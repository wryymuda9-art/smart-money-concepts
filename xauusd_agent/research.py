"""Validation harness: trustworthy metrics, parameter sweeps, walk-forward.

A single backtest on one period is a *noisy* number — easy to fool yourself with.
This module exists to make results believable:

* ``compute_metrics``  — richer, risk-aware stats (avg-R, Sharpe, Sortino, CAGR,
  payoff, drawdown, and a **significance flag** based on trade count).
* ``sweep``            — grid-search parameters, one row of metrics per combo.
* ``walk_forward``     — optimise on in-sample, measure on the *next, unseen*
  out-of-sample slice, repeat, and report the **stitched OOS** performance. This
  is the honest number: it cannot be curve-fit because each param set is judged
  only on data it never saw during selection.

Everything is timeframe-agnostic; ``periods_per_year`` is inferred from the
equity-curve timestamps so Sharpe/CAGR annualise correctly for M5 or 4H alike.
"""

from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from .config import AgentConfig
from .backtest import Backtester, BacktestResult


# -- metrics --------------------------------------------------------------------

def _infer_periods_per_year(index: pd.Index) -> float:
    if len(index) < 3:
        return 252.0
    deltas = pd.Series(pd.to_datetime(index)).diff().dropna()
    sec = deltas.dt.total_seconds().median()
    if not sec or sec <= 0:
        return 252.0
    return (365.25 * 24 * 3600) / sec


def compute_metrics(result: BacktestResult,
                    periods_per_year: Optional[float] = None) -> Dict[str, Any]:
    """Risk-aware metrics for a finished backtest."""
    trades = result.trades
    eq = result.equity_curve
    cfg = result.config
    n = len(trades)

    pnls = np.array([t.pnl for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]

    # realised R multiple per trade: pnl / planned dollar risk at entry
    rs = []
    for t in trades:
        p = t.position
        planned = abs(p.entry - p.stop) * p.lots * p.money_per_price_per_lot
        if planned > 0:
            rs.append(t.pnl / planned)
    rs = np.array(rs, dtype=float)

    gross_win = float(wins.sum())
    gross_loss = float(-losses.sum())

    if periods_per_year is None:
        periods_per_year = _infer_periods_per_year(eq.index)

    rets = eq.pct_change().dropna().values if len(eq) > 2 else np.array([])
    sharpe = sortino = 0.0
    if rets.size and rets.std(ddof=1) > 0:
        sharpe = float(rets.mean() / rets.std(ddof=1) * np.sqrt(periods_per_year))
    if rets.size:
        downside = rets[rets < 0]
        if downside.std(ddof=1) > 0 if downside.size > 1 else False:
            sortino = float(rets.mean() / downside.std(ddof=1) * np.sqrt(periods_per_year))

    # CAGR from the equity-curve span
    cagr = 0.0
    if len(eq) > 1:
        span_years = (pd.to_datetime(eq.index[-1]) - pd.to_datetime(eq.index[0])).total_seconds() / (365.25 * 24 * 3600)
        if span_years > 0 and eq.iloc[0] > 0:
            cagr = float((eq.iloc[-1] / cfg.starting_equity) ** (1 / span_years) - 1)

    # longest losing streak
    streak = max_streak = 0
    for p in pnls:
        if p < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    return {
        "trades": int(n),
        "win_rate": round(float((pnls > 0).mean()) if n else 0.0, 4),
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0),
        "expectancy_usd": round(float(pnls.mean()) if n else 0.0, 2),
        "avg_R": round(float(rs.mean()), 3) if rs.size else 0.0,
        "payoff": round(float(wins.mean() / -losses.mean()), 3) if wins.size and losses.size else 0.0,
        "total_return": round(float(result.total_return), 4),
        "cagr": round(cagr, 4),
        "max_drawdown": round(float(result.max_drawdown), 4),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "max_consec_losses": int(max_streak),
        "final_equity": round(float(result.final_equity), 2),
        # statistical confidence in the result, from sample size alone
        "significance": ("none" if n < 30 else "weak" if n < 100 else "moderate" if n < 300 else "ok"),
    }


# -- parameter plumbing ---------------------------------------------------------

def _set_param(cfg: AgentConfig, dotted: str, value: Any) -> None:
    """Set e.g. 'strategy.swing_length' or 'risk.risk_per_trade' on a config."""
    obj = cfg
    parts = dotted.split(".")
    for p in parts[:-1]:
        obj = getattr(obj, p)
    setattr(obj, parts[-1], value)


def run_with_params(base: AgentConfig, ohlc: pd.DataFrame,
                    params: Dict[str, Any]) -> BacktestResult:
    cfg = copy.deepcopy(base)
    for k, v in params.items():
        _set_param(cfg, k, v)
    return Backtester(cfg).run(ohlc)


# -- grid sweep -----------------------------------------------------------------

