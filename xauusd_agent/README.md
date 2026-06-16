# XAUUSD Trading Agent

An algorithmic trading agent for **XAUUSD (gold)** day-trading and scalping, built
on top of the [`smartmoneyconcepts`](../smartmoneyconcepts) (ICT / Smart Money
Concepts) indicator library that ships in this repo.

`smartmoneyconcepts` only *describes* a chart (order blocks, FVGs, liquidity,
BOS/CHoCH, sessions…). This package adds everything needed to turn those
descriptions into **decisions and orders**: a strategy engine, risk management,
position sizing, a simulated broker, a backtester, and a MetaTrader 5 live
adapter.

> ⚠️ **Educational software, not financial advice.** Trading leveraged gold is
> high-risk. Nothing here will place a real order unless you explicitly construct
> an `Mt5Broker` and run in `Mode.LIVE`. Backtest, then forward-test on a demo
> account, before risking money. You are responsible for your own trades.

## Architecture

```
   DataFeed  ──►  Strategy (smc)  ──►  RiskManager  ──►  Broker
   data.py        strategy.py          risk.py           broker.py
     │                │                    │                │
  OHLCV df         Signal             SizingDecision   Order / Position
                                      + gatekeeping     (Sim or MT5)

   Backtester (backtest.py)  orchestrates the above over history, causally.
   TradingAgent (agent.py)   orchestrates the above for paper / live, per candle.
```

Each layer is independent and unit-tested, so you can swap the strategy, retune
risk, or change broker without touching the others.

| File | Responsibility |
|------|----------------|
| `config.py` | All tunables as dataclasses (`AgentConfig`, `RiskConfig`, `StrategyConfig`, `InstrumentSpec`, `Mode`). |
| `data.py` | Load & normalise OHLCV (MT5/generic CSV) → datetime-indexed, lowercase columns; causal window iterator. |
| `feed.py` | `CsvDataFeed` (replay) and `Mt5DataFeed` (live bars via `copy_rates_*`, + history download). |
| `strategy.py` | `SMCStrategy.evaluate(window) → Signal`. The ICT confluence logic. |
| `risk.py` | `RiskManager`: fixed-fractional position sizing + daily-loss / max-trades / max-positions gates. |
| `broker.py` | `SimBroker` (deterministic fills for test/paper) and `Mt5Broker` (live, lazy-imported). |
| `backtest.py` | `Backtester` event loop + `BacktestResult` metrics (win rate, PF, expectancy, max DD…). |
| `viz.py` | `LiveDashboard` — dark SMC candlestick chart (order blocks/FVG/liquidity/structure) + the agent's own trade overlays, written to a self-refreshing HTML/PNG. |
| `agent.py` | `TradingAgent` top-level orchestrator; `backtest()` and per-candle `step()`. |
| `live.py` | `run_live(config, feed, dashboard, broker)` real-time loop; `run_live_replay()` offline. |
| `cli.py` | `backtest` / `dashboard` / `live` / `download` subcommands. |

## Where the data comes from

Everything consumes one shape: a datetime-indexed `open/high/low/close/volume`
DataFrame (`data.normalise_ohlc`). A **feed** supplies it:

| Mode | Feed | Source |
|------|------|--------|
| Backtest / Paper | `CsvDataFeed` | a CSV on disk (`load_csv`) |
| **Live** | `Mt5DataFeed` | the **MT5 terminal** via `MetaTrader5.copy_rates_*` |

The agent runs as a normal Python process on your machine/VPS; **MT5 is the data
*and* execution gateway it connects to** (it does not run inside MT5). `Mt5DataFeed`
and `Mt5Broker` are lazy-imported, so the package stays runnable on Linux/macOS and
only activates on a Windows host with an MT5 terminal.

## The strategy (ICT day-trade / scalp)

`SMCStrategy` is *causal* — it only ever sees candles up to the just-closed one, so
backtests don't cheat with look-ahead. For each closed candle it layers smc:

1. **Bias** — direction of the most recently *confirmed* `BOS` / `CHoCH`
   (continuation vs reversal of market structure).
2. **Timing** *(optional)* — only act inside the **London** and **New York
   kill-zones** (`smc.sessions`), where gold moves.
