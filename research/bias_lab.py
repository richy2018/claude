"""Quantify how much each construction bias inflates measured GLI performance.

WHY THIS EXISTS
---------------
The honest way to size the bias is to rebuild the signal from point-in-time
vintages and compare. That needs FRED/ALFRED, BIS and the basis-swap history,
none of which are reachable from this environment.

So this measures the bias a different way: on a synthetic world where the true
tradable edge is set by construction. Run the same pipelines over it and any
performance above the true edge is bias, attributable to a named mechanism.

WHAT THIS IS AND IS NOT
-----------------------
IS:     the magnitude of each mechanism, under a data-generating process
        calibrated to look like the real inputs (quarterly BIS-like factor with
        a slow financial cycle, monthly M2-like factor, fast market factors).
IS NOT: the number for this model on real data. The real number depends on how
        strongly BIS credit actually leads SPY, which only real data can say.

Read the output as "the leak is worth about this much Sharpe under plausible
conditions", not as a restatement of the model's track record.

PIPELINES
---------
  A  as_built        CubicSpline over the whole quarterly history, no lags.
                     This is research/data_loaders.py:build_gli_signal today.
  B  causal_nolag    Step-expand the quarterly factor, still no lags.
  C  causal_lagged   Step-expand + real publication lags. The honest pipeline.
  D  spline_lagged   CubicSpline + lags, to test whether the lag masks the spline.

  A - B  = the interpolation leak
  B - C  = the publication-lag effect
  A - C  = total flattering margin
  D - C  = spline leak that survives lagging

Usage:
  python3 research/bias_lab.py --draws 400
  python3 research/bias_lab.py --draws 400 --scenario null
"""

import argparse
import sys

import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline

sys.path.insert(0, __file__.rsplit("/", 2)[0])

from research.causal import (
    quarterly_to_monthly_causal, expanding_quintiles, PUBLICATION_LAG_MONTHS,
)

N_MONTHS = 300          # ~25 years, matching the 2001-2026 backtest window
CYCLE_MONTHS = 65       # Howell's liquidity cycle, as the model itself assumes
ALLOC = {1: 1.0, 2: 1.0, 3: 1.0, 4: 0.10, 5: 0.10}
KEYS = ["quantity_signal", "m2_signal", "spread_signal",
        "dollar_stress_signal", "rate_signal"]
WEIGHTS = {k: 0.20 for k in KEYS}


# ---------------------------------------------------------------------------
# Data-generating process
# ---------------------------------------------------------------------------

def simulate_world(rng, scenario="lead", beta=0.55, noise=0.040, lead_months=6):
    """Build one synthetic history: five factors plus an SPY return series.

    A latent liquidity cycle L drives every factor and (in the non-null
    scenarios) equity returns too. That shared driver is what makes the
    interpolation leak profitable: knowing the quarterly factor's future is
    knowing L's future, which is knowing SPY's future.

    scenario:
      "lead"  returns respond to the change in L six months later. There IS a
              real, tradeable edge — a causal pipeline should find it.
      "coin"  returns respond to the change in L in the same month. No tradeable
              edge from lagged data; anything a pipeline earns is leak.
      "null"  returns are independent of L. True edge is exactly zero, so any
              measured performance is pure artefact. Sanity check on the harness.
    """
    idx = pd.date_range("2001-01-01", periods=N_MONTHS, freq="MS")

    # Latent cycle: deterministic 65-month sine plus a persistent stochastic
    # component, so it is neither perfectly predictable nor white noise.
    t = np.arange(N_MONTHS)
    cycle = np.sin(2 * np.pi * t / CYCLE_MONTHS)
    ar = np.zeros(N_MONTHS)
    for i in range(1, N_MONTHS):
        ar[i] = 0.94 * ar[i - 1] + rng.normal(0, 0.35)
    L = pd.Series(cycle + ar, index=idx)

    dL = L.diff()

    if scenario == "lead":
        driver = dL.shift(lead_months)   # liquidity leads equities by N months
    elif scenario == "coin":
        driver = dL                   # contemporaneous only
    elif scenario == "null":
        driver = pd.Series(0.0, index=idx)
    else:
        raise ValueError(f"unknown scenario {scenario!r}")

    spy = pd.Series(
        0.006 - beta * driver.fillna(0.0).to_numpy() * 0.02
        + rng.normal(0, noise, N_MONTHS),
        index=idx,
    )

    # Factors are noisy observations of the same latent cycle.
    def factor(scale):
        return pd.Series(L.to_numpy() + rng.normal(0, scale, N_MONTHS), index=idx)

    quantity_monthly = factor(0.30)
    components_monthly = {
        "m2_signal": factor(0.55),
        "spread_signal": factor(0.75),
        "dollar_stress_signal": factor(0.75),
        "rate_signal": factor(0.65),
    }

    # The quantity factor is only ever OBSERVED at quarter ends. That sparsity
    # is what forces an interpolation choice in the first place.
    quarterly = quantity_monthly.resample("QE").last()

    return idx, quarterly, components_monthly, spy


