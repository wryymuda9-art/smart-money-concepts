# Getting real data → a real return number

The agent ships with only a short bundled sample, so every backtest says
`NOT VALIDATED` (too few trades to mean anything). To get a real number you need
**months-to-years of intraday history**. This guide gets you there with **free,
no-account** data in a few minutes.

> Why it matters: a verdict needs ~100+ out-of-sample trades. M15 over ~2–3 years
> clears that bar; a few weeks does not.

> **Note:** this must run on **your own machine** (or a VPS) — it needs internet
> access to the data provider, which CI/cloud sandboxes block.

---

## Fastest path — one turnkey command

```bash
git clone <this repo> && cd smart-money-concepts
./xauusd_agent/scripts/quickstart.sh
```
It installs deps, fetches ~3 years of free M15 gold from Dukascopy, and prints the
`=== VERDICT ===`. Needs Python 3 and Node.js. Everything below is the manual
breakdown of what it does.

---

## Option A — Dukascopy (recommended: free, no account, any OS)

Best free source for deep intraday gold. Needs **Node.js** (for `npx`).

**One command (fetch + validate):**
```bash
xauusd_agent/scripts/get_and_validate.sh --source dukascopy \
  -s XAUUSD -t M15 -b 2022-01-01 -e 2025-01-01
```
This downloads ~3 years of M15 gold from Dukascopy and prints the
`=== VERDICT ===` line with the trend/regime mode on.

**Or do it by hand:**
```bash
npx dukascopy-node -i xauusd -from 2022-01-01 -to 2025-01-01 -t m15 -f csv -v true -dir .
python -m xauusd_agent validate --csv xauusd-*-m15-*.csv --regime
```
`load_csv` auto-detects Dukascopy's millisecond timestamps — no conversion needed.

---

## Option B — HistData.com (free, no account, manual download)

1. Go to histdata.com → Forex → **XAUUSD** → **Generic ASCII**, M1.
2. Download a month (or several) and unzip the `DAT_ASCII_XAUUSD_M1_*.csv`.
3. Load and validate:
```python
from xauusd_agent.data import load_histdata
ohlc = load_histdata("DAT_ASCII_XAUUSD_M1_2024.csv")
```
```bash
python -m xauusd_agent validate --csv DAT_ASCII_XAUUSD_M1_2024.csv --regime
```
> Caveat: HistData bars have **zero volume**, so order-block strength (volume-based)
> is weaker. Fine for a free backtest; prefer Dukascopy/MT5 if you can.

---

## Option C — MT5 demo (free, also gives LIVE data) — Windows only

A free demo account from any broker (IC Markets, Pepperstone, FxPro, RoboForex,
XM, Tickmill) gives deep history **and** live streaming for paper/live trading.

1. Install MetaTrader 5 + `pip install MetaTrader5` on a **Windows** host.
2. Open the demo account, note its **login / server / password**.
3. Fetch + validate:
```bash
xauusd_agent/scripts/get_and_validate.sh --source mt5 \
  -s XAUUSD -t M15 -b 2022-01-01 -e 2025-01-01 \
  --login <id> --server <Broker-Server> --password '<pw>'
```
4. Later, paper/live trade against the same terminal:
```bash
python -m xauusd_agent live   # see README "Paper / live" section
```

---

## Reading the verdict

```
[walk-forward] ... OOS: 142 trades | PF 1.31 | avgR 0.18 | ret 9.4% | maxDD -6.1% | conf moderate
  buy & hold over window: +41.0%
=== VERDICT ===
 ...
```

- **trades** — under ~100 it's noise. Widen the date range (`-b` earlier) for more.
- **conf** — `none`/`weak` → unproven; `moderate`/`ok` → start trusting it.
- **PF > 1 and avgR > 0** out-of-sample is the edge. Compare **ret vs buy & hold** —
  beating it in a trending market is the whole point of the regime mode.

## A/B the trend mode
```bash
xauusd_agent/scripts/get_and_validate.sh --source dukascopy              # regime ON
xauusd_agent/scripts/get_and_validate.sh --source dukascopy --no-regime  # baseline
```

## Next steps once validated
1. Optimize on real data: `python -m xauusd_agent walkforward --csv <file> --splits 6`.
2. Add the USD macro filter: `validate ... --dxy-csv DX_M15.csv`.
3. Paper-trade on an MT5 demo for a few weeks before any real capital.

Paste me the verdict line + trade count and I'll help you read and tune it.
