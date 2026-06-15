# XAUUSD SMC Agent — Project Handover

A complete, honest summary of what was built, how to run it, what the results
actually say, and what it would take to make it a profitable, live bot.

> **One-line status:** a fully built, tested, deployable XAUUSD scalping/day-trading
> bot whose *machinery* is complete and trustworthy, but whose *trading edge is
> unproven* — and on the only real data available it **underperformed buy-and-hold**.
> Educational project; not investment advice; do not trade real money on it as-is.

---

## 1. What this is

An algorithmic agent for **XAUUSD (gold)** day-trading and scalping, built on top of
the repo's `smartmoneyconcepts` (ICT / Smart Money Concepts) indicator library. It
turns SMC chart structure into buy/sell decisions, sizes them by risk, manages the
trade, and executes — in simulation (backtest/paper) or live on MetaTrader 5.

The upstream `smartmoneyconcepts` library is **untouched**; everything lives in the
separate `xauusd_agent/` package.

## 2. Architecture

```
DataFeed → Strategy(SMC) → RiskManager → TradeManagement → Broker(Sim|MT5)
              │                │                                  │
        NewsFilter         sizing/limits                  Dashboard / Journal
              └──────────── Backtester / TradingAgent ───────────┘
                     Research: metrics · sweep · walk-forward
                     Robustness: Monte-Carlo · buy & hold
```

| Module | Responsibility |
|---|---|
| `config.py` | All parameters as dataclasses (instrument, risk, strategy, management, news). |
| `data.py` / `feed.py` | Load/normalise OHLCV; CSV replay feed and lazy MT5 live feed (`copy_rates`). |
| `strategy.py` | SMC confluence → `Signal`: BOS/CHoCH bias → kill-zone → order block → FVG → liquidity-sweep / HTF filters. |
| `risk.py` | Fixed-fractional sizing + daily-loss / max-trades / max-positions / spread gates. |
| `broker.py` | `SimBroker` (deterministic fills + break-even/trailing/partial management) and lazy `Mt5Broker`. |
| `backtest.py` | Causal event loop + `BacktestResult` metrics. |
| `agent.py` / `live.py` | `TradingAgent` orchestrator; real-time loop for paper/live. |
| `research.py` | Risk-aware metrics, parameter sweep, walk-forward (out-of-sample) validation. |
| `robustness.py` | Monte-Carlo bootstrap + buy-and-hold benchmark. |
| `viz.py` / `report.py` | Live SMC dashboard; performance tearsheet (equity + drawdown). |
| `news.py` / `journal.py` | Economic-calendar blackout; trade journal + restart state persistence. |
| `configio.py` | Run from a YAML/JSON config file. |

**36 unit tests** (`tests/test_agent.py`), all passing; CI in `.github/workflows/agent-tests.yaml`.

## 3. How to run

```bash
# install deps (core)
pip install pandas numpy numba pyyaml          # +plotly kaleido for charts, +MetaTrader5 for live

# backtest on bundled real gold, with a tearsheet and Monte-Carlo
SMC_CREDIT=0 python -m xauusd_agent backtest \
    --config xauusd_agent/config.example.yaml \
    --csv tests/test_data/XAUUSD/XAUUSD_M15.csv \
    --report-png report.png --montecarlo 5000

# parameter sweep / out-of-sample walk-forward
python -m xauusd_agent optimize    --timeframe M15 --objective profit_factor
python -m xauusd_agent walkforward --timeframe M15 --splits 3

# live SMC dashboard (HTML auto-refresh)
python -m xauusd_agent dashboard --csv your.csv --html dash.html

# MetaTrader 5 (Windows): pull history, then run paper / live
python -m xauusd_agent download --symbol XAUUSD --timeframe M15 --start 2023-01-01 --end 2025-01-01 --out gold.csv
python -m xauusd_agent live --symbol XAUUSD --timeframe M15            # paper (no orders)
python -m xauusd_agent live --symbol XAUUSD --timeframe M15 --execute  # live (sends orders)
```

The strategy entry criteria, in order: enough history → in kill-zone (optional) →
confirmed BOS/CHoCH bias → (optional HTF agreement) → (optional liquidity sweep) →
unmitigated order block price is tapping → (optional FVG overlap) → stop beyond the
block, target nearest opposing liquidity or a fixed R. Then risk gates + sizing.

## 4. Honest results (real XAUUSD data)

All on $10,000, 0.5% risk/trade, costs included. **Bundled data is short** (4H:
2020–22; M15: ~2 months 2025–26; M5: ~4 weeks 2026), so every result is
statistically `weak`/`none`.

| Style | Best config | Return | Max DD | PF | Trades | Significance |
|---|---|---|---|---|---|---|
| Swing 4H | strict | −0.7% | −2.1% | 0.73 | 13 | none |
| Day-trade M15 | baseline | −0.9% | −2.9% | 0.95 | 57 | weak |
| **Day-trade M15** | **+ partial TP & trailing** | **+1.9%** | −3.1% | 1.14 | 102* | weak |
| Scalp M5 | + HTF filter | +1.3% | −3.1% | 1.15 | 33 | weak |

\* partial take-profits split each trade into 2 legs, inflating the count.

**Key honest findings:**
1. **Trade management helped** — partial-TP + trailing lifted M15 from PF 0.95→1.14
   (−0.9% → +1.9%). The biggest single structural improvement.
2. **Parameter tuning could NOT be validated.** Walk-forward showed in-sample
   performance had *no* relationship to out-of-sample (one fold IS PF 0.35 → OOS
   4.76; another IS 3.82 → OOS 0.32). Optimising on this little data fits noise.
3. **Monte-Carlo (5,000 sims) on the +1.9% config:** distribution −3.6%..+7.5%,
   **73% chance of profit** — a weak, low-conviction edge.
4. **Buy-and-hold over the same window returned +10.1%.** The active strategy
   captured +1.9% of a +10% gold rally — **it badly underperformed simply holding.**

## 5. What this does and does NOT establish

* ✅ The engine runs end-to-end on real gold, sizes risk correctly, contains
  drawdown (~2–3%), and is safe/observable (news blackout, journal, restart state).
* ❌ It does **not** show a profitable edge. On the one measurable period it lagged
  the benchmark. The data is too short and single-regime (a trend) to conclude
  anything durable — and what we can measure is unflattering.

## 6. The path to a real, live-ready edge

In priority order — note that **#1 gates everything**; further code is secondary.

1. **Data.** Get **1–3 years of M15/M5 gold across regimes** (trending *and*
   ranging). Then re-run `walkforward` + `montecarlo` for a verdict with
   `moderate`/`ok` significance and a fair buy-and-hold comparison.
2. **Beat the benchmark.** The strategy must be judged vs buy-and-hold. If it can't
   beat holding in trends, it needs a trend-participation mode (e.g. let winners run
   far past fixed targets, or a regime filter that only mean-reverts in ranges).
3. **Realistic costs.** Add commission and variable/news-widened spread before
   trusting any backtest, especially for scalping.
4. **Validate before risking money:** walk-forward green → demo/paper forward-test
   for weeks → only then `--execute` live, small size.

## 7. Remaining nice-to-haves (built only if data shows an edge worth deploying)

Telegram/email alerts on fills+errors · live-runner daemon with reconnect ·
session-filter timezone confirmation · cost-sensitivity sweep · richer dashboard
panels · pip packaging of `xauusd_agent` as its own distribution.

---

*Built iteratively with honest validation at every step. The most valuable thing
this project produced is not a money-maker — it's an apparatus that tells you the
truth about a strategy instead of a cherry-picked backtest.*
