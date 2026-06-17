"""Macro / news directional bias for gold.

Encodes *how gold is affected* by the dominant macro forces, as a directional
bias (+1 bullish / -1 bearish / 0 neutral) that the agent can use to filter trades
(take only setups that agree with the macro direction).

The single most reliable relationship is **USD up -> gold down** (gold is priced
in dollars and pays no yield), so ``MacroBias.from_dxy`` derives gold's bias from
the trend of the US Dollar Index. You can also supply any bias series directly
(e.g. derived from real yields, a calendar surprise, or your own view) via
``MacroBias.from_series``.

Honest note: these are *tendencies, not certainties* — gold can rally on inflation
fear even with a firm dollar, and moves are often pre-priced. Treat the bias as an
odds tilt / filter, not a prediction to bet the account on.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


class MacroBias:
    """A datetime-indexed series of gold bias values in {-1, 0, +1}."""

    def __init__(self, bias: pd.Series):
        b = pd.Series(bias).copy()
        b.index = pd.to_datetime(b.index)
        self.bias = b.sort_index()

    # -- constructors -----------------------------------------------------------

    @classmethod
    def from_dxy(cls, dxy: pd.DataFrame, lookback: int = 20,
                 deadband: float = 0.0) -> "MacroBias":
        """Gold bias from the US Dollar Index trend: **DXY up -> gold bearish**.

        ``lookback`` bars define the trend window; ``deadband`` (in DXY price units)
        suppresses noise — within it the bias is neutral (0).
        """
        df = dxy.copy()
        df.columns = [c.lower() for c in df.columns]
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        close = df["close"].astype(float)
        change = close - close.shift(lookback)
        bias = np.where(change > deadband, -1,
                        np.where(change < -deadband, 1, 0))
        return cls(pd.Series(bias, index=close.index, dtype="int64"))

    @classmethod
    def from_dxy_csv(cls, path: str, lookback: int = 20, deadband: float = 0.0,
                     date_col: Optional[str] = None) -> "MacroBias":
        """Load a US Dollar Index OHLC csv (MT5 / generic export) and derive the
        gold bias from its trend. Same column handling as the gold loader, so a
        DXY export sits next to your gold CSV and just works.
        """
        from .data import load_csv
        return cls.from_dxy(load_csv(path, date_col=date_col),
                            lookback=lookback, deadband=deadband)

    @classmethod
    def from_series(cls, df: pd.DataFrame, col: str = "bias") -> "MacroBias":
        """Use an explicit bias series (values coerced to sign -1/0/+1)."""
        s = df[col] if isinstance(df, pd.DataFrame) else df
        return cls(pd.Series(np.sign(pd.Series(s).astype(float)).astype("int64"),
                             index=pd.Series(s).index))

    # -- query ------------------------------------------------------------------

    def bias_at(self, ts) -> int:
        """Most recent bias at or before ``ts`` (0 if none / before the series)."""
        if len(self.bias) == 0:
            return 0
        t = pd.Timestamp(ts)
        idx = self.bias.index.searchsorted(t, side="right")
        if idx <= 0:
            return 0
        return int(self.bias.iloc[idx - 1])

    def allows(self, ts, direction: int) -> bool:
        """True if a trade in ``direction`` (+1 long / -1 short) agrees with the
        macro bias (or the bias is neutral)."""
        mb = self.bias_at(ts)
        return mb == 0 or mb == direction
