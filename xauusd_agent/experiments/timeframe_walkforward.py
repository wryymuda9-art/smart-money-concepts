"""Higher-timeframe walk-forward: does 4H or daily gold hold an edge?

Hypothesis: the hourly edge decayed below the cost line partly because hourly
trades too often (cost drag). Higher timeframes trade less -> less drag. Test the
same in-sample/out-of-sample split on 4H and daily, with the proven fixed-RR lever.
"""
from xauusd_agent.config import AgentConfig, Mode
from xauusd_agent.backtest import Backtester
from xauusd_agent.data import load_csv
from xauusd_agent.research import compute_metrics

import sys
CSV = sys.argv[1] if len(sys.argv) > 1 else "xauusd_h1_real.csv"
h1 = load_csv(CSV)
agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}

def best(rr=None):
    c = AgentConfig(mode=Mode.BACKTEST)
    c.management.trailing_enabled = True
    c.management.trailing_at_r = 1.0
    c.management.trailing_distance_r = 1.0
    if rr is not None:
        c.strategy.target_liquidity = False
        c.strategy.default_rr = rr
    return c

variants = [("baseline (nearest-liq)", best()),
            ("fixed RR 3:1", best(3.0)),
            ("fixed RR 5:1", best(5.0))]

for tf_label, rule in [("4H", "4h"), ("DAILY", "1D")]:
    df = h1.resample(rule).agg(agg).dropna()
    half = len(df) // 2
    ins, oos = df.iloc[:half], df.iloc[half:]
    print("\n############ %s  (%d candles, %s -> %s) ############" % (
        tf_label, len(df), df.index.min().date(), df.index.max().date()), flush=True)
    print("%-24s %5s %6s | %-18s %5s %6s" % (
        "variant (IN-SAMPLE)", "PF", "ret%", "(OUT-OF-SAMPLE)", "PF", "ret%"))
    for name, cfg in variants:
        mi = compute_metrics(Backtester(cfg).run(ins))
        mo = compute_metrics(Backtester(cfg).run(oos))
        print("%-24s %5.2f %6.1f | %-18s %5.2f %6.1f  (n=%d/%d)" % (
            name, mi["profit_factor"], mi["total_return"] * 100, "",
            mo["profit_factor"], mo["total_return"] * 100,
            mi["trades"], mo["trades"]), flush=True)
print("\nDONE")
