"""Smart-Money-Concepts strategy for XAUUSD day-trading / scalping.

The strategy is *causal*: it is handed a trailing window whose last row is the
just-closed candle and must decide using only that.  It layers the smc primitives
into a single ICT-style confluence:

    1. BIAS      - direction of the most recent confirmed BOS / CHoCH.
    2. TIMING    - (optional) only act inside London/NY kill-zones.
    3. ZONE      - an unmitigated Order Block in the bias direction that price is
                   currently retracing into.
    4. CONFLUENCE- (optional) a Fair Value Gap overlapping that order block.
    5. RISK MAP  - stop just beyond the order block; target the nearest opposing
                   liquidity pool, else a fixed reward:risk multiple.

It returns a structural ``Signal`` (entry / stop / target / reason).  Turning that
into a position size is the RiskManager's job, and placing it is the Broker's.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

from smartmoneyconcepts import smc

from .config import StrategyConfig, InstrumentSpec


class Side(str, Enum):
    NONE = "none"
    LONG = "long"
    SHORT = "short"


@dataclass
class Signal:
    """A proposed trade. ``side == Side.NONE`` means 'do nothing'."""

    side: Side
    entry: float = 0.0
    stop: float = 0.0
    take_profit: float = 0.0
    reason: str = ""
    # diagnostics
    ob_top: float = 0.0
    ob_bottom: float = 0.0
    ob_strength: float = 0.0
    has_fvg: bool = False

    @property
    def is_trade(self) -> bool:
        return self.side in (Side.LONG, Side.SHORT)

    @property
    def risk_distance(self) -> float:
        return abs(self.entry - self.stop)


NO_SIGNAL = Signal(side=Side.NONE, reason="no setup")


class SMCStrategy:
    def __init__(self, config: StrategyConfig, instrument: InstrumentSpec):
        self.cfg = config
        self.instrument = instrument

    # -- helpers ----------------------------------------------------------------

    def _session_active(self, window: pd.DataFrame) -> bool:
        if not self.cfg.require_session:
            return True
        for session in self.cfg.sessions:
            try:
                res = smc.sessions(
                    window, session=session, time_zone=self.cfg.time_zone
                )
            except Exception:
                continue
            if len(res) and int(res["Active"].iloc[-1]) == 1:
                return True
        return False

    @staticmethod
    def _current_bias(bos_choch: pd.DataFrame, last: int) -> Side:
        """Direction of the most recent confirmed structural break at/<= ``last``."""
        broken = bos_choch["BrokenIndex"].values
        bos = bos_choch["BOS"].values
        choch = bos_choch["CHOCH"].values
        best_pos = -1
        best_dir = 0.0
        for i in range(len(bos_choch)):
            b = broken[i]
            if np.isnan(b) or b > last:
                continue
            direction = bos[i] if not np.isnan(bos[i]) else choch[i]
            if np.isnan(direction):
                continue
            if b >= best_pos:                  # most recently *broken* structure wins
                best_pos = b
                best_dir = direction
        if best_dir > 0:
            return Side.LONG
        if best_dir < 0:
            return Side.SHORT
        return Side.NONE

    @staticmethod
    def _active_order_block(ob: pd.DataFrame, direction: int, last: int):
        """Most recent unmitigated order block in ``direction`` (1 long / -1 short)."""
        ob_vals = ob["OB"].values
        mit = ob["MitigatedIndex"].values
        best = None
        for i in range(len(ob)):
            if ob_vals[i] != direction:
                continue
            if i > last:
                continue
            mitigated = mit[i]
            if not np.isnan(mitigated) and mitigated != 0 and mitigated <= last:
                continue  # already mitigated/broken before now
            if best is None or i > best:
                best = i
        return best

    @staticmethod
    def _fvg_overlaps(fvg: pd.DataFrame, direction: int, top: float, bottom: float,
                      last: int) -> bool:
        f = fvg["FVG"].values
        ft = fvg["Top"].values
        fb = fvg["Bottom"].values
        mit = fvg["MitigatedIndex"].values
        for i in range(len(fvg)):
            if f[i] != direction or i > last:
                continue
            m = mit[i]
            if not np.isnan(m) and m != 0 and m <= last:
                continue
            # overlap of [bottom, top] with [fb, ft]
            if min(top, ft[i]) >= max(bottom, fb[i]):
                return True
        return False

    @staticmethod
    def _nearest_liquidity(liq: pd.DataFrame, direction: int, price: float,
                           last: int) -> Optional[float]:
        """Nearest opposing liquidity level to target (above for long, below short)."""
        levels = liq["Level"].values
        kinds = liq["Liquidity"].values
        best = None
        for i in range(len(liq)):
            if i > last or np.isnan(kinds[i]):
                continue
            lvl = levels[i]
            if direction == 1 and lvl > price:          # long -> buy-side liquidity above
                if best is None or lvl < best:
                    best = lvl
            elif direction == -1 and lvl < price:        # short -> sell-side liquidity below
                if best is None or lvl > best:
                    best = lvl
        return best

    def _recent_sweep(self, liq: pd.DataFrame, direction: int, last: int,
                      lookback: int) -> bool:
        """True if opposing liquidity was swept within ``lookback`` candles.

        Long (direction 1) wants sell-side liquidity (bearish pool, lows) swept;
        short wants buy-side liquidity (bullish pool, highs) swept — the ICT
        stop-hunt that precedes a reversal.
        """
        want = -1 if direction == 1 else 1
        kinds = liq["Liquidity"].values
        swept = liq["Swept"].values
        for i in range(len(liq)):
            if kinds[i] != want:
                continue
            s = swept[i]
            if not np.isnan(s) and s != 0 and (last - lookback) <= s <= last:
                return True
        return False

    def _regime(self, window: pd.DataFrame):
        """Classify the recent market as ('trend'|'range', trend_dir).

        Uses the Kaufman Efficiency Ratio over ``regime_lookback`` bars:
        ER = |close[t]-close[t-n]| / sum(|close diffs|). ER -> 1 means a clean
        directional move (trend); ER -> 0 means chop (range). ``trend_dir`` is the
        sign of the net move (1 up / -1 down / 0 flat). Causal: uses only closed bars.
        """
        n = self.cfg.regime_lookback
        closes = window["close"].values
        if len(closes) <= n + 1:
            return ("range", 0)
        seg = closes[-(n + 1):]
        net = seg[-1] - seg[0]
        path = float(np.abs(np.diff(seg)).sum())
        er = abs(net) / path if path > 0 else 0.0
        if er >= self.cfg.regime_er_threshold:
            return ("trend", 1 if net > 0 else (-1 if net < 0 else 0))
        return ("range", 0)

    def _htf_bias(self, window: pd.DataFrame) -> Optional[Side]:
        """Bias from a higher timeframe built by aggregating every N candles.

        Returns None when there isn't enough data to judge (treated as 'no veto').
        """
        m = max(2, self.cfg.htf_multiplier)
        if len(window) < m * (3 * self.cfg.swing_length + 5):
            return None
        groups = np.arange(len(window)) // m
        htf = window.groupby(groups).agg(
            open=("open", "first"), high=("high", "max"),
            low=("low", "min"), close=("close", "last"),
            volume=("volume", "sum"),
        ).reset_index(drop=True)
        if len(htf) < 3 * self.cfg.swing_length + 5:
            return None
        shl = smc.swing_highs_lows(htf, swing_length=self.cfg.swing_length)
        return self._current_bias(smc.bos_choch(htf, shl), len(htf) - 1)

    # -- main entry point -------------------------------------------------------

    def evaluate(self, window: pd.DataFrame) -> Signal:
        cfg = self.cfg
        if len(window) < max(3 * cfg.swing_length, 30):
            return NO_SIGNAL

        last = len(window) - 1
        close = float(window["close"].iloc[-1])
        high = float(window["high"].iloc[-1])
        low = float(window["low"].iloc[-1])

        if not self._session_active(window):
            return Signal(side=Side.NONE, reason="outside session")

        shl = smc.swing_highs_lows(window, swing_length=cfg.swing_length)
        bos_choch = smc.bos_choch(window, shl)
        bias = self._current_bias(bos_choch, last)
        if bias is Side.NONE:
            return Signal(side=Side.NONE, reason="no structural bias")

        direction = 1 if bias is Side.LONG else -1

        # Regime / trend-participation: in a trend, optionally only trade WITH it and
        # widen the target so winners run; in a range, behave as normal SMC.
        rr = cfg.default_rr
        regime, trend_dir = ("range", 0)
        if cfg.regime_enabled:
            regime, trend_dir = self._regime(window)
            if regime == "trend" and trend_dir != 0:
                if cfg.regime_block_counter_trend and direction != trend_dir:
                    return Signal(side=Side.NONE, reason="counter-trend in trend regime")
                rr = cfg.regime_trend_rr      # let winners run with the trend

        # Multi-timeframe confluence: entry must agree with the higher-timeframe bias.
        if cfg.require_htf_alignment:
            htf = self._htf_bias(window)
            if htf is not None and htf is not bias:
                return Signal(side=Side.NONE, reason="HTF bias misaligned")

        # Liquidity-sweep trigger: require a recent opposing stop-hunt.
        if cfg.require_liquidity_sweep:
            liq_s = smc.liquidity(window, shl, range_percent=cfg.liquidity_range_percent)
            if not self._recent_sweep(liq_s, direction, last, cfg.liquidity_sweep_lookback):
                return Signal(side=Side.NONE, reason="no liquidity sweep")

        ob = smc.ob(window, shl)
        ob_idx = self._active_order_block(ob, direction, last)
        if ob_idx is None:
            return Signal(side=Side.NONE, reason="no active order block")

        ob_top = float(ob["Top"].iloc[ob_idx])
        ob_bottom = float(ob["Bottom"].iloc[ob_idx])
        ob_strength = float(ob["Percentage"].iloc[ob_idx])
        if cfg.min_ob_strength and ob_strength < cfg.min_ob_strength:
            return Signal(side=Side.NONE, reason="order block too weak")

        # Price must be retracing *into* the order block right now.
        tapping = (low <= ob_top) and (high >= ob_bottom)
        if not tapping:
            return Signal(side=Side.NONE, reason="price not in order block")

        has_fvg = self._fvg_overlaps(
            smc.fvg(window), direction, ob_top, ob_bottom, last
        )
        if cfg.require_fvg and not has_fvg:
            return Signal(side=Side.NONE, reason="no FVG confluence")

        buffer = (ob_top - ob_bottom) * cfg.stop_buffer_frac
        if direction == 1:
            entry = close
            stop = ob_bottom - buffer
            target = None
            if cfg.target_liquidity:
                liq = smc.liquidity(window, shl, range_percent=cfg.liquidity_range_percent)
                target = self._nearest_liquidity(liq, 1, entry, last)
            if target is None or target <= entry:
                target = entry + rr * (entry - stop)
            side = Side.LONG
        else:
            entry = close
            stop = ob_top + buffer
            target = None
            if cfg.target_liquidity:
                liq = smc.liquidity(window, shl, range_percent=cfg.liquidity_range_percent)
                target = self._nearest_liquidity(liq, -1, entry, last)
            if target is None or target >= entry:
                target = entry - rr * (stop - entry)
            side = Side.SHORT

        if abs(entry - stop) <= 0:
            return Signal(side=Side.NONE, reason="degenerate stop")

        return Signal(
            side=side,
            entry=entry,
            stop=stop,
            take_profit=target,
            reason=f"{bias.value} OB tap"
            + (" + FVG" if has_fvg else "")
            + (f" [{regime}]" if cfg.regime_enabled else ""),
            ob_top=ob_top,
            ob_bottom=ob_bottom,
            ob_strength=ob_strength,
            has_fvg=has_fvg,
        )
