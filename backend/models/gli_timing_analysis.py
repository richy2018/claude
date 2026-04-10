"""Track 1 — Signal Timing & Lead/Lag Structure for GLI 3FA model.

Cross-correlation at lags -6 to +6, per-factor transform comparison,
staggered alignment model vs contemporaneous.
"""

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

from .backtest_engine import (
    _extract_components, SIGNAL_TRANSFORMS, PRODUCTION_MODELS,
)

_PROD = PRODUCTION_MODELS["5f"]
_PROD_KEYS = _PROD["keys"]
_PROD_WEIGHTS = _PROD["weights"]
_SIG_FN = SIGNAL_TRANSFORMS["mom6"][1]

LAGS = list(range(-6, 7))  # -6 to +6 months
TRANSFORM_KEYS = ["level", "mom1", "mom3", "mom6", "accel", "z12"]


def _sharpe_from_signal(signal, spy_monthly):
    """Quick Sharpe from signal + SPY prices."""
    alloc_map = {1: 1.0, 2: 1.0, 3: 0.7, 4: 0.4, 5: 0.2}
    spy_ret = spy_monthly.pct_change().dropna()
    aligned = pd.concat([signal.rename("sig"), spy_ret.rename("ret")], axis=1).dropna()
    if len(aligned) < 30:
        return 0, 0
    try:
        q = pd.qcut(aligned["sig"], 5, labels=[1, 2, 3, 4, 5], duplicates='drop')
    except Exception:
        return 0, 0
    w = q.map(alloc_map).astype(float)
    port = aligned["ret"] * w
    eq = (1 + port).cumprod()
    years = len(port) / 12
    ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
    ann_vol = float(port.std() * np.sqrt(12))
    sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 1e-8 else 0
    peak = eq.expanding().max()
    max_dd = round(float(((eq - peak) / peak).min()) * 100, 1)
    return sharpe, max_dd


def analyze_cross_correlations(components, spy_monthly):
    """Compute cross-correlation of each factor with SPY forward returns at lags -6 to +6.

    Returns: dict of {factor: {lag: {corr_3m, corr_6m, corr_12m}}}
    """
    spy_fwd_3 = spy_monthly.pct_change(3).shift(-3) * 100
    spy_fwd_6 = spy_monthly.pct_change(6).shift(-6) * 100
    spy_fwd_12 = spy_monthly.pct_change(12).shift(-12) * 100

    results = {}
    for k in _PROD_KEYS:
        if k not in components:
            continue
        s = components[k]
        lag_results = {}

        for lag in LAGS:
            shifted = s.shift(lag)  # positive lag = signal leads (look at past signal)
            common = shifted.dropna().index
            common = common.intersection(spy_fwd_6.dropna().index)
            if len(common) < 30:
                lag_results[lag] = {"corr_3m": None, "corr_6m": None, "corr_12m": None}
                continue

            c3 = float(shifted.reindex(common).corr(spy_fwd_3.reindex(common)))
            c6 = float(shifted.reindex(common).corr(spy_fwd_6.reindex(common)))
            c12 = float(shifted.reindex(common).corr(spy_fwd_12.reindex(common)))

            lag_results[lag] = {
                "corr_3m": round(c3, 4),
                "corr_6m": round(c6, 4),
                "corr_12m": round(c12, 4),
            }

        # Find optimal lag per horizon
        best_6m_lag = min(lag_results, key=lambda l: lag_results[l].get("corr_6m") or 0)
        results[k] = {
            "lags": lag_results,
            "best_lag_6m": best_6m_lag,
            "best_corr_6m": lag_results[best_6m_lag].get("corr_6m"),
            "contemporaneous_corr_6m": lag_results[0].get("corr_6m"),
        }

    return results


def analyze_per_factor_transforms(components, spy_monthly):
    """For each factor, which transform maximizes correlation with forward equity returns?

    Tests: level, mom1, mom3, mom6, accel, z12.
    """
    spy_fwd_6 = spy_monthly.pct_change(6).shift(-6) * 100

    results = {}
    for k in _PROD_KEYS:
        if k not in components:
            continue
        s = components[k]
        transform_results = {}

        for tkey in TRANSFORM_KEYS:
            _, tfn = SIGNAL_TRANSFORMS[tkey]
            transformed = tfn(s).dropna()
            common = transformed.index.intersection(spy_fwd_6.dropna().index)
            if len(common) < 30:
                continue

            corr = float(transformed.reindex(common).corr(spy_fwd_6.reindex(common)))

            # OOS: second half
            mid = len(common) // 2
            oos = common[mid:]
            if len(oos) >= 20:
                oos_corr = float(transformed.reindex(oos).corr(spy_fwd_6.reindex(oos)))
            else:
                oos_corr = None

            transform_results[tkey] = {
                "full_corr": round(corr, 4),
                "oos_corr": round(oos_corr, 4) if oos_corr is not None else None,
            }

        best_transform = min(transform_results,
                             key=lambda t: transform_results[t].get("oos_corr") or 0)
        results[k] = {
            "transforms": transform_results,
            "best_transform": best_transform,
            "best_oos_corr": transform_results[best_transform].get("oos_corr"),
            "mom6_oos_corr": transform_results.get("mom6", {}).get("oos_corr"),
        }

    return results


