"""Robustness analysis: Monte-Carlo bootstrap and a buy-and-hold benchmark.

A single backtest gives one number. These tools quantify *how much to trust it*:

* ``monte_carlo`` resamples the realised trade P&L sequence (with replacement)
  thousands of times to build a distribution of outcomes — so instead of "the
  return was +1.9%" you get "+1.9% observed; 5th–95th percentile −3% .. +7%;
  probability of profit 62%". That directly exposes how luck-driven a small
  sample is.

* ``buy_and_hold_return`` is the do-nothing benchmark over the same window — a
  strategy that can't beat just holding gold isn't adding value.
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from .backtest import BacktestResult


def _max_drawdown(equity: np.ndarray) -> float:
    running_max = np.maximum.accumulate(equity)
    return float(((equity - running_max) / running_max).min())


def monte_carlo(result: BacktestResult, n_sims: int = 5000, seed: int = 0) -> Dict[str, Any]:
    """Bootstrap the trade-P&L sequence to estimate the outcome distribution."""
    pnls = np.array([t.pnl for t in result.trades], dtype=float)
    start = result.config.starting_equity
    n = len(pnls)
    if n == 0:
        return {"trades": 0, "note": "no trades to bootstrap"}

    rng = np.random.default_rng(seed)
    returns = np.empty(n_sims)
    drawdowns = np.empty(n_sims)
    for i in range(n_sims):
        sample = rng.choice(pnls, size=n, replace=True)
        equity = start + np.cumsum(sample)
        returns[i] = (equity[-1] - start) / start
        drawdowns[i] = _max_drawdown(np.concatenate([[start], equity]))

    def pct(a, q):
        return round(float(np.percentile(a, q)), 4)

    observed_return = (result.final_equity - start) / start
    return {
        "trades": int(n),
        "sims": int(n_sims),
        "observed_return": round(float(observed_return), 4),
        "return_p5": pct(returns, 5),
        "return_p50": pct(returns, 50),
        "return_p95": pct(returns, 95),
        "maxdd_p5": pct(drawdowns, 5),
        "maxdd_p50": pct(drawdowns, 50),
        "maxdd_median": pct(drawdowns, 50),
        "prob_profit": round(float((returns > 0).mean()), 4),
        "prob_beat_5pct": round(float((returns > 0.05).mean()), 4),
    }


def buy_and_hold_return(ohlc: pd.DataFrame) -> float:
    """Fractional price change over the data window (the do-nothing benchmark)."""
    if len(ohlc) < 2:
        return 0.0
    first = float(ohlc["close"].iloc[0])
    last = float(ohlc["close"].iloc[-1])
    return (last - first) / first if first else 0.0
