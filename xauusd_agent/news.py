"""Economic-calendar news blackout.

Gold reacts violently to scheduled high-impact USD events (FOMC, CPI, NFP, PCE,
retail sales...). Trading into them is a coin-flip with brutal slippage, so a
prudent bot simply *steps aside* in a window around each event. This is a safety
control — it needs no backtest to justify; you never *want* to be in a fresh
trade at the FOMC release.

``NewsFilter`` holds the event times and answers "is ``ts`` inside a blackout?".
Supply events from a CSV exported from any economic calendar (Forex Factory,
investing.com, MT5), or as a plain list of datetimes.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd


class NewsFilter:
    """Marks timestamps that fall within ±window of a high-impact event."""

    def __init__(self, events: Sequence, before_min: int = 30, after_min: int = 30):
        ev = pd.to_datetime(pd.Series(list(events))).dropna()
        # normalise to tz-naive for consistent comparison with candle index
        if getattr(ev.dt, "tz", None) is not None:
            ev = ev.dt.tz_convert("UTC").dt.tz_localize(None)
        self.events = np.sort(ev.values.astype("datetime64[ns]"))
        self.before = pd.Timedelta(minutes=before_min)
        self.after = pd.Timedelta(minutes=after_min)

    @classmethod
    def from_csv(cls, path: str, datetime_col: Optional[str] = None,
                 impact_col: Optional[str] = "impact",
                 keep_impacts: Sequence[str] = ("High", "high", "HIGH", "3"),
                 **kwargs) -> "NewsFilter":
        """Load events from a calendar CSV, keeping only high-impact rows.

        Auto-detects the datetime column if not given. If an impact column exists
        it filters to ``keep_impacts``; otherwise every row is treated as an event.
        """
        df = pd.read_csv(path)
        cols = {c.lower(): c for c in df.columns}
        if datetime_col is None:
            for cand in ("datetime", "date", "time", "timestamp", "release_time"):
                if cand in cols:
                    datetime_col = cols[cand]
                    break
        if datetime_col is None:
            raise ValueError("could not find a datetime column in the calendar CSV")

        # if separate date + time columns, combine
        if datetime_col.lower() == "date" and "time" in cols:
            dt = pd.to_datetime(df[cols["date"]].astype(str) + " " + df[cols["time"]].astype(str),
                                errors="coerce")
        else:
            dt = pd.to_datetime(df[datetime_col], errors="coerce")

        impact_key = impact_col.lower() if impact_col else None
        if impact_key and impact_key in cols:
            keep = df[cols[impact_key]].astype(str).isin([str(k) for k in keep_impacts])
            dt = dt[keep]
        return cls(dt.dropna().tolist(), **kwargs)

    def in_blackout(self, ts, before_min: Optional[int] = None,
                    after_min: Optional[int] = None) -> bool:
        """True if ``ts`` is within the blackout window of any event."""
        if len(self.events) == 0:
            return False
        before = pd.Timedelta(minutes=before_min) if before_min is not None else self.before
        after = pd.Timedelta(minutes=after_min) if after_min is not None else self.after
        t = pd.Timestamp(ts)
        if t.tz is not None:
            t = t.tz_convert("UTC").tz_localize(None)
        t64 = np.datetime64(t.to_datetime64())
        # nearest event at or before t
        i = int(np.searchsorted(self.events, t64, side="right"))
        if i > 0:
            ev = pd.Timestamp(self.events[i - 1])
            if ev - before <= t <= ev + after:
                return True
        # nearest event after t (its 'before' window may already cover t)
        if i < len(self.events):
            ev = pd.Timestamp(self.events[i])
            if ev - before <= t <= ev + after:
                return True
        return False
