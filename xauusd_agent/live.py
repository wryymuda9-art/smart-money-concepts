"""Drive the agent candle-by-candle and feed a live dashboard.

``run_live_replay`` replays historical candles as if they were arriving in
real time: for each new closed candle it advances the paper agent one step
(updating positions, triggering stops/targets, possibly opening a trade) and
re-renders the :class:`~xauusd_agent.viz.LiveDashboard`.

The exact same loop works against real data — swap the historical iterator for a
broker/data feed that yields the latest candle, and point the agent at an
``Mt5Broker`` for live execution.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from .config import AgentConfig
from .agent import TradingAgent
from .viz import LiveDashboard, DashboardConfig


def run_live_replay(
    config: AgentConfig,
    ohlc: pd.DataFrame,
    dashboard: Optional[LiveDashboard] = None,
    *,
    plot_window: int = 120,
    render_every: int = 1,
    png_path: Optional[str] = None,
    png_every: int = 0,
    max_candles: Optional[int] = None,
    verbose: bool = True,
) -> TradingAgent:
    """Replay ``ohlc`` through a paper agent, refreshing ``dashboard`` as it goes.

    Returns the agent (inspect ``agent.broker.closed`` / ``.positions``).
    """
    agent = TradingAgent(config)              # SimBroker / paper by default
    broker = agent.broker
    dashboard = dashboard or LiveDashboard(cfg=DashboardConfig())

    warmup = min(config.strategy.window, max(0, len(ohlc) - 1))
    closes = ohlc["close"].values
    times = ohlc.index
    n = len(ohlc)
    rendered = 0

    for i in range(warmup, n):
        window = ohlc.iloc[max(0, i - config.strategy.window + 1) : i + 1]
        result = agent.step(window, when=times[i])

        if verbose and result.acted:
            print(f"[{times[i]}] {result.signal.side.value.upper()} "
                  f"{result.lots:.2f} lots — {result.signal.reason}")

        if (i - warmup) % render_every == 0:
            plot_df = ohlc.iloc[max(0, i - plot_window + 1) : i + 1]
            equity = broker.equity(float(closes[i]))
            snap = png_path if (png_every and rendered % png_every == 0) else None
            dashboard.update(plot_df, equity, config.starting_equity,
                             broker.positions, broker.closed, png_path=snap)
            rendered += 1

        if max_candles is not None and (i - warmup) >= max_candles:
            break

    # final render
    last_i = min(i, n - 1)
    plot_df = ohlc.iloc[max(0, last_i - plot_window + 1) : last_i + 1]
    dashboard.update(plot_df, broker.equity(float(closes[last_i])),
                     config.starting_equity, broker.positions, broker.closed,
                     png_path=png_path)
    if verbose:
        print(f"dashboard written to {dashboard.html_path}"
              + (f" (snapshot {png_path})" if png_path else ""))
    return agent