3. **Zone** — an **unmitigated Order Block** (`smc.ob`) in the bias direction that
   price is currently retracing into.
4. **Confluence** *(optional)* — a **Fair Value Gap** (`smc.fvg`) overlapping that
   order block.
5. **Risk map** — stop just beyond the order block (buffered by a fraction of its
   height); target the nearest **opposing liquidity pool** (`smc.liquidity`), or a
   fixed reward:risk multiple if none is found.

Every confluence is a toggle/weight in `StrategyConfig`, so you can loosen or
tighten the setup without editing code.

### Optional ICT upgrades (opt-in)

Two stronger confluences are available but **off by default** (they're strict and
need dense intraday data to earn their keep — validate with the walk-forward
before enabling live):

- **Liquidity-sweep trigger** (`require_liquidity_sweep`) — only enter after a
  recent *opposing* liquidity sweep / stop-hunt (sell-side swept below → long;
  buy-side swept above → short), within `liquidity_sweep_lookback` candles. Models
  the ICT "sweep → reversal" sequence.
- **Multi-timeframe bias** (`require_htf_alignment`) — require the entry direction
  to agree with a higher-timeframe bias built by aggregating every
  `htf_multiplier` candles (e.g. M15 base → H1 bias). Stops you trading LTF setups
  against the HTF trend.

### Macro / news bias filter (opt-in)

Gold is a macro instrument: the strongest, most reliable driver is the **US
dollar — USD up ⇒ gold down**. `macro.py` turns that into a directional bias
(`+1` bullish / `-1` bearish / `0` neutral) the agent uses as a **filter**: it
takes only SMC setups that *agree* with gold's macro direction and steps aside on
the ones fighting it. It does **not** try to predict or trade the news headline —
that layer is the noisiest and hardest to validate. This is an odds tilt, not a
prophecy.

Two complementary layers:

- **Event blackout** (`news.py`, `NewsConfig`) — flatten/stand down around
  scheduled high-impact events (CPI, FOMC, NFP). *Avoid* the chaos.
- **Macro bias** (`macro.py`, `MacroConfig`) — *bias* entries with the prevailing
  USD direction. Off by default (`macro.enabled = False`).

Plug data in two ways:

```python
from xauusd_agent import MacroBias, Backtester

# 1. derive gold's bias from the US Dollar Index trend (DXY up -> gold bearish)
macro = MacroBias.from_dxy(dxy_ohlc, lookback=20)   # dxy_ohlc: datetime-indexed 'close'

# 2. or supply any bias series you compute (real yields, your own view, a
#    calendar-surprise model): a datetime-indexed series of -1 / 0 / +1
macro = MacroBias.from_series(my_bias_df, col="bias")

cfg.macro.enabled = True
result = Backtester(cfg, macro_bias=macro).run(ohlc)   # or TradingAgent(cfg, macro_bias=macro)
```

`bias_at(ts)` looks up the most recent bias at/before a timestamp (no look-ahead);
`allows(ts, direction)` answers whether a long (`+1`) or short (`-1`) agrees. For
backtests, feed a DXY CSV aligned to your gold period; for live, refresh the bias
from your DXY feed or an economic-calendar API on each loop. **Honest caveat:**
these are tendencies, not certainties — gold can rally on inflation fear with a
firm dollar, and moves are often pre-priced. Validate with the walk-forward before
trusting it live.

## Risk management & position sizing

Fixed-fractional risk — the loss if the stop is hit is ~`risk_per_trade` of equity
**regardless of stop width** (wider stops automatically get smaller size):

```
risk_money = equity * risk_per_trade                     # e.g. 0.5% of equity
stop_dist  = |entry - stop|                               # USD per ounce
money/lot  = stop_dist * money_per_price_per_lot          # 100 USD/price/lot for gold
lots       = floor(risk_money / money/lot  / lot_step) * lot_step
```

Gatekeeping in `RiskManager.can_trade(...)` enforces:
- **Daily loss limit** (`max_daily_loss`) — halts trading for the rest of the day.
- **Max trades per day** (`max_daily_trades`).
- **Max concurrent positions** (`max_open_positions`).
- **Min stop distance** and **max spread** filters (gold spreads are wide/variable).

## Quick start on real XAUUSD (bundled)

