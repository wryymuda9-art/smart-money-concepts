"""Top-level orchestrator.

``TradingAgent`` is the single object an application interacts with.  In
BACKTEST mode it delegates to :class:`Backtester`.  In PAPER / LIVE mode it
exposes :meth:`step`, which you call once per closed candle with the latest
trailing window; the agent runs the same Strategy -> Risk -> Broker pipeline.

LIVE is opt-in and guarded: you must pass a connected ``Mt5Broker`` and set
``config.mode = Mode.LIVE`` yourself.  Nothing here connects to a real account on
its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd

from .config import AgentConfig, Mode
from .strategy import SMCStrategy, Signal, Side
from .risk import RiskManager
from .broker import SimBroker, Mt5Broker, Order
from .backtest import Backtester, BacktestResult


@dataclass
class StepResult:
    signal: Signal
    acted: bool
    reason: str
    lots: float = 0.0


class TradingAgent:
    def __init__(self, config: AgentConfig, broker=None, news_filter=None,
                 macro_bias=None, journal=None):
        self.config = config
        self.news_filter = news_filter
        self.macro_bias = macro_bias
        self.journal = journal
        self.strategy = SMCStrategy(config.strategy, config.instrument)
        self.risk = RiskManager(
            config.risk, config.instrument, starting_equity=config.starting_equity
        )
        if broker is not None:
            self.broker = broker
        elif config.mode is Mode.LIVE:
            raise ValueError(
                "Mode.LIVE requires an explicit connected broker, e.g. "
                "TradingAgent(cfg, broker=Mt5Broker(cfg.instrument)). Refusing to "
                "auto-create a live connection."
            )
        else:
            self.broker = SimBroker(config.instrument, config.starting_equity,
                                    management=config.management)

    # -- backtest ---------------------------------------------------------------

    def backtest(self, ohlc: pd.DataFrame, progress_every: int = 0) -> BacktestResult:
        bt = Backtester(self.config, news_filter=self.news_filter,
                        macro_bias=self.macro_bias)
        return bt.run(ohlc, progress_every=progress_every)

    # -- live / paper step ------------------------------------------------------

    def _equity(self, last_close: float) -> float:
        if isinstance(self.broker, Mt5Broker):
            return self.broker.account_equity()
        return self.broker.equity(last_close)

    def _open_count(self) -> int:
        if isinstance(self.broker, Mt5Broker):
            return self.broker.open_count()
        return self.broker.open_count

    def step(self, window: pd.DataFrame, when=None, spread: Optional[float] = None) -> StepResult:
        """Evaluate the latest closed candle and act (paper or live)."""
        when = when if when is not None else window.index[-1]
        last_close = float(window["close"].iloc[-1])

        # roll the sim broker's exits forward on the latest candle (paper only;
        # the live broker manages SL/TP server-side)
        if isinstance(self.broker, SimBroker):
            self.broker.update(
                float(window["high"].iloc[-1]),
                float(window["low"].iloc[-1]),
                last_close,
                when,
            )

        # news blackout: optionally flatten, and block new entries
        blackout = (self.config.news.enabled and self.news_filter is not None
                    and self.news_filter.in_blackout(
                        when, self.config.news.before_min, self.config.news.after_min))
        if blackout and self.config.news.flatten_open and isinstance(self.broker, SimBroker):
            self.broker.close_all(last_close, when, reason="news")

        signal = self.strategy.evaluate(window)
        if not signal.is_trade:
            return StepResult(signal, False, signal.reason)
        if blackout:
            return StepResult(signal, False, "news blackout")

        # macro bias: skip setups that fight gold's macro direction
        if (self.config.macro.enabled and self.macro_bias is not None
                and self.config.macro.mode == "filter"
                and not self.macro_bias.allows(
                    when, 1 if signal.side is Side.LONG else -1)):
            return StepResult(signal, False, "against macro bias")

        today = pd.Timestamp(when).date()
        equity = self._equity(last_close)
        ok, why = self.risk.can_trade(today, equity, self._open_count())
        if not ok:
            return StepResult(signal, False, why)

        spread = spread if spread is not None else self.config.instrument.sim_spread
        if not self.risk.spread_ok(spread):
            return StepResult(signal, False, "spread too wide")

        sizing = self.risk.size(signal, equity)
        if not sizing.approved:
            return StepResult(signal, False, sizing.reason)

        order = Order(
            side=signal.side,
            lots=sizing.lots,
            stop=signal.stop,
            take_profit=signal.take_profit,
            comment=signal.reason,
        )
        if isinstance(self.broker, Mt5Broker):
            self.broker.place(order)
        else:
            self.broker.place(order, ref_price=last_close, when=when)
        self.risk.register_fill()
        if self.journal is not None:
            self.journal.log("entry", when, side=signal.side.value, lots=sizing.lots,
                             entry=last_close, stop=signal.stop, take_profit=signal.take_profit,
                             reason=signal.reason)
        return StepResult(signal, True, "order placed", lots=sizing.lots)
