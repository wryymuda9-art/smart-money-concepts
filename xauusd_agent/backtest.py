"""Event-driven backtester.

Wires the four layers together on historical candles with strict causality:

    for each just-closed candle i:
        1. mark-to-market & trigger stops/targets for OPEN positions on candle i
        2. evaluate the strategy on data up to and including candle i
        3. if it returns a trade AND risk allows it -> open at the close of i
           (so the new position is only ever tested from candle i+1 onward)

This ordering guarantees the strategy never sees a candle it is about to trade on
before deciding, and a position can never be entered and exited on the same bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from .config import AgentConfig
from .data import iter_windows
from .strategy import SMCStrategy, Side
from .risk import RiskManager
from .broker import SimBroker, Order, ClosedTrade


@dataclass
class BacktestResult:
    config: AgentConfig
    equity_curve: pd.Series
    trades: List[ClosedTrade] = field(default_factory=list)

    # -- summary metrics --------------------------------------------------------

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def final_equity(self) -> float:
        return float(self.equity_curve.iloc[-1]) if len(self.equity_curve) else 0.0

    @property
    def total_return(self) -> float:
        start = self.config.starting_equity
        return (self.final_equity - start) / start if start else 0.0

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return wins / len(self.trades)

    @property
    def profit_factor(self) -> float:
        gross_win = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = -sum(t.pnl for t in self.trades if t.pnl < 0)
        if gross_loss == 0:
            return float("inf") if gross_win > 0 else 0.0
        return gross_win / gross_loss

    @property
    def expectancy(self) -> float:
        if not self.trades:
            return 0.0
        return float(np.mean([t.pnl for t in self.trades]))

    @property
    def max_drawdown(self) -> float:
        if self.equity_curve.empty:
            return 0.0
        running_max = self.equity_curve.cummax()
        drawdown = (self.equity_curve - running_max) / running_max
        return float(drawdown.min())

    def summary(self) -> dict:
        return {
            "trades": int(self.n_trades),
            "win_rate": round(float(self.win_rate), 4),
            "profit_factor": round(float(self.profit_factor), 4),
            "expectancy_usd": round(float(self.expectancy), 2),
            "total_return": round(float(self.total_return), 4),
            "max_drawdown": round(float(self.max_drawdown), 4),
            "final_equity": round(float(self.final_equity), 2),
        }

    def __str__(self) -> str:
        s = self.summary()
        return (
            f"Backtest {self.config.instrument.symbol}: "
            f"{s['trades']} trades | win {s['win_rate']:.1%} | "
            f"PF {s['profit_factor']:.2f} | ret {s['total_return']:.2%} | "
            f"maxDD {s['max_drawdown']:.2%} | eq ${s['final_equity']:,.0f}"
        )


class Backtester:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.strategy = SMCStrategy(config.strategy, config.instrument)
        self.risk = RiskManager(
            config.risk, config.instrument, starting_equity=config.starting_equity
        )
        self.broker = SimBroker(config.instrument, starting_equity=config.starting_equity,
                                management=config.management)

    def run(self, ohlc: pd.DataFrame, progress_every: int = 0) -> BacktestResult:
        cfg = self.config
        warmup = max(cfg.strategy.window, 3 * cfg.strategy.swing_length + 5)
        warmup = min(warmup, max(0, len(ohlc) - 1))

        times = ohlc.index
        highs = ohlc["high"].values
        lows = ohlc["low"].values
        closes = ohlc["close"].values

        eq_times: List = []
        eq_values: List[float] = []

        for count, (i, window) in enumerate(
            iter_windows(ohlc, cfg.strategy.window, warmup)
        ):
            when = times[i]
            h, l, c = float(highs[i]), float(lows[i]), float(closes[i])

            # 1. update existing positions on this candle
            self.broker.update(h, l, c, when)

            equity = self.broker.equity(c)
            eq_times.append(when)
            eq_values.append(equity)

            # 2. ask the strategy
            signal = self.strategy.evaluate(window)

            # 3. gate + size + open
            if signal.is_trade:
                today = pd.Timestamp(when).date()
                ok, _why = self.risk.can_trade(today, equity, self.broker.open_count)
                if ok and self.risk.spread_ok(cfg.instrument.sim_spread):
                    sizing = self.risk.size(signal, equity)
                    if sizing.approved:
                        self.broker.place(
                            Order(
                                side=signal.side,
                                lots=sizing.lots,
                                stop=signal.stop,
                                take_profit=signal.take_profit,
                                comment=signal.reason,
                            ),
                            ref_price=c,
                            when=when,
                        )
                        self.risk.register_fill()

            if progress_every and count % progress_every == 0 and count:
                print(f"  ...{count} candles, equity ${equity:,.0f}, "
                      f"{len(self.broker.closed)} closed trades")

        # close anything still open at the last price
        if len(closes):
            self.broker.close_all(float(closes[-1]), times[-1], reason="end")
            eq_times.append(times[-1])
            eq_values.append(self.broker.balance)

        equity_curve = pd.Series(eq_values, index=pd.Index(eq_times, name="time"),
                                 name="equity")
        return BacktestResult(cfg, equity_curve, list(self.broker.closed))
