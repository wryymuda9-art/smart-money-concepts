"""Entry-quality sweep: HTF / liquidity-sweep / regime filters on the trailing config.

Usage: python xauusd_agent/experiments/entry_sweep.py <ohlc.csv>
See xauusd_agent/FINDINGS.md for how to produce the CSV and the results.
"""
import sys
from xauusd_agent.config import AgentConfig, Mode
from xauusd_agent.backtest import Backtester
from xauusd_agent.data import load_csv
from xauusd_agent.robustness import buy_and_hold_return

CSV = sys.argv[1] if len(sys.argv) > 1 else "xauusd_h1_real.csv"
ohlc = load_csv(CSV)

def base():
    # proven baseline: strict + trailing stop (best from the management sweep)
    c = AgentConfig(mode=Mode.BACKTEST)
    c.management.trailing_enabled = True
    c.management.trailing_at_r = 1.0
    c.management.trailing_distance_r = 1.0
    return c

variants = {}

variants["trailing only (carry-over)"] = base()

c = base(); c.strategy.require_htf_alignment = True
variants["+ HTF alignment"] = c

c = base(); c.strategy.require_liquidity_sweep = True
variants["+ liquidity sweep"] = c

c = base(); c.strategy.regime_enabled = True
variants["+ regime (with-trend)"] = c

# everything on together -- strictest entry quality
c = base()
c.strategy.require_htf_alignment = True
c.strategy.require_liquidity_sweep = True
c.strategy.regime_enabled = True
variants["+ all three"] = c

print("buy & hold over window: %+.2f%%" % (buy_and_hold_return(ohlc) * 100))
print("=" * 80)
print("%-30s %7s %6s %6s %9s %8s" % ("variant", "trades", "win%", "PF", "return", "maxDD"))
print("-" * 80)
for name, cfg in variants.items():
    r = Backtester(cfg).run(ohlc)
    s = r.summary()
    print("%-30s %7d %5.1f%% %6.2f %8.2f%% %7.2f%%" % (
        name, s["trades"], s["win_rate"] * 100, s["profit_factor"],
        s["total_return"] * 100, s["max_drawdown"] * 100), flush=True)
print("=" * 80)
print("DONE")
