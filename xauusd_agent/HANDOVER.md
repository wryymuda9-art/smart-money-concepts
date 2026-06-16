# XAUUSD SMC Agent — Project Handover

A complete, honest summary of what was built, how to run it, what the results
actually say, and what it would take to make it a profitable, live bot.

> **One-line status:** a fully built, tested, deployable XAUUSD scalping/day-trading
> bot with a **small, validated, low-drawdown positive edge** on 13 months of
> multi-regime M15 data (out-of-sample walk-forward +5.9%, PF 1.70, ~2% max DD) —
> credible but not yet statistically conclusive, and it trails buy-and-hold in a
> gold bull market. Educational project; not investment advice; do not trade real
> money on it as-is.

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

All on $10,000, 0.5% risk/trade, costs included. The headline test is the
**13-month multi-regime M15 dataset** (`XAUUSD_M15_multi.csv`, ~7,504 candles,
2025-03 .. 2026-04, gold $2,970–$5,419, ~20 stitched segments across regimes).

**Day-trade M15 (multi-regime), in-sample:**

| Config | Return | Max DD | Ret/DD | PF | Win | Significance |
|---|---|---|---|---|---|---|
| baseline (no management) | +3.9% | −5.3% | 0.74 | 1.11 | 39% | moderate |
| + management (partial+trail) | +5.2% | −3.4% | 1.53 | 1.17 | 61% | moderate |
| **+ "let winners run"** ⭐ | **+17.4%** | −7.9% | **2.22** | **1.50** | 36% | moderate |

**Out-of-sample (walk-forward, the honest number):**

| Profile | OOS return | OOS PF | OOS max DD | OOS trades |
|---|---|---|---|---|
| + management | +2.6% | 1.30 | −2.1% | 63 |
| **+ "let winners run"** | **+5.9%** | **1.70** | −2.1% | 40 |

**Key honest findings:**
1. **More data revealed a real edge.** On 2 months the strategy looked like noise
   (`weak`/`none`, underperformed); on 13 multi-regime months it reaches `moderate`
   significance and is consistently positive. Monte-Carlo (5,000 sims): **84%
   probability of profit**.
2. **"Let winners run" is a *validated* improvement.** Dropping the early partial
   and trailing wide (3R) **doubled the out-of-sample return (+2.6% → +5.9%, PF
   1.30 → 1.70) at the same ~2% drawdown.** It survived walk-forward — not
   curve-fitting. Now the default (`with_management=True`, `management_style="runner"`).
3. **Leverage is not improvement.** Raising risk 0.5%→2% scaled return to +21% but
   drawdown to −21% (Ret/DD fell to 1.00). Adding positions hurt (Ret/DD 0.34).
   Keep risk at 0.5% until the edge is proven on clean data.
4. **It still trails buy-and-hold** (+57.7% over the same gold bull run) in raw
   return — but at ~1/8th the drawdown, far less exposure, and the ability to
   profit in ranges/bears. A risk-managed all-weather overlay, not a gold-bull proxy.
5. **Still not conclusive.** Best out-of-sample sample is 40–63 trades (`weak`).
   Encouraging and validated, but a clean multi-year export is needed for `ok`.

## 5. What this does and does NOT establish

* ✅ The engine runs end-to-end on real gold, sizes risk correctly, contains
  drawdown (~2–3%), and is safe/observable (news blackout, journal, restart state).
* ✅ On 13 months of multi-regime data it shows a **small, positive, out-of-sample
  edge** (+5.9% OOS, PF 1.70) — credible, low-drawdown, and validated by walk-forward.
* ❌ It is **not yet conclusive** (40–63 OOS trades = `weak`), and it **underperforms
  buy-and-hold** in a gold bull market on raw return. A clean continuous multi-year
  export is needed to confirm the edge is durable rather than a lucky patchwork.

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
