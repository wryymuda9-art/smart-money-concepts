"""Drive the agent from a data feed and refresh the live dashboard.

``run_live`` is the single real-time loop used by both paper and live trading:

    every new closed candle:
        window = feed.latest_window(strategy.window)   # read bars
        agent.step(window)                             # decide + size + (maybe) order
        dashboard.update(...)                          # redraw chart

Point ``feed`` at a :class:`~xauusd_agent.feed.CsvDataFeed` for an offline
replay, or an :class:`~xauusd_agent.feed.Mt5DataFeed` for real data; pass an
``Mt5Broker`` to actually place orders. Nothing here connects on its own.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from .config import AgentConfig
from .agent import TradingAgent
from .broker import SimBroker
from .feed import CsvDataFeed
from .viz import LiveDashboard


def run_live(
    config: AgentConfig,
    feed,
    dashboard: Optional[LiveDashboard] = None,
    *,
    broker=None,
    plot_window: int = 120,
    render_every: int = 1,
    png_path: Optional[str] = None,
    png_every: int = 0,
    max_candles: Optional[int] = None,
    verbose: bool = True,
) -> TradingAgent:
    """Run the real-time loop against ``feed`` until it is exhausted/``max_candles``.

    Returns the agent (inspect ``agent.broker`` for sim results).
    """
    agent = TradingAgent(config, broker=broker)
    is_sim = isinstance(agent.broker, SimBroker)

    processed = 0
    rendered = 0
    while True:
        ts = feed.wait_next_candle()
        if ts is None:
            break

        window = feed.latest_window(config.strategy.window)
        if len(window) < max(3 * config.strategy.swing_length, 30):
            continue

        result = agent.step(window, when=ts)
        if verbose and result.acted:
            print(f"[{ts}] {result.signal.side.value.upper()} "
                  f"{result.lots:.2f} lots — {result.signal.reason}")

        if dashboard is not None and processed % render_every == 0:
            plot_df = window.tail(plot_window)
            last_close = float(window["close"].iloc[-1])
            if is_sim:
                equity = agent.broker.equity(last_close)
                positions, closed = agent.broker.positions, agent.broker.closed
            else:
                equity = agent._equity(last_close)
                positions, closed = (), ()   # MT5 manages fills server-side
            snap = png_path if (png_every and rendered % png_every == 0) else None
            dashboard.update(plot_df, equity, config.starting_equity,
                             positions, closed, png_path=snap)
            rendered += 1

        processed += 1
        if max_candles is not None and processed >= max_candles:
            break

    # final render
    if dashboard is not None:
        window = feed.latest_window(config.strategy.window)
        plot_df = window.tail(plot_window)
        last_close = float(window["close"].iloc[-1]) if len(window) else 0.0
        if is_sim:
            equity = agent.broker.equity(last_close)
            positions, closed = agent.broker.positions, agent.broker.closed
        else:
            equity, positions, closed = config.starting_equity, (), ()
        dashboard.update(plot_df, equity, config.starting_equity,
                         positions, closed, png_path=png_path)
        if verbose:
            print(f"dashboard written to {dashboard.html_path}"
                  + (f" (snapshot {png_path})" if png_path else ""))
    return agent


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
    """Offline convenience: replay a DataFrame through :func:`run_live`."""
    feed = CsvDataFeed(ohlc, symbol=config.instrument.symbol,
                       start_at=min(config.strategy.window, max(1, len(ohlc) - 1)))
    return run_live(config, feed, dashboard, plot_window=plot_window,
                    render_every=render_every, png_path=png_path, png_every=png_every,
                    max_candles=max_candles, verbose=verbose)
