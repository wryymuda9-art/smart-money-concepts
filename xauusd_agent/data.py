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
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.set_index(date_col)
    else:
        df.index = pd.to_datetime(df.index)

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
    """Load and normalise an OHLCV csv (MetaTrader / generic exports)."""
    return normalise_ohlc(pd.read_csv(path), date_col=date_col)


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