Real gold sample data ships under `tests/test_data/XAUUSD/` (`XAUUSD_4H.csv` ≈ 2,081
candles 2020–2022 with volume; `XAUUSD_5M.csv` a short scalping-timeframe sample).
One command backtests the gold-tuned preset on it:

```bash
SMC_CREDIT=0 python -m xauusd_agent.examples.run_xauusd --timeframe 4H
# add a chart:
SMC_CREDIT=0 python -m xauusd_agent.examples.run_xauusd --timeframe 4H --png xauusd.png
```

```python
from xauusd_agent import xauusd_config, sample_data_path, Backtester
from xauusd_agent.data import load_csv

cfg  = xauusd_config(timeframe="5M")          # gold instrument + scalping tuning
ohlc = load_csv(sample_data_path("4H"))       # or your own MT5 export
print(Backtester(cfg).run(ohlc))
```

> The bundled data is for demonstration/tests only (short, single period). For any
> real evaluation, supply your own history — `download` from MT5, or a broker CSV.

## Run from a config file

Describe a whole run declaratively (`xauusd_agent/config.example.yaml`) instead of
juggling flags. Any omitted field keeps its default; explicit CLI flags override
the file.

```bash
python -m xauusd_agent backtest --config xauusd_agent/config.example.yaml --csv gold.csv
```

```python
from xauusd_agent import load_config, save_config, Backtester
cfg = load_config("config.example.yaml")   # -> AgentConfig
save_config(cfg, "my_run.yaml")
```

`python -m xauusd_agent <command>` works for every subcommand (`backtest`,
`dashboard`, `live`, `download`, `optimize`, `walkforward`). Agent tests run in CI
via `.github/workflows/agent-tests.yaml`.

## Usage

### Backtest (CLI)

```bash
# from the repo root
SMC_CREDIT=0 python -m xauusd_agent.cli backtest \
    --csv path/to/XAUUSD_M5.csv \
    --risk-per-trade 0.005 --swing-length 5 --window 400
```

### Backtest (Python)

```python
from xauusd_agent import AgentConfig, Mode
from xauusd_agent.data import load_csv
from xauusd_agent.backtest import Backtester

cfg = AgentConfig(mode=Mode.BACKTEST, starting_equity=10_000)
cfg.risk.risk_per_trade = 0.005          # 0.5% per trade
cfg.strategy.swing_length = 5            # scalping-ish structure
cfg.strategy.sessions = ["London open kill zone", "New York kill zone"]

ohlc = load_csv("XAUUSD_M5.csv")         # MT5/generic OHLCV export
result = Backtester(cfg).run(ohlc, progress_every=2000)
print(result)            # one-line summary
print(result.summary())  # dict of metrics
```

### Live dashboard (visual)

Replay candles into the dark SMC chart (HTML auto-refreshes; PNG optional):

```bash
SMC_CREDIT=0 python -m xauusd_agent.cli dashboard \
    --csv XAUUSD_M5.csv --html dash.html --png dash.png --plot-window 130
# open dash.html in a browser to watch it update
```

The chart shows order blocks, FVGs, liquidity, swing structure and BOS/CHoCH,
plus the agent's own activity: ▲/▼ entry markers, dashed take-profit / stop-loss
lines, exit markers coloured by win/loss, and a header with equity / open PnL /
win-rate. Works in backtest-replay, paper and live modes.

### Download XAUUSD history from MT5 (Windows + terminal)

```bash
python -m xauusd_agent.cli download --symbol XAUUSD --timeframe M5 \
    --start 2024-01-01 --end 2024-06-01 --out XAUUSD_M5.csv
```

### Run on live MT5 data

```bash
# PAPER: read live MT5 bars, simulate fills, no orders sent (safe default)
python -m xauusd_agent.cli live --symbol XAUUSD --timeframe M5 --html dash.html

# LIVE: actually place orders via MT5 (explicit opt-in)
python -m xauusd_agent.cli live --symbol XAUUSD --timeframe M5 --execute
```

### Paper / live (MetaTrader 5, Python API)

MT5's Python bindings are Windows-only; `Mt5Broker` is imported lazily so the rest
of the package works anywhere. Live is **opt-in** and never auto-connects.