# ---------------------------------------------------------------------------
# The two interpolation conventions
# ---------------------------------------------------------------------------

def spline_expand(quarterly, idx):
    """Reproduce gli_engine.interpolate_quarterly_to_monthly (the as-built path)."""
    s = quarterly.dropna()
    x = (s.index - s.index[0]).days.to_numpy().astype(float)
    cs = CubicSpline(x, s.to_numpy(), extrapolate=False)
    x_new = (idx - s.index[0]).days.to_numpy().astype(float)
    return pd.Series(cs(x_new), index=idx)


def step_expand(quarterly, idx):
    """Causal step expansion."""
    return quarterly_to_monthly_causal(quarterly).reindex(idx, method="ffill")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(idx, quarterly, monthly, spy, interp="spline", lags=False):
    """Build signal -> quintiles -> allocation -> return the strategy's returns."""
    qty = (spline_expand if interp == "spline" else step_expand)(quarterly, idx)

    comps = {"quantity_signal": qty, **monthly}

    if lags:
        comps = {k: v.shift(PUBLICATION_LAG_MONTHS.get(k, 0)) for k, v in comps.items()}

    comp = pd.Series(0.0, index=idx)
    for k in KEYS:
        comp = comp + WEIGHTS[k] * comps[k]
    comp = comp.dropna()

    signal = comp.diff(6).dropna()
    if len(signal) < 60:
        return None

    q = expanding_quintiles(signal, min_window=36).dropna()

    common = q.index.intersection(spy.index)
    if len(common) < 60:
        return None

    w = q.reindex(common).map(ALLOC).astype(float)
    return spy.reindex(common) * w          # cash leg earns 0 in this experiment


def metrics(port, bench):
    """Sharpe and CAPM alpha of the strategy, both annualised."""
    if port is None or len(port) < 36:
        return None
    sd = float(port.std())
    sharpe = float(port.mean()) / sd * np.sqrt(12) if sd > 1e-12 else 0.0

    b = bench.reindex(port.index)
    var = float(b.var())
    beta = float(port.cov(b)) / var if var > 1e-12 else 0.0
    alpha = (float(port.mean()) - beta * float(b.mean())) * 12 * 100

    return {"sharpe": sharpe, "alpha": alpha, "beta": beta}


