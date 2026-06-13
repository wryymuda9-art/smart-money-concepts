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
| `strategy.py` | `SMCStrategy.evaluate(window) → Signal`. The ICT confluence logic. |
| `risk.py` | `RiskManager`: fixed-fractional position sizing + daily-loss / max-trades / max-positions gates. |
| `broker.py` | `SimBroker` (deterministic fills for test/paper) and `Mt5Broker` (live, lazy-imported). |
| `backtest.py` | `Backtester` event loop + `BacktestResult` metrics (win rate, PF, expectancy, max DD…). |
| `agent.py` | `TradingAgent` top-level orchestrator; `backtest()` and per-candle `step()`. |
| `cli.py` | `python -m xauusd_agent.cli backtest --csv ...` |

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

### Paper / live (MetaTrader 5)

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

## Roadmap / what to add next

- Live XAUUSD data ingestion (MT5 `copy_rates_*`) and a scheduling loop.
- Walk-forward optimisation and parameter sweeps over the confluence toggles.
- Trailing stops / partial take-profits / break-even moves.
- Per-session and per-day-of-week performance attribution.
- News-blackout filter (gold is very sensitive to USD/CPI/FOMC).
```
