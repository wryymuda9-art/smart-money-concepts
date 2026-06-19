"""Market-data loading and normalisation.

The smc library expects a DataFrame indexed by datetime with lowercase
``open, high, low, close`` (and ``volume``) columns. This module produces exactly
that from a few common sources and provides a tiny streaming helper used by the
backtester.
"""

from __future__ import annotations

from typing import Iterator, Optional, Tuple

import pandas as pd


_COLUMN_ALIASES = {
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "tickvol": "volume",  # MT5 export often has Tickvol + (zero) Volume
}


def _to_datetime(s: pd.Series) -> pd.DatetimeIndex:
    """Parse a time column to datetime, handling epoch ints (Dukascopy etc.).

    A plain ``pd.to_datetime`` reads bare integers as *nanoseconds*, which mangles
    epoch-seconds/millis exports. Detect the unit from magnitude instead.
    """
    num = pd.to_numeric(s, errors="coerce")
    if num.notna().all():                       # purely numeric -> epoch timestamp
        mx = float(num.abs().max())
        if mx >= 1e17:
            unit = "ns"
        elif mx >= 1e14:
            unit = "us"
        elif mx >= 1e11:
            unit = "ms"                          # Dukascopy / dukascopy-node default
        else:
            unit = "s"
        return pd.DatetimeIndex(pd.to_datetime(num.to_numpy(), unit=unit))
    return pd.DatetimeIndex(pd.to_datetime(s.to_numpy()))


def normalise_ohlc(df: pd.DataFrame, date_col: Optional[str] = None) -> pd.DataFrame:
    """Return a clean OHLCV frame: datetime index, lowercase columns.

    Accepts mixed-case columns and a few aliases (e.g. MT5 ``Tickvol``).  If the
    frame has no real ``volume`` (all zero, as in many MT5 exports) tick volume is
    used so volume-based indicators (order blocks) still function.
    """
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    if date_col is None:
        for cand in ("date", "datetime", "time", "timestamp"):
            if cand in df.columns:
                date_col = cand
                break
    if date_col is not None and date_col in df.columns:
        df = df.set_index(_to_datetime(df[date_col]))
        df = df.drop(columns=[date_col], errors="ignore")
    else:
        df.index = _to_datetime(pd.Series(df.index))

    # Pick volume: prefer a non-zero 'volume', else fall back to tick volume.
    if "volume" not in df.columns or df.get("volume", pd.Series(dtype=float)).fillna(0).eq(0).all():
        if "tickvol" in df.columns:
            df["volume"] = df["tickvol"]

    keep = ["open", "high", "low", "close", "volume"]
    missing = [c for c in ("open", "high", "low", "close") if c not in df.columns]
    if missing:
        raise ValueError(f"input is missing required column(s): {missing}")
    if "volume" not in df.columns:
        df["volume"] = 0.0

    df = df[keep].astype(float).sort_index()
    return df


def load_csv(path: str, date_col: Optional[str] = None) -> pd.DataFrame:
    """Load and normalise an OHLCV csv (MetaTrader / Dukascopy / generic exports).

    Epoch timestamps (e.g. Dukascopy's millisecond ``timestamp`` column) are
    detected and parsed automatically, so a Dukascopy CSV loads with no fuss.
    """
    return normalise_ohlc(pd.read_csv(path), date_col=date_col)


# Free, no-account, any-OS gold history. ``dukascopy-node`` (Node CLI) writes a
# ``timestamp,open,high,low,close,volume`` CSV that load_csv reads directly.
DUKASCOPY_HINT = (
    "Get free XAUUSD history from Dukascopy (no account, any OS):\n"
    "  npx dukascopy-node -i xauusd -from 2022-01-01 -to 2025-01-01 \\\n"
    "    -t m15 -f csv -v true -dir .\n"
    "then:  python -m xauusd_agent validate --csv xauusd-*-m15-*.csv --regime"
)


def fetch_dukascopy(instrument: str, start: str, end: str, timeframe: str = "m15",
                    out_dir: str = ".") -> str:
    """Download free history via the ``dukascopy-node`` CLI; return the CSV path.

    Requires Node.js (``npx`` on PATH). This is the easiest free, no-account,
    cross-platform source for deep intraday gold data. On any failure it raises
    with the manual command (``DUKASCOPY_HINT``) so you can run it by hand.
    """
    import glob
    import subprocess

    cmd = ["npx", "--yes", "dukascopy-node", "-i", instrument.lower(),
           "-from", start, "-to", end, "-t", timeframe.lower(),
           "-f", "csv", "-v", "true", "-dir", out_dir]
    try:
        subprocess.run(cmd, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            f"dukascopy-node download failed ({exc}). Run it manually:\n{DUKASCOPY_HINT}"
        ) from exc
    matches = sorted(glob.glob(f"{out_dir}/{instrument.lower()}-*-{timeframe.lower()}-*.csv"))
    if not matches:
        raise RuntimeError(f"no CSV produced in {out_dir}; expected dukascopy-node output")
    return matches[-1]


# HistData.com "Generic ASCII" M1 bars: free, no account, but manual download
# (their site has no clean API). Format is headerless, semicolon-delimited:
#   YYYYMMDD HHMMSS;open;high;low;close;volume   (volume is always 0 for FX/metals)
HISTDATA_HINT = (
    "Download free M1 history from histdata.com -> 'Generic ASCII' (one zip per\n"
    "month), unzip the DAT_ASCII_*.csv, then:\n"
    "  python -m xauusd_agent validate --csv DAT_ASCII_XAUUSD_M1_2024.csv --regime"
)


def load_histdata(path: str) -> pd.DataFrame:
    """Load a HistData.com 'Generic ASCII' M1 bar CSV into the standard frame.

    Headerless, semicolon-delimited, timestamp ``YYYYMMDD HHMMSS``. Volume is 0 in
    these exports, so order-block strength (volume-based) is weaker — fine for a
    free deep-history backtest, but prefer MT5/Dukascopy tick volume if you have it.
    """
    df = pd.read_csv(
        path, sep=";", header=None,
        names=["datetime", "open", "high", "low", "close", "volume"],
    )
    df["datetime"] = pd.to_datetime(df["datetime"], format="%Y%m%d %H%M%S")
    return normalise_ohlc(df, date_col="datetime")


def iter_windows(
    ohlc: pd.DataFrame, window: int, warmup: int
) -> Iterator[Tuple[int, pd.DataFrame]]:
    """Yield ``(i, window_df)`` for each decision point.

    ``window_df`` contains only candles up to and including index ``i`` (the
    just-closed candle) so a strategy evaluated on it can never see the future.
    The trailing window is capped at ``window`` rows to bound compute cost.
    """
    n = len(ohlc)
    for i in range(warmup, n):
        start = max(0, i - window + 1)
        yield i, ohlc.iloc[start : i + 1]
