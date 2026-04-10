"""Track 2 — Signal Combination Methods for GLI 3FA model.

Tests alternative aggregation methods (zero or minimal extra parameters):
- Rank averaging: percentile rank in trailing 120M window, average
- Binary discretization: +1/-1 per factor, sum to [-3, +3]
- Equal weight: 1/3 each
- Geometric mean: geometric mean of (1 + normalized factor)

Compare each to baseline weighted sum via expanding-window OOS Sharpe.
"""

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

from .backtest_engine import (
    _extract_components, SIGNAL_TRANSFORMS, PRODUCTION_MODELS,
    ALLOCATION_RULES,
)

_PROD = PRODUCTION_MODELS["5f"]
_PROD_KEYS = _PROD["keys"]
_PROD_WEIGHTS = _PROD["weights"]
_SIG_FN = SIGNAL_TRANSFORMS["mom6"][1]
_ALLOC = ALLOCATION_RULES["production"]


def _sharpe_and_dd(signal, spy_monthly):
    """Compute Sharpe and MaxDD from signal + SPY."""
    spy_ret = spy_monthly.pct_change().dropna()
    aligned = pd.concat([signal.rename("sig"), spy_ret.rename("ret")], axis=1).dropna()
    if len(aligned) < 30:
        return 0, 0, 0

    try:
        q = pd.qcut(aligned["sig"], 5, labels=[1, 2, 3, 4, 5], duplicates='drop')
    except Exception:
        return 0, 0, 0

    w = q.map(_ALLOC).astype(float)
    port = aligned["ret"] * w
    eq = (1 + port).cumprod()
    years = len(port) / 12
    ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
    ann_vol = float(port.std() * np.sqrt(12))
    sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 1e-8 else 0
    peak = eq.expanding().max()
    max_dd = round(float(((eq - peak) / peak).min()) * 100, 1)
    calmar = round(ann_ret / abs(max_dd / 100), 2) if abs(max_dd) > 0.1 else 0
    return sharpe, max_dd, calmar


def _oos_corr(signal, spy_fwd):
    """OOS correlation (second half of sample)."""
    common = signal.dropna().index.intersection(spy_fwd.dropna().index)
    if len(common) < 60:
        return None
    mid = len(common) // 2
    oos = common[mid:]
    if len(oos) < 20:
        return None
    return round(float(signal.reindex(oos).corr(spy_fwd.reindex(oos))), 4)


