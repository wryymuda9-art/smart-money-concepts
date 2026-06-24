"""Trade-management sweep: baseline vs break-even / trailing on real gold data.

Usage: python xauusd_agent/experiments/mgmt_experiment.py <ohlc.csv>
See xauusd_agent/FINDINGS.md for how to produce the CSV and the results.
"""
import sys
from xauusd_agent.config import AgentConfig, Mode
from xauusd_agent.backtest import Backtester
from xauusd_agent.data import load_csv
from xauusd_agent.robustness import buy_and_hold_return

CSV = sys.argv[1] if len(sys.argv) > 1 else "xauusd_h1_real.csv"
ohlc = load_csv(CSV)

def make():
    # mirror the CLI strict baseline exactly: plain AgentConfig defaults
    return AgentConfig(mode=Mode.BACKTEST)

variants = {}

# 1. baseline (no management) -- the -2.0% strict result, recomputed for apples-to-apples
variants["baseline (strict, no mgmt)"] = make()

# 2. break-even: move stop to entry once +1R in profit
c = make(); c.management.breakeven_enabled = True; c.management.breakeven_at_r = 1.0
variants["+ break-even @1R"] = c

# 3. trailing: trail 1R behind best price once +1R in profit
c = make(); c.management.trailing_enabled = True; c.management.trailing_at_r = 1.0
c.management.trailing_distance_r = 1.0
variants["+ trailing 1R @1R"] = c

# 4. both together
c = make()
c.management.breakeven_enabled = True; c.management.breakeven_at_r = 1.0
c.management.trailing_enabled = True; c.management.trailing_at_r = 1.0
c.management.trailing_distance_r = 1.0
variants["+ break-even & trailing"] = c

print("buy & hold over window: %+.2f%%" % (buy_and_hold_return(ohlc) * 100))
print("=" * 78)
print("%-28s %7s %6s %6s %9s %8s" % ("variant", "trades", "win%", "PF", "return", "maxDD"))
print("-" * 78)
for name, cfg in variants.items():
    r = Backtester(cfg).run(ohlc)
    s = r.summary()
    print("%-28s %7d %5.1f%% %6.2f %8.2f%% %7.2f%%" % (
        name, s["trades"], s["win_rate"] * 100, s["profit_factor"],
        s["total_return"] * 100, s["max_drawdown"] * 100))
print("=" * 78)
print("DONE")
