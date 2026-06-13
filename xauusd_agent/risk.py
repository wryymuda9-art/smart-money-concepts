"""Risk management and position sizing.

This is the layer that decides *how much* to trade and *whether* a trade is
allowed at all.  It is deliberately independent of how signals are generated and
how orders are routed, so it can be unit-tested in isolation and reused by both
the backtester and a live agent.

Position sizing uses fixed-fractional risk:

    risk_money   = equity * risk_per_trade
    stop_dist    = |entry - stop|                     (price units, USD/oz)
    money/lot    = stop_dist * money_per_price_per_lot (USD lost per 1.0 lot if stopped)
    lots         = risk_money / money/lot              (rounded down to lot_step)

so the loss if the stop is hit is ~`risk_per_trade` of equity regardless of how
wide the stop is — wider stops automatically get smaller size.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .config import RiskConfig, InstrumentSpec
from .strategy import Signal


@dataclass
class SizingDecision:
    approved: bool
    lots: float = 0.0
    risk_money: float = 0.0
    reason: str = ""


@dataclass
class RiskManager:
    config: RiskConfig
    instrument: InstrumentSpec
    starting_equity: float = 10_000.0

    # mutable day-tracking state
    _day: Optional[date] = field(default=None, init=False)
    _day_start_equity: float = field(default=0.0, init=False)
    _trades_today: int = field(default=0, init=False)
    _halted_today: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self._day_start_equity = self.starting_equity

    # -- daily roll-over --------------------------------------------------------

    def _roll_day(self, today: date, equity: float) -> None:
        if self._day != today:
            self._day = today
            self._day_start_equity = equity
            self._trades_today = 0
            self._halted_today = False

    def register_fill(self) -> None:
        self._trades_today += 1

    # -- gatekeeping ------------------------------------------------------------

    def can_trade(self, today: date, equity: float, open_positions: int) -> tuple[bool, str]:
        self._roll_day(today, equity)

        if self._halted_today:
            return False, "daily loss limit hit"

        # Re-check the daily drawdown each call (equity moves intraday).
        daily_pnl = equity - self._day_start_equity
        if daily_pnl <= -self.config.max_daily_loss * self._day_start_equity:
            self._halted_today = True
            return False, "daily loss limit hit"

        if self._trades_today >= self.config.max_daily_trades:
            return False, "max daily trades reached"

        if open_positions >= self.config.max_open_positions:
            return False, "max open positions reached"

        return True, "ok"

    # -- sizing -----------------------------------------------------------------

    def size(self, signal: Signal, equity: float) -> SizingDecision:
        if not signal.is_trade:
            return SizingDecision(False, reason="not a trade signal")

        stop_dist = signal.risk_distance
        if stop_dist < self.config.min_stop_distance:
            return SizingDecision(False, reason="stop distance below minimum")

        risk_money = equity * self.config.risk_per_trade
        money_per_lot = stop_dist * self.instrument.money_per_price_per_lot
        if money_per_lot <= 0:
            return SizingDecision(False, reason="invalid stop distance")

        raw_lots = risk_money / money_per_lot

        # round DOWN to the broker lot step so we never exceed the risk budget
        step = self.instrument.lot_step
        lots = math.floor(raw_lots / step) * step
        lots = round(lots, 8)

        if lots < self.instrument.min_lot:
            return SizingDecision(
                False,
                reason=(
                    f"required size {lots:.4f} < min lot {self.instrument.min_lot} "
                    "(stop too wide for risk budget)"
                ),
            )
        lots = min(lots, self.instrument.max_lot)

        return SizingDecision(
            approved=True,
            lots=lots,
            risk_money=lots * money_per_lot,
            reason="sized",
        )

    def spread_ok(self, spread: float) -> bool:
        return spread <= self.instrument.max_spread