def method_weighted_sum(components, spy_monthly):
    """Baseline: weighted sum with production weights, Mom 6M."""
    base_idx = components[_PROD_KEYS[0]].index
    for k in _PROD_KEYS[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()

    comp = pd.Series(0.0, index=base_idx)
    for k in _PROD_KEYS:
        if k in components:
            comp += _PROD_WEIGHTS[k] * components[k].reindex(base_idx, method="ffill").fillna(0)
    signal = _SIG_FN(comp).dropna()

    spy_fwd = spy_monthly.pct_change(6).shift(-6) * 100
    sharpe, max_dd, calmar = _sharpe_and_dd(signal, spy_monthly)
    oos = _oos_corr(signal, spy_fwd)

    return {
        "name": "Weighted Sum (production)",
        "signal": signal,
        "sharpe": sharpe, "max_dd": max_dd, "calmar": calmar,
        "oos_corr_6m": oos, "n_params": 3,
    }


def method_rank_average(components, spy_monthly):
    """Rank averaging: percentile rank each factor in trailing 120M, average the ranks."""
    base_idx = components[_PROD_KEYS[0]].index
    for k in _PROD_KEYS[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()

    rank_sum = pd.Series(0.0, index=base_idx)
    for k in _PROD_KEYS:
        if k in components:
            s = components[k].reindex(base_idx, method="ffill").fillna(0)
            # Rolling 120M percentile rank
            ranks = s.rolling(120, min_periods=36).apply(
                lambda x: sp_stats.percentileofscore(x, x.iloc[-1]) if len(x) > 1 else 50,
                raw=False)
            rank_sum += ranks

    signal = _SIG_FN(rank_sum / len(_PROD_KEYS)).dropna()

    spy_fwd = spy_monthly.pct_change(6).shift(-6) * 100
    sharpe, max_dd, calmar = _sharpe_and_dd(signal, spy_monthly)
    oos = _oos_corr(signal, spy_fwd)

    return {
        "name": "Rank Average (120M window)",
        "signal": signal,
        "sharpe": sharpe, "max_dd": max_dd, "calmar": calmar,
        "oos_corr_6m": oos, "n_params": 0,
    }


def method_binary(components, spy_monthly):
    """Binary discretization: +1 (above trailing 60M median) or -1. Sum to [-3, +3]."""
    base_idx = components[_PROD_KEYS[0]].index
    for k in _PROD_KEYS[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()

    binary_sum = pd.Series(0.0, index=base_idx)
    for k in _PROD_KEYS:
        if k in components:
            s = components[k].reindex(base_idx, method="ffill").fillna(0)
            median_60 = s.rolling(60, min_periods=24).median()
            binary = pd.Series(-1.0, index=base_idx)
            binary[s > median_60] = 1.0
            binary_sum += binary

    signal = _SIG_FN(binary_sum).dropna()

    spy_fwd = spy_monthly.pct_change(6).shift(-6) * 100
    sharpe, max_dd, calmar = _sharpe_and_dd(signal, spy_monthly)
    oos = _oos_corr(signal, spy_fwd)

    return {
        "name": "Binary Discretization",
        "signal": signal,
        "sharpe": sharpe, "max_dd": max_dd, "calmar": calmar,
        "oos_corr_6m": oos, "n_params": 0,
    }


def method_equal_weight(components, spy_monthly):
    """Equal weight: 1/3 each factor."""
    base_idx = components[_PROD_KEYS[0]].index
    for k in _PROD_KEYS[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()

    comp = pd.Series(0.0, index=base_idx)
    eq_w = 1.0 / len(_PROD_KEYS)
    for k in _PROD_KEYS:
        if k in components:
            comp += eq_w * components[k].reindex(base_idx, method="ffill").fillna(0)
    signal = _SIG_FN(comp).dropna()

    spy_fwd = spy_monthly.pct_change(6).shift(-6) * 100
    sharpe, max_dd, calmar = _sharpe_and_dd(signal, spy_monthly)
    oos = _oos_corr(signal, spy_fwd)

    return {
        "name": "Equal Weight (1/3 each)",
        "signal": signal,
        "sharpe": sharpe, "max_dd": max_dd, "calmar": calmar,
        "oos_corr_6m": oos, "n_params": 0,
    }


def method_geometric(components, spy_monthly):
    """Geometric mean of (1 + normalized_factor). Penalizes divergence."""
    base_idx = components[_PROD_KEYS[0]].index
    for k in _PROD_KEYS[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()

    # Shift factors to [0, 2] range: factor in [-1, 1] → (1 + factor)
    product = pd.Series(1.0, index=base_idx)
    for k in _PROD_KEYS:
        if k in components:
            s = components[k].reindex(base_idx, method="ffill").fillna(0)
            product *= (1 + s).clip(lower=0.01)  # Avoid zero/negative

    # Geometric mean = product^(1/n), then center at 0
    geo = product ** (1.0 / len(_PROD_KEYS)) - 1
    signal = _SIG_FN(geo).dropna()

    spy_fwd = spy_monthly.pct_change(6).shift(-6) * 100
    sharpe, max_dd, calmar = _sharpe_and_dd(signal, spy_monthly)
    oos = _oos_corr(signal, spy_fwd)

    return {
        "name": "Geometric Mean",
        "signal": signal,
        "sharpe": sharpe, "max_dd": max_dd, "calmar": calmar,
        "oos_corr_6m": oos, "n_params": 0,
    }


def run_combination_analysis(ratio_series, spy_monthly):
    """Run all combination method tests.

    Returns comparison table: each method vs baseline weighted sum.
    """
    components = _extract_components(ratio_series)
    missing = [k for k in _PROD_KEYS if k not in components]
    if missing:
        return {"error": f"Missing components: {missing}"}

    print("[COMBINATION] Testing 5 aggregation methods...")

    methods = [
        method_weighted_sum(components, spy_monthly),
        method_equal_weight(components, spy_monthly),
        method_rank_average(components, spy_monthly),
        method_binary(components, spy_monthly),
        method_geometric(components, spy_monthly),
    ]

    # Remove signal from results (too large to serialize)
    for m in methods:
        m.pop("signal", None)

    # Sort by Sharpe
    methods.sort(key=lambda x: x.get("sharpe", 0), reverse=True)
    if methods:
        methods[0]["is_best"] = True

    baseline = next((m for m in methods if "production" in m["name"].lower()), None)
    baseline_sharpe = baseline["sharpe"] if baseline else 0

    for m in methods:
        m["delta_sharpe"] = round(m["sharpe"] - baseline_sharpe, 3)

    # Check if equal weight is within 0.05 Sharpe of optimized → prefer for robustness
    eq = next((m for m in methods if "Equal" in m["name"]), None)
    robustness_note = None
    if eq and baseline:
        diff = abs(eq["sharpe"] - baseline["sharpe"])
        if diff < 0.05:
            robustness_note = f"Equal weight within {diff:.3f} Sharpe of optimized — consider adopting for robustness (0 estimated parameters)."

    print(f"[COMBINATION] Best: {methods[0]['name']} (Sharpe={methods[0]['sharpe']})")

    return {
        "methods": methods,
        "baseline": baseline,
        "best": methods[0] if methods else None,
        "robustness_note": robustness_note,
    }


if __name__ == "__main__":
    print("=" * 60)
    print("GLI 3FA Signal Combination Methods")
    print("=" * 60)
    print("Call run_combination_analysis(ratio_series, spy_monthly)")