def test_staggered_model(components, spy_monthly, cross_corr_results):
    """Build staggered composite: shift each component by its optimal lag.

    Compare Sharpe: contemporaneous vs staggered.
    """
    # Get optimal lags
    optimal_lags = {}
    for k in _PROD_KEYS:
        if k in cross_corr_results:
            optimal_lags[k] = cross_corr_results[k]["best_lag_6m"]
        else:
            optimal_lags[k] = 0

    # Contemporaneous model (baseline)
    base_idx = components[_PROD_KEYS[0]].index
    for k in _PROD_KEYS[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()

    comp_contemp = pd.Series(0.0, index=base_idx)
    for k in _PROD_KEYS:
        if k in components:
            comp_contemp += _PROD_WEIGHTS[k] * components[k].reindex(base_idx, method="ffill").fillna(0)
    sig_contemp = _SIG_FN(comp_contemp).dropna()
    sharpe_contemp, dd_contemp = _sharpe_from_signal(sig_contemp, spy_monthly)

    # Staggered model
    comp_stagger = pd.Series(0.0, index=base_idx)
    for k in _PROD_KEYS:
        if k in components:
            shifted = components[k].shift(optimal_lags.get(k, 0))
            comp_stagger += _PROD_WEIGHTS[k] * shifted.reindex(base_idx, method="ffill").fillna(0)
    sig_stagger = _SIG_FN(comp_stagger).dropna()
    sharpe_stagger, dd_stagger = _sharpe_from_signal(sig_stagger, spy_monthly)

    return {
        "optimal_lags": optimal_lags,
        "contemporaneous": {"sharpe": sharpe_contemp, "max_dd": dd_contemp},
        "staggered": {"sharpe": sharpe_stagger, "max_dd": dd_stagger},
        "improvement": round(sharpe_stagger - sharpe_contemp, 3),
    }


def test_best_transform_model(components, spy_monthly, transform_results):
    """Build model using the best transform per factor instead of uniform Mom 6M."""
    # Baseline: all Mom 6M
    base_idx = components[_PROD_KEYS[0]].index
    for k in _PROD_KEYS[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()

    comp_baseline = pd.Series(0.0, index=base_idx)
    for k in _PROD_KEYS:
        if k in components:
            comp_baseline += _PROD_WEIGHTS[k] * components[k].reindex(base_idx, method="ffill").fillna(0)
    sig_baseline = _SIG_FN(comp_baseline).dropna()
    sharpe_baseline, dd_baseline = _sharpe_from_signal(sig_baseline, spy_monthly)

    # Best-transform model: transform each factor independently, then combine
    transformed_factors = {}
    for k in _PROD_KEYS:
        if k in components and k in transform_results:
            best_t = transform_results[k]["best_transform"]
            _, tfn = SIGNAL_TRANSFORMS[best_t]
            transformed_factors[k] = tfn(components[k]).dropna()
        elif k in components:
            transformed_factors[k] = _SIG_FN(components[k]).dropna()

    if len(transformed_factors) < len(_PROD_KEYS):
        return {"error": "Not enough transformed factors"}

    # Combine pre-transformed factors
    common = transformed_factors[_PROD_KEYS[0]].index
    for k in _PROD_KEYS[1:]:
        common = common.intersection(transformed_factors[k].index)
    common = common.sort_values()

    comp_best = pd.Series(0.0, index=common)
    for k in _PROD_KEYS:
        comp_best += _PROD_WEIGHTS[k] * transformed_factors[k].reindex(common, method="ffill").fillna(0)
    # No additional transform — factors are already transformed
    sharpe_best, dd_best = _sharpe_from_signal(comp_best, spy_monthly)

    return {
        "best_transforms": {k: transform_results[k]["best_transform"] for k in _PROD_KEYS if k in transform_results},
        "baseline_mom6": {"sharpe": sharpe_baseline, "max_dd": dd_baseline},
        "best_per_factor": {"sharpe": sharpe_best, "max_dd": dd_best},
        "improvement": round(sharpe_best - sharpe_baseline, 3),
    }


def run_timing_analysis(ratio_series, spy_monthly):
    """Run full timing/lead-lag analysis.

    Returns cross-correlations, per-factor transforms, staggered model comparison.
    """
    components = _extract_components(ratio_series)
    missing = [k for k in _PROD_KEYS if k not in components]
    if missing:
        return {"error": f"Missing components: {missing}"}

    print("[TIMING] Computing cross-correlations at lags -6 to +6...")
    cross_corr = analyze_cross_correlations(components, spy_monthly)

    print("[TIMING] Testing per-factor transforms...")
    transforms = analyze_per_factor_transforms(components, spy_monthly)

    print("[TIMING] Testing staggered alignment model...")
    staggered = test_staggered_model(components, spy_monthly, cross_corr)

    print("[TIMING] Testing best-transform-per-factor model...")
    best_transform = test_best_transform_model(components, spy_monthly, transforms)

    # Summary
    print(f"[TIMING] Staggered improvement: {staggered['improvement']:.3f} Sharpe")
    print(f"[TIMING] Best-transform improvement: {best_transform.get('improvement', 'N/A')}")

    return {
        "cross_correlations": cross_corr,
        "per_factor_transforms": transforms,
        "staggered_model": staggered,
        "best_transform_model": best_transform,
    }


if __name__ == "__main__":
    print("=" * 60)
    print("GLI 3FA Signal Timing & Lead/Lag Analysis")
    print("=" * 60)
    print("Call run_timing_analysis(ratio_series, spy_monthly)")
