"""Market-data feeds.

A *feed* is the thing that hands the agent the latest trailing window of candles.
Two implementations share one tiny interface so the live loop is identical in
testing and production:

    class DataFeed:
        symbol: str
        def latest_window(self, n) -> pd.DataFrame          # newest n candles
        def wait_next_candle(self) -> Optional[pd.Timestamp] # block until a new bar

* ``CsvDataFeed``  - replays a CSV/DataFrame candle-by-candle (backtest / paper).
* ``Mt5DataFeed``  - reads live bars from a MetaTrader 5 terminal via
  ``MetaTrader5.copy_rates_*``. Imported lazily (Windows-only), so this module
  stays importable everywhere.

``Mt5DataFeed`` also doubles as the way to pull XAUUSD *history* to a CSV for
backtesting (:meth:`Mt5DataFeed.download`).
"""

from __future__ import annotations

import time
from typing import Optional

import pandas as pd

from .data import normalise_ohlc


# String timeframe -> (mt5 attribute name, pandas seconds) -------------------
_TIMEFRAMES = {
    "M1": ("TIMEFRAME_M1", 60),
    "M5": ("TIMEFRAME_M5", 300),
    "M15": ("TIMEFRAME_M15", 900),
    "M30": ("TIMEFRAME_M30", 1800),
    "H1": ("TIMEFRAME_H1", 3600),
    "H4": ("TIMEFRAME_H4", 14400),
    "D1": ("TIMEFRAME_D1", 86400),
}


def _normalise_timeframe(tf: str) -> str:
    key = tf.upper().replace("MIN", "M").replace("HOUR", "H")
    if key not in _TIMEFRAMES:
        raise ValueError(f"unknown timeframe {tf!r}; use one of {list(_TIMEFRAMES)}")
    return key


class CsvDataFeed:
    """Replay a DataFrame as if candles were arriving one at a time.

    Used for backtest / paper. ``wait_next_candle`` simply advances an internal
    cursor (no real waiting); ``latest_window`` returns history up to it.
    """

    def __init__(self, ohlc: pd.DataFrame, symbol: str = "XAUUSD", start_at: int = 1):
        self.symbol = symbol
        self.ohlc = ohlc
        self._cursor = max(0, start_at - 1)  # index of the latest available candle

    @classmethod
    def from_csv(cls, path: str, symbol: str = "XAUUSD", **kw) -> "CsvDataFeed":
        from .data import load_csv
        return cls(load_csv(path), symbol=symbol, **kw)

    def latest_window(self, n: int) -> pd.DataFrame:
        end = self._cursor + 1
        return self.ohlc.iloc[max(0, end - n) : end]

    def wait_next_candle(self) -> Optional[pd.Timestamp]:
        if self._cursor >= len(self.ohlc) - 1:
            return None
        self._cursor += 1
        return self.ohlc.index[self._cursor]

    @property
    def exhausted(self) -> bool:
        return self._cursor >= len(self.ohlc) - 1


class Mt5DataFeed:
    """Live OHLC feed backed by a MetaTrader 5 terminal.

    Reads bars with ``copy_rates_from_pos`` and blocks for new candles by polling
    the most recent bar's open time. ``MetaTrader5`` is imported lazily so the
    package runs on non-Windows hosts; this class only works where MT5 is
    installed and a terminal is running/logged in.
    """

    def __init__(self, symbol: str = "XAUUSD", timeframe: str = "M5",
                 login: Optional[int] = None, password: Optional[str] = None,
                 server: Optional[str] = None, poll_secs: float = 1.0):
        self.symbol = symbol
        self.timeframe = _normalise_timeframe(timeframe)
        self.login = login
        self.password = password
        self.server = server
        self.poll_secs = poll_secs
        self._mt5 = None
        self._tf_const = None
        self._last_time: Optional[pd.Timestamp] = None

    # -- connection -------------------------------------------------------------

    def connect(self) -> "Mt5DataFeed":
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError as exc:  # pragma: no cover - host dependent
            raise RuntimeError(
                "MetaTrader5 package is not installed. `pip install MetaTrader5` "
                "on a Windows host with a running MT5 terminal to read live data."
            ) from exc

        kwargs = {}
        if self.login:
            kwargs.update(login=self.login, password=self.password, server=self.server)
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")
        if mt5.symbol_info(self.symbol) is None:
            raise RuntimeError(f"symbol {self.symbol!r} not found on this MT5 account")
        mt5.symbol_select(self.symbol, True)
        self._mt5 = mt5
        self._tf_const = getattr(mt5, _TIMEFRAMES[self.timeframe][0])
        return self

    def _require(self):
        if self._mt5 is None:
            raise RuntimeError("Mt5DataFeed.connect() must be called first.")
        return self._mt5

    # -- bar access -------------------------------------------------------------

    @staticmethod
    def _rates_to_df(rates) -> pd.DataFrame:
        df = pd.DataFrame(rates)
        if df.empty:
            return df
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("time")
        # MT5 gives tick_volume / real_volume; map tick_volume -> volume
        if "tick_volume" in df.columns:
            df = df.rename(columns={"tick_volume": "volume"})
        return normalise_ohlc(df)

    def latest_window(self, n: int, include_forming: bool = False) -> pd.DataFrame:
        """Return the newest ``n`` *closed* candles (drops the forming bar)."""
        mt5 = self._require()
        # +1 so we can drop the still-forming current bar
        rates = mt5.copy_rates_from_pos(self.symbol, self._tf_const, 0, n + 1)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"copy_rates returned nothing: {mt5.last_error()}")
        df = self._rates_to_df(rates)
        if not include_forming and len(df) > 1:
            df = df.iloc[:-1]   # last row is the live, unfinished candle
        return df.tail(n)

    def copy_range(self, start, end) -> pd.DataFrame:
        """Historical bars between two datetimes (for downloads/backtests)."""
        mt5 = self._require()
        rates = mt5.copy_rates_range(
            self.symbol, self._tf_const, pd.Timestamp(start).to_pydatetime(),
            pd.Timestamp(end).to_pydatetime())
        if rates is None:
            raise RuntimeError(f"copy_rates_range failed: {mt5.last_error()}")
        return self._rates_to_df(rates)

    def download(self, start, end, path: str) -> pd.DataFrame:
        """Pull history and save it as a CSV usable by the backtester."""
        df = self.copy_range(start, end)
        out = df.reset_index().rename(columns={"time": "Date"})
        out.to_csv(path, index=False)
        return df

    def wait_next_candle(self, timeout: Optional[float] = None) -> Optional[pd.Timestamp]:
        """Block until a new *closed* candle appears; return its open time."""
        mt5 = self._require()
        waited = 0.0
        while True:
            df = self.latest_window(1)
            if len(df):
                ts = df.index[-1]
                if self._last_time is None or ts > self._last_time:
                    self._last_time = ts
                    return ts
            if timeout is not None and waited >= timeout:
                return None
            time.sleep(self.poll_secs)
            waited += self.poll_secs

    def shutdown(self) -> None:
        if self._mt5 is not None:
            self._mt5.shutdown()
            self._mt5 = None
