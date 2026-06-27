"""Gross-edge test: does removing trading costs lift the best config above PF 1.0?

If yes -> a real edge is being eaten by friction (fixable: trade less / bigger targets).
If no  -> no edge underneath; the entry logic itself must change.
"""
import json
from xauusd_agent.config import AgentConfig, Mode
from xauusd_agent.backtest import Backtester
from xauusd_agent.data import load_csv
from xauusd_agent.research import compute_metrics

import sys
CSV = sys.argv[1] if len(sys.argv) > 1 else "xauusd_h1_real.csv"
ohlc = load_csv(CSV)

def best():
    c = AgentConfig(mode=Mode.BACKTEST)
    c.management.trailing_enabled = True
    c.management.trailing_at_r = 1.0
    c.management.trailing_distance_r = 1.0
    return c

# 1. best config WITH costs (reference)
with_costs = best()

# 2. best config with ZERO costs -> the gross edge
zero = best()
zero.instrument.sim_spread = 0.0
zero.instrument.sim_slippage = 0.0
zero.instrument.commission_per_lot = 0.0

for name, cfg in [("WITH costs (real)", with_costs), ("ZERO costs (gross edge)", zero)]:
    r = Backtester(cfg).run(ohlc)
    m = compute_metrics(r)
    print("=== %s ===" % name)
    print("  trades=%d  win=%.1f%%  PF=%.3f  return=%.2f%%  sharpe=%.3f" % (
        m["trades"], m["win_rate"] * 100, m["profit_factor"],
        m["total_return"] * 100, m["sharpe"]), flush=True)
print("DONE")
