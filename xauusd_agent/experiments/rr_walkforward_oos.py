"""Out-of-sample validation: the RR sweep on the SECOND half (~2017-2022),
which the in-sample optimization never saw. This is the test that decides
whether the fixed-RR improvement is a real edge or curve-fitting.
"""
from xauusd_agent.config import AgentConfig, Mode
from xauusd_agent.backtest import Backtester
from xauusd_agent.data import load_csv
from xauusd_agent.research import compute_metrics

import sys
CSV = sys.argv[1] if len(sys.argv) > 1 else "xauusd_h1_real.csv"
ohlc = load_csv(CSV)
half = len(ohlc) // 2
oos = ohlc.iloc[half:]
print("OUT-OF-SAMPLE: %d candles  %s -> %s" % (
    len(oos), oos.index.min(), oos.index.max()), flush=True)

def best():
    c = AgentConfig(mode=Mode.BACKTEST)
    c.management.trailing_enabled = True
    c.management.trailing_at_r = 1.0
    c.management.trailing_distance_r = 1.0
    return c

variants = {}
variants["baseline (nearest-liquidity target)"] = best()
for rr in (3.0, 4.0, 5.0):
    c = best()
    c.strategy.target_liquidity = False
    c.strategy.default_rr = rr
    variants["fixed RR %.0f:1" % rr] = c

print("%-34s %6s %6s %6s %8s %7s" % ("variant", "trades", "win%", "PF", "return", "sharpe"))
for name, cfg in variants.items():
    r = Backtester(cfg).run(oos)
    m = compute_metrics(r)
    print("%-34s %6d %5.1f%% %6.3f %7.2f%% %7.3f" % (
        name, m["trades"], m["win_rate"] * 100, m["profit_factor"],
        m["total_return"] * 100, m["sharpe"]), flush=True)
print("DONE")
