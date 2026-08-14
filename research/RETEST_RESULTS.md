# GLI signal — bias audit and re-test

Run date: 2026-08-14. Data: snapshot exported from the live Render backend
(`research/bis-credit.json`, `spy.json`, `fred.json`).
Reproduce with `python3 research/snapshot_retest.py`.

## Headline

Once components are lagged by their real publication delays, the signal's
timing value against an exposure-matched static allocation is **−0.012 Sharpe**.
The as-built pipeline shows **+0.086**. The entire measured timing edge is
accounted for by reading data before its release date.

Independently, no factor shows lead-lag structure against forward SPY returns
that beats a permutation null (all p ≥ 0.39). There is no detected lead for a
correctly-lagged signal to capture, which is consistent with the above.

## 1. The composite was never really 5F

| component | live months | first live | dead |
|---|---:|---|---:|
| quantity_signal | 300 | 2001-09 | 7% |
| m2_signal | 295 | 2001-12 | 9% |
| rate_signal | 303 | 2001-06 | 6% |
| dollar_stress_signal | 172 | 2012-04 | 47% |
| **spread_signal** | **14** | **2025-07** | **96%** |

`compute_debt_liquidity_ratio` substitutes `0.0` for absent components. Because
components are scaled to [-1, 1], zero is not "missing" — it reads as a
perfectly neutral signal. Consequences:

- **2006-08 .. 2012-03: 40% of composite weight pinned at 0.0**, spanning the GFC.
- **2012-04 .. 2025-06: 20% pinned.**
- Only from 2025-07 (13 months) is the model actually 5-factor.

The credit component — HY OAS, the input most likely to flag credit stress —
contributed exactly nothing to every historical crash call.

Root cause is upstream: the deployed FRED cache holds `BAMLH0A0HYM2` only from
2023-08 and most series from 2019-09. The truncation propagates silently.

## 2. Publication-lag cost (240 months, 2006-09 .. 2026-08)

Sharpe is excess over 0% — the snapshot has no pre-2019 risk-free series. Both
arms are treated identically, so the delta is clean; the levels are indicative.

| variant | Sharpe | alpha% | maxDD% | crashes |
|---|---:|---:|---:|---:|
| 5F as configured / no lag | 0.867 | 3.03 | −21.2 | 1/4 |
| 5F as configured / lagged | 0.769 | 1.71 | −26.2 | 2/4 |
| live-only renormalised / no lag | 0.872 | 3.01 | −21.2 | 2/4 |
| live-only renormalised / lagged | 0.765 | 1.41 | −30.9 | 1/4 |
| SPY buy & hold | 0.781 | — | −50.8 | — |

**Cost of honest lags: −0.098 to −0.107 Sharpe, −1.32 to −1.60% alpha.**

The as-built 0.867 reconciles with the 0.895 no-filter Sharpe recorded in
`production_filter.py` (different window and rf treatment), so the
reconstruction is tracking the production path.

## 3. Against an exposure-matched static allocation

The right benchmark is not SPY — it is a fixed weight with the same average
exposure and zero timing.

| | Sharpe | return | maxDD | beta |
|---|---:|---:|---:|---:|
| as-built, timed | 0.867 | 8.76% | −21.2% | 0.48 |
| static 56% | 0.781 | 6.75% | −32.3% | 0.56 |
| **timing value** | **+0.086** | +2.01% | +11.1pp | |
| | | | | |
| lagged, timed | 0.769 | 8.84% | −26.2% | 0.60 |
| static 61% | 0.781 | 7.29% | −34.4% | 0.61 |
| **timing value** | **−0.012** | +1.55% | +8.2pp | |

## 4. Lead-lag: no detectable structure

Permutation null, 500 shuffles, bar = 95th percentile of max|r| across 19 lags.

| factor | peak lag | peak r | noise bar | p |
|---|---:|---:|---:|---:|
| curve_signal | 3 | −0.118 | 0.174 | 0.39 |
| m2_signal | 5 | −0.102 | 0.173 | 0.55 |
| dollar_stress_signal | 6 | −0.098 | 0.241 | 0.98 |
| rate_signal | 10 | +0.097 | 0.189 | 0.74 |
| quantity_signal | 6 | −0.091 | 0.176 | 0.66 |

0 of 5 clear the bar. Peak correlations are weaker than what searching 19 lags
finds in shuffled data.

## 5. Crash detection

Published claim was 4/4. Measured here: 1/4 to 2/4, and which events are caught
**flips between variants without a consistent pattern** — the mark of noise.
Vol Shock Q4-2018 and COVID are missed by every variant. With n=4 events, "4/4"
was never a statistically meaningful claim in either direction.

## What survives

Drawdown reduction is real and holds up after lagging: −26.2% vs −50.8% for
SPY, and 8pp better than the exposure-matched static. The model works as a
de-risking overlay. It does not show alpha or timing skill by Sharpe.

## What this re-test cannot settle

- **The spline (interpolation) effect.** `ratio_series` is downstream of the
  cubic spline, so the snapshot cannot isolate it. `bias_lab.py` measures it
  separately: negligible at the 20% weight the 5F model gives it.
- **Revisions.** All values are current-vintage. This corrects look-ahead in
  *timing*, not in *values*. A true point-in-time rebuild needs ALFRED
  (see `pit_fred.py`) and, for BIS and the basis-swap gist, forward archiving —
  neither publishes recoverable vintage history.
- **Absolute levels.** Truncated FRED cache and no pre-2019 rf. Read deltas.

## Next steps, in order

1. Fix the FRED cache truncation and re-run. Everything above rests on a
   composite that was 3-of-5 live through the GFC; the model deserves to be
   judged on its full input set before any conclusion is called final.
2. Re-run `snapshot_retest.py` and `leadlag.py` on the repaired data.
3. Only if the lead-lag test then shows real structure is the point-in-time
   rebuild worth the effort.