PIPELINES = {
    "A as_built    (spline, no lag)": dict(interp="spline", lags=False),
    "B causal_nolag(step,   no lag)": dict(interp="step", lags=False),
    "C causal_lagged(step,  lagged)": dict(interp="step", lags=True),
    "D spline_lagged(spline,lagged)": dict(interp="spline", lags=True),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", type=int, default=400)
    ap.add_argument("--scenario", default="lead", choices=["lead", "coin", "null"])
    ap.add_argument("--seed", type=int, default=20260814)
    ap.add_argument("--lead-months", type=int, default=6,
                    help="How many months the latent liquidity cycle leads "
                         "equity returns. Only used by --scenario lead.")
    ap.add_argument("--qty-only", action="store_true",
                    help="Weight the quarterly factor 100%%, isolating the "
                         "interpolation leak from dilution by the four monthly "
                         "factors.")
    args = ap.parse_args()

    if args.qty_only:
        global KEYS, WEIGHTS
        KEYS = ["quantity_signal"]
        WEIGHTS = {"quantity_signal": 1.0}

    rng = np.random.default_rng(args.seed)
    rows = {name: [] for name in PIPELINES}
    bh = []

    for d in range(args.draws):
        idx, quarterly, monthly, spy = simulate_world(
            rng, scenario=args.scenario, lead_months=args.lead_months)
        bh.append(metrics(spy.copy(), spy))
        for name, kw in PIPELINES.items():
            m = metrics(run_pipeline(idx, quarterly, monthly, spy, **kw), spy)
            if m:
                rows[name].append(m)
        if (d + 1) % 100 == 0:
            print(f"  ...{d + 1}/{args.draws} draws", flush=True)

    print()
    print("=" * 78)
    print(f"  BIAS LAB — scenario={args.scenario}  draws={args.draws}  "
          f"months={N_MONTHS}")
    print("=" * 78)
    truth = {"lead": "a real 6-month-lead edge exists",
             "coin": "no edge is available to a lagged observer",
             "null": "true edge is exactly zero"}[args.scenario]
    print(f"  Ground truth: {truth}")
    print(f"  Buy & hold:   Sharpe {np.mean([m['sharpe'] for m in bh]):.3f}")
    print("-" * 78)
    print(f"  {'pipeline':<32}{'Sharpe':>9}{'  (sd)':>8}{'alpha%':>9}{'  (sd)':>8}")
    print("-" * 78)

    series = {}
    for name in PIPELINES:
        s = np.array([m["sharpe"] for m in rows[name]])
        a = np.array([m["alpha"] for m in rows[name]])
        series[name] = (s, a)
        print(f"  {name:<32}{s.mean():>9.3f}{s.std():>8.3f}"
              f"{a.mean():>9.2f}{a.std():>8.2f}")

    # Paired differences. Every pipeline sees the identical draw, so the draw-to-
    # draw variance cancels and the standard error on the DIFFERENCE is far
    # smaller than the standard deviation of either level. t = mean/se.
    print("-" * 78)
    print("  Paired differences (same draw, so draw variance cancels):")
    print(f"  {'mechanism':<34}{'dSharpe':>9}{'se':>7}{'t':>7}{'dAlpha%':>9}{'se':>7}{'t':>7}")
    print("-" * 78)

    names = list(PIPELINES)
    n = args.draws

    def paired(lhs, rhs, label):
        ds = series[lhs][0] - series[rhs][0]
        da = series[lhs][1] - series[rhs][1]
        se_s, se_a = ds.std(ddof=1) / np.sqrt(n), da.std(ddof=1) / np.sqrt(n)
        t_s = ds.mean() / se_s if se_s > 1e-12 else 0.0
        t_a = da.mean() / se_a if se_a > 1e-12 else 0.0
        print(f"  {label:<34}{ds.mean():>+9.3f}{se_s:>7.3f}{t_s:>7.1f}"
              f"{da.mean():>+9.2f}{se_a:>7.2f}{t_a:>7.1f}")

    paired(names[0], names[1], "interpolation leak       (A-B)")
    paired(names[1], names[2], "publication-lag effect   (B-C)")
    paired(names[0], names[2], "TOTAL flattering margin  (A-C)")
    paired(names[3], names[2], "spline leak after lagging(D-C)")
    print("=" * 78)


if __name__ == "__main__":
    main()