def sweep(base: AgentConfig, ohlc: pd.DataFrame, grid: Dict[str, Sequence[Any]],
          sort_by: str = "profit_factor", min_trades: int = 0,
          verbose: bool = False) -> pd.DataFrame:
    """Backtest every combination in ``grid``; return a metrics table.

    ``grid`` maps dotted config paths to value lists, e.g.::

        {"strategy.swing_length": [4, 6, 8], "strategy.require_fvg": [True, False]}
    """
    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    rows = []
    for i, combo in enumerate(combos):
        params = dict(zip(keys, combo))
        result = run_with_params(base, ohlc, params)
        metrics = compute_metrics(result)
        if metrics["trades"] < min_trades:
            continue
        rows.append({**params, **metrics})
        if verbose:
            print(f"  [{i+1}/{len(combos)}] {params} -> "
                  f"PF {metrics['profit_factor']}, trades {metrics['trades']}, "
                  f"avgR {metrics['avg_R']}")
    df = pd.DataFrame(rows)
    if len(df) and sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=False).reset_index(drop=True)
    return df


# -- walk-forward ---------------------------------------------------------------

@dataclass
class WalkForwardResult:
    splits: List[Dict[str, Any]] = field(default_factory=list)   # per-fold chosen params + OOS metrics
    oos_metrics: Dict[str, Any] = field(default_factory=dict)     # stitched out-of-sample
    objective: str = "profit_factor"

    def summary(self) -> Dict[str, Any]:
        return {
            "folds": len(self.splits),
            "objective": self.objective,
            "oos": self.oos_metrics,
            "chosen_params_per_fold": [s["params"] for s in self.splits],
        }

    def __str__(self) -> str:
        o = self.oos_metrics
        return (f"WalkForward ({len(self.splits)} folds, opt={self.objective}) "
                f"OOS: {o.get('trades',0)} trades | PF {o.get('profit_factor',0)} | "
                f"avgR {o.get('avg_R',0)} | ret {o.get('total_return',0):.2%} | "
                f"maxDD {o.get('max_drawdown',0):.2%} | conf {o.get('significance','?')}")


def walk_forward(base: AgentConfig, ohlc: pd.DataFrame, grid: Dict[str, Sequence[Any]],
                 n_splits: int = 4, is_frac: float = 0.6, objective: str = "profit_factor",
                 min_is_trades: int = 8, verbose: bool = False) -> WalkForwardResult:
    """Rolling walk-forward: optimise on IS, test on the next OOS slice, stitch OOS.

    The data is cut into ``n_splits`` rolling blocks; in each block the first
    ``is_frac`` is in-sample (parameters are grid-searched and the best by
    ``objective`` is chosen), and the remainder is out-of-sample (tested once with
    those params). The concatenated OOS trades/equity are the headline result.
    """
    n = len(ohlc)
    block = n // n_splits
    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))

    oos_trades = []
    wf = WalkForwardResult(objective=objective)

    for s in range(n_splits):
        start = s * block
        stop = n if s == n_splits - 1 else (s + 1) * block
        seg = ohlc.iloc[start:stop]
        cut = int(len(seg) * is_frac)
        is_data, oos_data = seg.iloc[:cut], seg.iloc[cut:]
        if len(oos_data) < base.strategy.window + 10 or len(is_data) < base.strategy.window + 10:
            if verbose:
                print(f"  fold {s+1}: skipped (segment too short for window)")
            continue

        # optimise on in-sample
        best_params, best_score = None, -np.inf
        for combo in combos:
            params = dict(zip(keys, combo))
            m = compute_metrics(run_with_params(base, is_data, params))
            score = m.get(objective, -np.inf)
            if m["trades"] < min_is_trades:
                score = -np.inf
            if score > best_score:
                best_score, best_params = score, params
        if best_params is None:
            best_params = dict(zip(keys, combos[0]))

        # measure on out-of-sample
        oos_result = run_with_params(base, oos_data, best_params)
        oos_m = compute_metrics(oos_result)
        wf.splits.append({"fold": s + 1, "params": best_params,
                          "is_score": round(float(best_score), 4) if np.isfinite(best_score) else None,
                          "oos": oos_m})
        oos_trades.extend(oos_result.trades)
        if verbose:
            print(f"  fold {s+1}: chose {best_params} (IS {objective}={best_score:.3f}) "
                  f"-> OOS PF {oos_m['profit_factor']}, trades {oos_m['trades']}, avgR {oos_m['avg_R']}")

    # Build one continuous OOS account by chaining trade P&L chronologically
    # (each fold restarts at starting_equity, so we can't concat raw equity curves).
    if oos_trades:
        trades_sorted = sorted(oos_trades, key=lambda t: pd.Timestamp(t.close_time))
        times = pd.Index([pd.Timestamp(t.close_time) for t in trades_sorted], name="time")
        equity = base.starting_equity + np.cumsum([t.pnl for t in trades_sorted])
        stitched = pd.Series(equity, index=times, name="equity")
        agg = BacktestResult(base, stitched, trades_sorted)
        wf.oos_metrics = compute_metrics(agg)
    return wf
