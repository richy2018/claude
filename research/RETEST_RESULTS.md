# GLI signal — bias audit and re-test

Run date: 2026-08-14. Reproduce with `python3 research/snapshot_retest.py`.

Data: snapshot exported from the live Render backend (`research/bis-credit.json`,
`spy.json`), plus `backend/data/HY data.csv` — a Bloomberg HY OAS export
covering 1994-01 to 2026-08, which is what finally made a genuine 5-factor test
possible.

---

## Headline

With a live credit component, correct publication lags and a one-month
execution lag, the model **does** add timing value: **+0.100 Sharpe** over an
exposure-matched static allocation, and it roughly halves maximum drawdown
(−22.8% against −50.8% for SPY, −35.4% for the static).

This reverses the earlier draft of this document, which concluded −0.012. Three
things changed, two of them my errors. See "Corrections" below.

The mechanism is not what the model claims. Of the five components, **only the
credit spread shows predictive structure that beats a permutation null**
(p=0.01). The four liquidity components are individually indistinguishable from
noise. They still earn their place — dropping them takes maximum drawdown from
−22.8% to −40.7% — but as variance reduction, not as prediction.

---

## 1. The credit component, finally alive

FRED serves the licensed ICE BofA series as a ~3-year rolling window regardless
of `observation_start` — verified against the live API: a request from
2000-01-01 returned 795 observations starting 2023-08-14. `spread_signal`,
20% of the composite, was therefore absent for 96% of the backtest and, because
missing components were zero-filled, read as a confident *neutral* rather than
as missing.

`backend/data/HY data.csv` (Bloomberg, 1994-01 → 2026-08, 6606 observations,
monthly to 2000-08 then daily) fixes this. It peaks at 19.71 in Nov-Dec 2008 and
tracks the GFC correctly (7.1% mid-2008 → 18.3% Nov-2008 → 9.5% Jun-2009).

| component | live months before | after |
|---|---:|---:|
| spread_signal | 14 of 323 | **323 of 323** |

Composite weight pinned at a fabricated zero, by era:

| era | before | after |
|---|---:|---:|
| 2006-08 .. 2012-03 | 40% | 20% |
| 2012-04 .. 2025-06 | 20% | **0%** |

(The residual 20% pre-2012 is `dollar_stress_signal`; the basis-swap gist does
not start until 2012-04. That is a genuine source limit.)

## 2. Results — 240 months, 2006-10 .. 2026-08

Sharpe is excess over 0%: the snapshot has no pre-2019 risk-free series. All
arms are treated identically.

| variant | Sharpe | alpha% | maxDD% | crashes |
|---|---:|---:|---:|---:|
| 5F as configured / no pub lag | 0.770 | 1.92 | −28.7 | 2/4 |
| **5F as configured / lagged** | **0.875** | **3.11** | **−22.8** | **3/4** |
| live-only renormalised / lagged | 0.821 | 2.48 | −28.7 | 3/4 |
| SPY buy & hold | 0.781 | — | −50.8 | — |

Publication lags now **help** (+0.104 Sharpe), which is exactly what
`bias_lab.py` predicts when the true lead exceeds the publication lag.

Crash detection improves to 3/4 — GFC, COVID and the 2022 rate shock. Q4-2018
is missed by every variant.

## 3. Against an exposure-matched static allocation

The honest benchmark is not SPY, it is a fixed weight at the same average
exposure with zero timing.

| | Sharpe | return | maxDD |
|---|---:|---:|---:|
| GLI timed (lagged) | 0.875 | 9.25% | −22.8% |
| static 63% | 0.774 | 7.48% | −35.4% |
| **timing value** | **+0.100** | **+1.76%** | **+12.6pp** |

Note the model gives up return against outright SPY (9.25% vs 11.95%) in
exchange for less than half the drawdown.

## 4. Where the edge actually comes from

Permutation null, 500 shuffles, bar = 95th percentile of max\|r\| across 19 lags.

