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

### 4. Gross edge — are costs masking a real edge? (best config, costs zeroed)

| Config | Trades | Win% | PF | Return | Sharpe |
|---|---|---|---|---|---|
| Best (strict + trailing), real costs | 141 | 59% | 0.97 | −0.9% | −0.06 |
| Best, **zero costs** | 141 | 61% | **1.08** | **+2.1%** | **+0.17** |

**Verdict:** there *is* a real but thin gross edge — trading costs (~$0.40/trade
spread+slippage) eat it entirely. This makes the fix mechanical: bigger winners
per trade so the edge clears the fixed cost.

### 5. Walk-forward — does a bigger reward:risk target rescue it? (costs ON)

Optimised fixed reward:risk on the first half, validated on the untouched second half.

| Variant | In-sample PF (2012–17) | Out-of-sample PF (2017–22) |
|---|---|---|
| Baseline (nearest-liquidity) | 1.20 | 0.81 |
| Fixed RR 3:1 | 1.45 | 0.90 |
| Fixed RR 4:1 | 1.46 | 0.92 |
| Fixed RR 5:1 | 1.48 | 0.92 |

**Verdict:** a fixed RR target is a genuine, *consistent* improvement (better PF in
BOTH halves — it generalises, not curve-fit). But it is not enough: the best
out-of-sample PF is 0.92, still below 1.0. The strategy was profitable in 2012–2017
(PF up to 1.48) and decayed to a loss in 2017–2022 — the edge faded over time,
most likely arbitraged away as these SMC patterns became widely traded.

### 6. Does a higher timeframe help? (4H / daily walk-forward)

Hypothesis: hourly trades too often, so costs dominate; higher timeframes trade
less. Same in-sample/out-of-sample split, fixed-RR lever.

| Timeframe | In-sample PF | Out-of-sample PF | Trades / half |
|---|---|---|---|
| Hourly | up to 1.48 | 0.92 | ~140 |
| 4H | up to 1.25 | 0.50–0.90 | ~20 |
| Daily | 0.35 | — | ~6 total |

**Verdict:** higher timeframes do not rescue it. They cut cost drag but collapse the
trade count to meaningless levels (daily: 6 trades in 5 years), and the same
out-of-sample decay persists. Hourly is the only timeframe with enough trades to
evaluate — and it loses out of sample. (Note: daily requires `require_session=False`,
since kill-zones are meaningless on daily bars and otherwise block every trade.)

## Conclusion

There was a **real but thin edge** on hourly gold that has **decayed**: profitable
in 2012–2017, losing in 2017–2022. We diagnosed the weakness correctly (winners too
small relative to fixed costs) and found the right lever (larger reward:risk
targets), which improves results *consistently in and out of sample*. It is still
not sufficient — the best out-of-sample profit factor is 0.92, below the 1.0
break-even line. **The strategy cannot be tuned back into profitability on recent
gold.** Net of costs, on the most recent (most decision-relevant) data, it loses.

This is a nuanced, well-earned result: not "the idea is worthless", but "the edge
existed, weakened over time, and the recoverable part no longer clears trading
costs." Walk-forward validation is what separated the real improvement from the
period-specific illusion — and it is exactly why no version of this should be
traded live as-is.

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
