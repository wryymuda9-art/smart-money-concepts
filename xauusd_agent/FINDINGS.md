# Findings — does this SMC strategy have an edge on gold?

This document records a full evaluation of the XAUUSD strategy against **10 years
of real hourly gold data** (2012–2022, 57,600 candles). It exists so the analysis
survives — the work was done in an ephemeral environment.

## The question

Initial concern: *"the bot is too strict — it barely trades, even on good setups.
Are we throwing away good trades?"*

## Data

- **Source:** public GitHub dataset `ejtraderLabs/historical-data`, file
  `XAUUSD/XAUUSDh1.csv` (hourly, 2012-05-17 → 2022-03-04).
- Prices were stored in points (×100); rescaled to USD/oz (range ≈ $1,050–$2,070).
- Clean CSV produced with columns `date,open,high,low,close,volume`.
- **Buy & hold over the window: +26.84%** (the bar any strategy must beat).

## Experiments (all on the full 10-year set)

### 1. Is it too strict? (`--near-miss` + strict vs. loose)

The near-miss tool found **379 valid core setups** (structure + unmitigated order
block + price tapping it); only **3%** survived the optional filters. So the filters
*are* rejecting most setups. But removing them is decisively worse:

| Config | Trades | Win% | PF | Return |
|---|---|---|---|---|
| Strict (FVG required, default) | 138 | 49% | **0.93** | **−2.0%** |
| Loose (FVG off) | 757 | 40% | 0.79 | −37.7% |
| Loose + all sessions | 1,242 | 44% | 0.84 | −40.7% |

**Verdict:** the strictness was *protective*. The rejected setups were mostly bad.

### 2. Trade management (on the strict config)

| Variant | Trades | Win% | PF | Return | MaxDD |
|---|---|---|---|---|---|
| Baseline (no mgmt) | 138 | 49% | 0.93 | −2.0% | −6.3% |
| + Break-even @1R | 140 | 44% | 0.88 | −3.1% | −5.6% |
| **+ Trailing 1R @1R** | 141 | **59%** | **0.97** | **−0.9%** | **−4.7%** |
| + Break-even & trailing | 141 | 59% | 0.97 | −0.9% | −4.7% |

**Verdict:** trailing helps (best result), break-even hurts. Still under PF 1.0.

### 3. Entry quality (on top of the trailing stop)

| Variant | Trades | Win% | PF | Return |
|---|---|---|---|---|
| Trailing only (best) | 141 | 59% | **0.97** | **−0.9%** |
| + HTF alignment | 79 | 54% | 0.80 | −3.3% |
| + Liquidity sweep | 7 | 29% | 0.21 | −1.9% |
| + Regime (with-trend) | 139 | 58% | 0.91 | −2.3% |
| + All three | 4 | 25% | 0.00 | −1.4% |

**Verdict:** every entry filter made it worse.

## Conclusion

**This SMC strategy does not have a profitable edge on hourly gold.** Across every
lever (entry filters, sessions, trade management, entry quality), the best
configuration achieved was **−0.9% over 10 years** — and that is an *in-sample*
figure, the most favourable possible measurement. Over the same decade, simply
holding gold returned **+27%**. No walk-forward test is needed to "confirm" a
result that is already negative in-sample; out-of-sample would only be worse.

The original concern (too strict) was reasonable and was tested rigorously: the
opposite was true — the filters were the only thing keeping the system near
break-even. Knowing a strategy loses *before* risking capital is the point of
backtesting; this is a useful, money-saving conclusion, not a failure.

## Reproducing

```bash
# 1. fetch + rescale the data (any host-allowlisted environment)
#    raw: https://raw.githubusercontent.com/ejtraderLabs/historical-data/main/XAUUSD/XAUUSDh1.csv
#    divide OHLC by 100, rename tick_volume -> volume, save as xauusd_h1_real.csv

# 2. strict vs loose
python -m xauusd_agent backtest --csv xauusd_h1_real.csv            # strict
python -m xauusd_agent backtest --csv xauusd_h1_real.csv --no-require-fvg

# 3. management + entry sweeps
python xauusd_agent/experiments/mgmt_experiment.py
python xauusd_agent/experiments/entry_sweep.py
```

## Possible next directions (not pursued here)

- Try the same logic on a **different instrument or higher timeframe** — a fresh
  question, not a re-tune of these same knobs (re-tuning is how you curve-fit).
- If pursuing gold, a **genuinely different entry model** would be required; the
  parameters exposed by this strategy have been exhausted.