| factor | peak lag | peak r | noise bar | p | verdict |
|---|---:|---:|---:|---:|---|
| **spread_signal** | 0 | **−0.230** | 0.185 | **0.01** | real, and tradeable |
| m2_signal | 5 | −0.102 | 0.173 | 0.55 | noise |
| dollar_stress_signal | 6 | −0.098 | 0.241 | 0.98 | noise |
| rate_signal | 10 | +0.097 | 0.189 | 0.74 | noise |
| quantity_signal | 6 | −0.091 | 0.176 | 0.66 | noise |

Component ablation (all lagged, all with execution lag):

| model | Sharpe | return | maxDD | vs static |
|---|---:|---:|---:|---:|
| 5F (all) | 0.875 | 9.25% | −22.8% | +0.100 |
| 4F (minus credit) | 0.821 | 8.84% | −28.8% | +0.046 |
| 1F (credit only) | 0.829 | 9.43% | −40.7% | +0.054 |
| 2F (credit + quantity) | 0.797 | 8.35% | −18.6% | +0.023 |

**Read this carefully.** The Sharpe differences between 5F, 4F and 1F are ~0.05
on 240 months — well inside the standard error of a Sharpe ratio at that sample
size, so they are *not* statistically distinguishable. What survives is:

- credit has real predictive structure; the other four do not;
- credit alone has a bad drawdown profile (−40.7%, barely better than SPY);
- combining all five gives the best drawdown (−22.8%) at similar Sharpe.

So the liquidity components function as variance reduction around a credit
signal, not as independent forecasters. The model works — but not through the
mechanism its name claims.

---

## Corrections to the earlier draft

Three changes moved the headline from −0.012 to +0.100. Two were my errors.

1. **Live credit component** (the Bloomberg export). Legitimate improvement.

2. **My publication-lag spec was wrong.** `PUBLICATION_LAG_MONTHS` was derived
   as `ceil(days/30)`, which charges a full month to any series with a non-zero
   day-lag. A daily market series sampled at month end is available *at* month
   end — its lag in monthly observations is 0, not 1. That over-penalised
   `spread_signal`, `rate_signal` and `dollar_stress_signal`. Now stated
   explicitly per series in `research/causal.py`.

3. **My backtest had a one-month look-ahead.** Both the signal and the return
   carry month-START labels produced by `resample("MS").last()`, so the row
   labelled `2020-03-01` holds the value observed on `2020-03-31`. Multiplying
   signal[t] by return[t] trades on the month that has already happened.
   `backtest()` now shifts the weight by one month. **This was worth 0.25
   Sharpe of pure look-ahead** — the inflated figure was 1.125.

## ⚠️ The same look-ahead exists in production

`backtest_engine.simulate_equity_curve` and
`gli_realtime_validation._backtest` both compute `port_ret = r * w` with no
execution shift, on the same month-start-labelled data. Every Sharpe, alpha and
equity curve those functions produce is inflated by roughly the same margin
found here (~0.25 Sharpe). **Not yet fixed** — it changes every published
number and warrants a deliberate decision.

## What this re-test still cannot settle

- **The spline (interpolation) effect.** `ratio_series` is downstream of it.
  `bias_lab.py` measures it separately: negligible at 20% weight.
- **Revisions.** Values are current-vintage. This corrects look-ahead in
  *timing*, not in *values*. A true point-in-time rebuild needs ALFRED
  (`pit_fred.py`) and, for BIS and the gist, forward archiving.
- **Absolute levels.** No pre-2019 risk-free series in the snapshot. Read
  deltas. Run `research/export_snapshot.py` on a networked host to fix this.

## Next steps

1. Decide on the production execution-lag fix — it is a real bug and it
   inflates every reported number.
2. Run `research/export_snapshot.py` for a proper risk-free series, then re-run
   for trustworthy absolute Sharpe and alpha.
3. Consider whether a credit-led model with liquidity components as
   stabilisers is the honest framing, and re-weight accordingly. Equal 20%
   weighting gives the only factor with detectable signal the same voice as
   four that have none.
