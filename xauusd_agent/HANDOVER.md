# XAUUSD SMC Agent — Project Handover

A complete, honest summary of what was built, how to run it, what the results
actually say, and what it would take to make it a profitable, live bot.

> **One-line status:** a fully built, tested, deployable XAUUSD scalping/day-trading
> bot whose edge is **NOT yet statistically validated**. The bundled "13-month"
> dataset is only ~105 *partial* trading days (heavily stitched/gapped), so the
> walk-forward yields just **~11–19 out-of-sample trades** — and the OOS result
> **flips sign with a single toggle** (FVG on → +1.3% PF 1.50; FVG off → −1.4% PF
> 0.74). That is noise, not a proven edge. The machinery is sound and honest; the
> verdict is *"insufficient data — get real continuous history and re-run."*
> Educational project; not investment advice; **do not trade real money on it.**

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
     News + Macro filter   sizing/limits                  Dashboard / Journal
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
| `news.py` / `macro.py` | Economic-calendar event blackout; USD/DXY directional **macro bias filter** (`MacroBias`, off by default). |
| `journal.py` / `configio.py` | Trade journal + restart state persistence; run from a YAML/JSON config file. |

**41 unit tests** (`tests/test_agent.py`), all passing; CI in `.github/workflows/agent-tests.yaml`.

## 3. How to run

```bash
# install deps (core)
pip install pandas numpy numba pyyaml          # +plotly kaleido for charts, +MetaTrader5 for live

# backtest on bundled real gold, with a tearsheet and Monte-Carlo
SMC_CREDIT=0 python -m xauusd_agent backtest \
    --config xauusd_agent/config.example.yaml \
    --csv tests/test_data/XAUUSD/XAUUSD_M15.csv \
    --report-png report.png --montecarlo 5000

# ONE-COMMAND HONEST VERDICT (backtest + Monte-Carlo + walk-forward + buy&hold)
python -m xauusd_agent validate --csv your_gold.csv --tf M15 --splits 4
#   ...add the macro/USD filter by dropping in a Dollar-Index export:
python -m xauusd_agent validate --csv your_gold.csv --dxy-csv your_dxy.csv

# parameter sweep / out-of-sample walk-forward
python -m xauusd_agent optimize    --timeframe M15 --objective profit_factor
python -m xauusd_agent walkforward --timeframe M15 --splits 3

# live SMC dashboard (HTML auto-refresh)
python -m xauusd_agent dashboard --csv your.csv --html dash.html

# MetaTrader 5 (Windows): pull history (now PAGED — multi-year pulls aren't truncated)
python -m xauusd_agent download --symbol XAUUSD --timeframe M15 --start 2022-01-01 --end 2025-01-01 --out gold.csv
python -m xauusd_agent download --symbol USDX   --timeframe M15 --start 2022-01-01 --end 2025-01-01 --out dxy.csv   # for the macro filter
#   (DXY symbol name varies by broker: USDX / DX / DXY / "US Dollar Index")
python -m xauusd_agent live --symbol XAUUSD --timeframe M15            # paper (no orders)
python -m xauusd_agent live --symbol XAUUSD --timeframe M15 --execute  # live (sends orders)
```

The strategy entry criteria, in order: enough history → in kill-zone (optional) →
confirmed BOS/CHoCH bias → (optional HTF agreement) → (optional liquidity sweep) →
unmitigated order block price is tapping → (optional FVG overlap) → stop beyond the
block, target nearest opposing liquidity or a fixed R. Then risk gates + sizing.

## 4. Honest results (real XAUUSD data)

All on $10,000, 0.5% risk/trade, costs included (JustMarkets Pro: 0.18 spread +
0.03 slippage). The headline test is the **bundled "13-month" multi-regime M15
dataset** (`XAUUSD_M15_multi.csv`, 7,504 candles, 2025-03 .. 2026-04).

> ⚠️ **Re-validation (2026-06) overturned the earlier optimistic read.** The
> numbers below are not reproducible as a stable edge — they sit inside the noise
> of a tiny sample. Treat this section as *"why we can't conclude yet,"* not as a
> performance claim.

**The sample is far too small.** Although the set *spans* 393 calendar days, it
contains only **~105 distinct, partial trading days** (~71 candles/day vs 96 for a
full M15 session) — it's stitched/gapped from public sources. After the strategy's
selectivity, a 4-fold walk-forward leaves only **~11–19 out-of-sample trades**. The
metrics harness itself flags every fold as `significance: none`.

**The out-of-sample result flips sign with a single toggle** (fresh walk-forward,
runner profile, identical data/costs):

| Walk-forward setup | OOS trades | OOS PF | OOS return | Verdict |
|---|---|---|---|---|
| FVG in the search grid | 11 | 1.50 | **+1.3%** | noise (`none`) |
| FVG off (runner profile) | 19 | 0.74 | **−1.4%** | noise (`none`) |
| per-fold OOS PF (grid run) | 2–3 each | `0.0 / 0.51 / 0.0 / 7.10` | — | one lucky trade swings it |

An edge that inverts from +1.3% to −1.4% when you flip one flag, on 11–19 trades,
is **not an edge** — it's sampling variance. The earlier "+5.9% OOS, PF 1.70, 84%
prob-profit, *validated*" framing was over-claimed on this same razor-thin data and
has been retracted.

**Benchmark reality:** buy-and-hold gold returned **+57.7%** over the span. The
system barely participated (5–19 trades while gold ran from ~$2,970 to ~$5,419). It
neither beat nor meaningfully tracked the move.

**What we can still say honestly:** the engine is causal, costs are applied, risk
is contained (~2–4% DD), and the validation harness *correctly refuses to certify*
the strategy — which is exactly what it's for. The blocker is data, not plumbing.

## 5. What this does and does NOT establish

* ✅ The engine runs end-to-end on real gold, sizes risk correctly, contains
  drawdown (~2–4%), and is safe/observable (news blackout, macro filter, journal,
  restart state).
* ✅ The validation harness works and is honest — it refuses to certify an edge on
  insufficient data instead of printing a flattering number.
* ❌ **No edge has been established.** OOS is 11–19 trades (`significance: none`) and
  the sign of the result is config-dependent. The bundled dataset (~105 partial
  days) cannot support a verdict. A clean, continuous, multi-year M15/M5 export is
  the prerequisite for *any* conclusion — positive or negative.

## 6. The path to a real, live-ready edge

In priority order — note that **#1 gates everything**; further code is secondary.

1. **Data — this is the whole ballgame right now.** Get **2–3 years of *continuous*
   M15/M5 gold** (not stitched fragments) via `python -m xauusd_agent download` (now
   paged, so multi-year pulls aren't truncated) or a data vendor. Then run
   `python -m xauusd_agent validate --csv your_gold.csv` for a one-shot verdict.
   Until the OOS sample is ~100+ trades, no result here means anything.
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