```python
from xauusd_agent import AgentConfig, Mode, TradingAgent
from xauusd_agent.broker import Mt5Broker

cfg = AgentConfig(mode=Mode.LIVE)
broker = Mt5Broker(cfg.instrument, login=..., password=..., server=...)
broker.connect()                         # explicit; nothing happens before this
agent = TradingAgent(cfg, broker=broker)

# once per just-closed candle, feed the latest trailing window:
result = agent.step(latest_window, spread=current_spread)
if result.acted:
    print("placed", result.lots, "lots:", result.signal.reason)
```

For **paper trading**, use the default `SimBroker` (omit `broker=`) with
`Mode.PAPER` and feed it live candles the same way.

## Validation harness (trust the numbers)

A single backtest is a noisy number. `research.py` makes results believable:

- **`compute_metrics(result)`** — risk-aware stats: `avg_R` (mean realised
  reward:risk), `sharpe`, `sortino`, `cagr`, `payoff`, `max_drawdown`,
  `max_consec_losses`, plus a **`significance`** flag derived from trade count
  (`none` <30, `weak` <100, `moderate` <300, `ok`). Under ~100 trades, treat any
  edge as unproven.
- **`sweep(base, ohlc, grid)`** — grid-search parameters; one row of metrics per
  combination, sorted by your objective.
- **`walk_forward(base, ohlc, grid, n_splits)`** — optimise on in-sample, measure
  on the *next unseen* out-of-sample slice, repeat, and report the **stitched OOS**
  performance. This is the honest, curve-fit-resistant number.

```bash
# grid-search on the bundled real gold (or --csv your own)
SMC_CREDIT=0 python -m xauusd_agent.cli optimize    --timeframe 4H --objective avg_R --top 10
# out-of-sample walk-forward validation
SMC_CREDIT=0 python -m xauusd_agent.cli walkforward --timeframe 4H --splits 3 --objective profit_factor
```

```python
from xauusd_agent import xauusd_config, sweep, walk_forward, sample_data_path
from xauusd_agent.data import load_csv

cfg, ohlc = xauusd_config(timeframe="4H"), load_csv(sample_data_path("4H"))
grid = {"strategy.swing_length": [4, 6, 8], "strategy.require_fvg": [True, False]}
table = sweep(cfg, ohlc, grid, sort_by="avg_R")          # ranked DataFrame
wf    = walk_forward(cfg, ohlc, grid, n_splits=3)         # OOS result
print(wf)
```

> **Read the `significance` flag first.** The bundled samples are short, so demo
> results will say `none`/`weak`. Meaningful conclusions need months of intraday
> data → hundreds of trades.

## Tests

```bash
SMC_CREDIT=0 python -m unittest xauusd_agent.tests.test_agent -v
```

Covers position sizing vs risk budget, lot-step rounding, daily-loss / trade /
position gates, simulated stop/target fills (incl. worst-case stop-first
tie-break), full-pipeline accounting consistency, and a no-look-ahead check. The
pipeline smoke test runs over the bundled EURUSD sample (the repo ships no XAUUSD
data) purely to prove the layers wire together — the numbers are not a strategy
endorsement.

## Optional dependencies

The core (backtest/paper) needs only `pandas`, `numpy`, `numba` (already required
by `smartmoneyconcepts`). Extra features:

- **Dashboard**: `pip install plotly kaleido` (PNG export also needs Chrome:
  `plotly_get_chrome`). HTML output needs only plotly.
- **Live / data download**: `pip install MetaTrader5` on a Windows host.

## Roadmap / what to add next

- ✅ Live XAUUSD data ingestion (MT5 `copy_rates_*`) + real-time loop (`feed.py`, `live.py`).
- ✅ Visual live dashboard (`viz.py`).
- ✅ Liquidity-sweep entry trigger and multi-timeframe bias (`require_liquidity_sweep`, `require_htf_alignment`).
- ✅ Walk-forward optimisation and parameter sweeps over the confluence toggles (`research.py`).
- ✅ News-blackout filter + macro/USD directional bias (`news.py`, `macro.py`).
- Trailing stops / partial take-profits / break-even moves.
- Per-session and per-day-of-week performance attribution.
- Live economic-calendar ingestion to drive the event blackout + macro bias automatically.
```
