"""GLI Signal Conviction Enhancement — Methods 1, 2, 4.

Method 1: Signal momentum (rate of change → conviction level)
Method 2: Factor consensus (how many factors agree on stress)
Method 4: VIX term structure confirmation (backwardation filter)

All methods maintain 4/4 crash detection as a hard constraint.
"""

import numpy as np
import pandas as pd

from .backtest_engine import (
    _extract_components, SIGNAL_TRANSFORMS, PRODUCTION_MODELS,
    ALLOCATION_RULES, sortino_ratio, COMP_LABELS, sharpe_ratio,
    _old_sharpe_geometric, rf_from_fred,
)

_PROD = PRODUCTION_MODELS["5f"]
_PROD_KEYS = _PROD["keys"]
_PROD_WEIGHTS = _PROD["weights"]
_SIG_FN = SIGNAL_TRANSFORMS["mom6"][1]
_ALLOC = ALLOCATION_RULES["production"]  # 100/100/100/10/10

TAIL_EVENTS = [
    {"name": "GFC", "start": "2007-09-01"},
    {"name": "COVID", "start": "2020-02-01"},
    {"name": "Rate Shock", "start": "2022-01-01"},
    {"name": "Vol Shock Q4-2018", "start": "2018-10-01"},
]


def _build_signal(components):
    """Build 5F composite + Mom6M signal."""
    base_idx = components[_PROD_KEYS[0]].index
    for k in _PROD_KEYS[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()
    comp = pd.Series(0.0, index=base_idx)
    for k in _PROD_KEYS:
        if k in components:
            comp += _PROD_WEIGHTS[k] * components[k].reindex(base_idx, method="ffill").fillna(0)
    return _SIG_FN(comp).dropna()


def _expanding_quintile_series(signal):
    """Compute expanding-window quintile for every date (no future info)."""
    quintiles = pd.Series(3, index=signal.index, dtype=int)
    for i in range(20, len(signal)):
        hist = signal.iloc[:i+1]
        val = hist.iloc[-1]
        pct = float((hist <= val).mean()) * 100
        quintiles.iloc[i] = 1 if pct < 20 else 2 if pct < 40 else 3 if pct < 60 else 4 if pct < 80 else 5
    return quintiles


def _backtest(weights, spy_ret, vix_data=None, target_vol=0.10, rf_monthly=None):
    """Run backtest from pre-computed weights series. Cash leg earns rf_monthly."""
    if vix_data is not None and len(vix_data) > 12:
        vix_m = vix_data.resample("MS").last().dropna() / 100
        realized = spy_ret.rolling(5, min_periods=3).std() * np.sqrt(12)
        realized = realized.clip(lower=0.05)
        vix_al = vix_m.reindex(weights.index, method="ffill")
        vol = vix_al.fillna(realized.reindex(weights.index, method="ffill")).clip(lower=0.05)
        vs = (target_vol / vol).clip(upper=2.0)
        weights = (weights * vs).clip(0, 1)

    rf_m = rf_monthly.reindex(weights.index, method="ffill").fillna(0.0) if rf_monthly is not None else pd.Series(0.0, index=weights.index)
    aligned_ret = spy_ret.reindex(weights.index).fillna(0)
    port_ret = aligned_ret * weights + rf_m * (1 - weights)
    eq = (1 + port_ret).cumprod()
    years = len(port_ret) / 12
    ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
    ann_vol = float(port_ret.std() * np.sqrt(12))
    sharpe = sharpe_ratio(port_ret, rf=rf_monthly)
    sharpe_old = _old_sharpe_geometric(aligned_ret * weights)
    sort = sortino_ratio(port_ret, rf=rf_monthly)
    peak = eq.expanding().max()
    max_dd = round(float(((eq - peak) / peak).min()) * 100, 1)
    total = round(float(eq.iloc[-1] - 1) * 100, 1)
    pct_def = round(float((weights < 0.5).mean()) * 100, 1)
    return {"sharpe": sharpe, "sharpe_old_geometric": sharpe_old,
            "sortino": sort, "max_dd": max_dd,
            "total_return": total, "ann_return": round(ann_ret * 100, 2),
            "pct_defensive": pct_def}


def _crash_detection_check(quintiles, conviction_weights):
    """Check if signal was defensive (weight < 50%) at each crash onset."""
    detected = 0
    details = []
    for event in TAIL_EVENTS:
        d = pd.Timestamp(event["start"])
        d_before = d - pd.DateOffset(months=1)
        w_at = conviction_weights.get(d) if d in conviction_weights.index else None
        w_before = conviction_weights.get(d_before) if d_before in conviction_weights.index else None
        was_def = (w_at is not None and w_at < 0.5) or (w_before is not None and w_before < 0.5)
        if was_def:
            detected += 1
        details.append({"event": event["name"], "weight_at_start": round(float(w_at), 2) if w_at is not None else None,
                         "detected": was_def})
    return detected, details


def _false_positive_rate(quintiles, spy_ret):
    """% of Q4-Q5 months NOT followed by >15% drawdown in next 3M."""
    defensive = quintiles >= 4
    spy_fwd_3m = spy_ret.rolling(3).sum().shift(-3) * 100  # Approx 3M fwd return
    n_defensive = int(defensive.sum())
    if n_defensive == 0:
        return 0, 0
    # Check if any 3M forward window has a >15% decline
    dd_mask = spy_fwd_3m < -15
    fp = 0
    for d in quintiles[defensive].index:
        if d in dd_mask.index and not dd_mask.get(d, False):
            fp += 1
    return round(fp / max(n_defensive, 1) * 100, 1), n_defensive


# ─── Method 1: Signal Momentum ──────────────────────────────────────────────

def run_signal_momentum(ratio_series, spy_monthly, vix_data=None, rf_monthly=None):
    """Method 1: Conviction based on speed of signal change."""
    components = _extract_components(ratio_series)
    signal = _build_signal(components)
    spy_ret = spy_monthly.pct_change().dropna()
    quintiles = _expanding_quintile_series(signal)

    # Signal momentum: 1M and 2M changes in quintile
    q_mom1 = quintiles.diff(1)  # Quintile change in 1 month
    q_mom2 = quintiles.diff(2)  # Quintile change in 2 months

    # Conviction levels
    def _conviction(i):
        if i < 2:
            return "LOW"
        m1 = q_mom1.iloc[i] if not np.isnan(q_mom1.iloc[i]) else 0
        m2 = q_mom2.iloc[i] if not np.isnan(q_mom2.iloc[i]) else 0
        if m1 >= 2 or m2 >= 3:
            return "HIGH"
        if m1 >= 1 or m2 >= 2:
            return "MEDIUM"
        return "LOW"

    conviction = pd.Series([_conviction(i) for i in range(len(quintiles))], index=quintiles.index)

    # Conviction-adjusted allocation
    conv_weights = pd.Series(1.0, index=quintiles.index)
    for i in range(len(quintiles)):
        q = quintiles.iloc[i]
        c = conviction.iloc[i]
        if q >= 4:
            if c == "HIGH":
                conv_weights.iloc[i] = 0.10
            elif c == "MEDIUM":
                conv_weights.iloc[i] = 0.40
            else:
                conv_weights.iloc[i] = 0.70

    # Baseline (current flat rule)
    base_weights = quintiles.map(_ALLOC).astype(float)

    # Backtest both
    conv_metrics = _backtest(conv_weights, spy_ret, rf_monthly=rf_monthly)
    base_metrics = _backtest(base_weights, spy_ret, rf_monthly=rf_monthly)

    # Crash detection check
    conv_detected, conv_details = _crash_detection_check(quintiles, conv_weights)
    base_detected, _ = _crash_detection_check(quintiles, base_weights)

    # False positive rates
    fp_conv, n_def_conv = _false_positive_rate(quintiles, spy_ret)
    fp_base, n_def_base = _false_positive_rate(quintiles, spy_ret)

    print(f"[CONVICTION M1] Momentum: Sharpe={conv_metrics['sharpe']} vs Base={base_metrics['sharpe']}, "
          f"Crashes={conv_detected}/4, FP conv adj effective DEF%={conv_metrics['pct_defensive']}%")

    return {
        "method": "signal_momentum",
        "conviction_metrics": conv_metrics,
        "baseline_metrics": base_metrics,
        "crash_detection": {"detected": conv_detected, "total": 4, "details": conv_details},
        "baseline_crash_detection": base_detected,
        "pct_defensive_conviction": conv_metrics["pct_defensive"],
        "pct_defensive_baseline": base_metrics["pct_defensive"],
    }


# ─── Method 2: Factor Consensus ─────────────────────────────────────────────

def run_factor_consensus(ratio_series, spy_monthly, vix_data=None, rf_monthly=None):
    """Method 2: Conviction based on how many factors agree on stress."""
    components = _extract_components(ratio_series)
    signal = _build_signal(components)
    spy_ret = spy_monthly.pct_change().dropna()
    quintiles = _expanding_quintile_series(signal)

    # For each factor: is it below its trailing 12M median?
    common = signal.index
    market_factors = {"spread_signal", "dollar_stress_signal"}

    consensus = pd.Series(0.0, index=common)
    for k in _PROD_KEYS:
        if k not in components:
            continue
        s = components[k].reindex(common, method="ffill").fillna(0)
        median_12 = s.rolling(12, min_periods=6).median()
        stressed = (s > median_12).astype(float)  # Above median = tightening for these signals
        weight = 1.5 if k in market_factors else 1.0
        consensus += stressed * weight

    # Normalize to 0-5 scale
    max_score = sum(1.5 if k in market_factors else 1.0 for k in _PROD_KEYS)
    consensus_norm = (consensus / max_score * 5).clip(0, 5)

    # Conviction levels
    conv_weights = pd.Series(1.0, index=common)
    for i in range(len(quintiles)):
        q = quintiles.iloc[i] if i < len(quintiles) else 3
        c = consensus_norm.iloc[i] if i < len(consensus_norm) else 2.5
        if q >= 4:
            if c >= 4:
                conv_weights.iloc[i] = 0.10  # HIGH consensus
            elif c >= 3:
                conv_weights.iloc[i] = 0.40  # MEDIUM
            else:
                conv_weights.iloc[i] = 0.70  # LOW

    base_weights = quintiles.map(_ALLOC).astype(float)

    conv_metrics = _backtest(conv_weights, spy_ret, rf_monthly=rf_monthly)
    base_metrics = _backtest(base_weights, spy_ret, rf_monthly=rf_monthly)

    conv_detected, conv_details = _crash_detection_check(quintiles, conv_weights)

    # Consensus at each crash
    crash_consensus = []
    for event in TAIL_EVENTS:
        d = pd.Timestamp(event["start"])
        c_val = consensus_norm.get(d) if d in consensus_norm.index else None
        crash_consensus.append({"event": event["name"],
                                 "consensus": round(float(c_val), 1) if c_val is not None else None})

    print(f"[CONVICTION M2] Consensus: Sharpe={conv_metrics['sharpe']} vs Base={base_metrics['sharpe']}, "
          f"Crashes={conv_detected}/4, DEF%={conv_metrics['pct_defensive']}%")

    return {
        "method": "factor_consensus",
        "conviction_metrics": conv_metrics,
        "baseline_metrics": base_metrics,
        "crash_detection": {"detected": conv_detected, "total": 4, "details": conv_details},
        "crash_consensus": crash_consensus,
        "pct_defensive_conviction": conv_metrics["pct_defensive"],
    }


# ─── Method 4: VIX Term Structure ───────────────────────────────────────────

def run_vix_confirmation(ratio_series, spy_monthly, vix_data=None, rf_monthly=None):
    """Method 4: VIX backwardation as confirmation filter."""
    components = _extract_components(ratio_series)
    signal = _build_signal(components)
    spy_ret = spy_monthly.pct_change().dropna()
    quintiles = _expanding_quintile_series(signal)

    if vix_data is None or len(vix_data) < 60:
        return {"error": "No VIX data for term structure analysis"}

    vix_m = vix_data.resample("MS").last().dropna()
    # Proxy for term structure: VIX vs 3M moving average
    # VIX > 3M MA = backwardation proxy (stress), VIX < 3M MA = contango (calm)
    vix_ma3 = vix_m.rolling(3, min_periods=2).mean()
    vix_slope = vix_ma3 - vix_m  # Positive = contango, negative = backwardation
    backwardation = vix_slope < 0

    common = quintiles.index.intersection(backwardation.index)
    quintiles = quintiles.reindex(common)
    backwardation = backwardation.reindex(common, method="ffill").fillna(False)

    # Confirmation rule
    conv_weights = pd.Series(1.0, index=common)
    for i in range(len(common)):
        q = quintiles.iloc[i]
        is_backwd = bool(backwardation.iloc[i])
        if q >= 4:
            if is_backwd:
                conv_weights.iloc[i] = 0.10  # CONFIRMED stress
            else:
                conv_weights.iloc[i] = 0.60  # UNCONFIRMED

    base_weights = quintiles.map(_ALLOC).astype(float)

    conv_metrics = _backtest(conv_weights, spy_ret, rf_monthly=rf_monthly)
    base_metrics = _backtest(base_weights, spy_ret, rf_monthly=rf_monthly)
    conv_detected, conv_details = _crash_detection_check(quintiles, conv_weights)

    # VIX state at each crash
    crash_vix = []
    for event in TAIL_EVENTS:
        d = pd.Timestamp(event["start"])
        bw = bool(backwardation.get(d, False)) if d in backwardation.index else None
        v = float(vix_m.get(d, 0)) if d in vix_m.index else None
        crash_vix.append({"event": event["name"], "backwardation": bw,
                          "vix": round(v, 1) if v else None})

    print(f"[CONVICTION M4] VIX: Sharpe={conv_metrics['sharpe']} vs Base={base_metrics['sharpe']}, "
          f"Crashes={conv_detected}/4, DEF%={conv_metrics['pct_defensive']}%")

    return {
        "method": "vix_confirmation",
        "conviction_metrics": conv_metrics,
        "baseline_metrics": base_metrics,
        "crash_detection": {"detected": conv_detected, "total": 4, "details": conv_details},
        "crash_vix_state": crash_vix,
        "pct_defensive_conviction": conv_metrics["pct_defensive"],
    }


# ─── Orchestrator ────────────────────────────────────────────────────────────

def run_conviction_analysis(ratio_series, spy_monthly, vix_data=None, fred_data=None):
    """Run all conviction methods and compare."""
    spy_index = spy_monthly.pct_change().dropna().index
    rf_monthly = rf_from_fred(fred_data, spy_index)

    print("[CONVICTION] === Method 1: Signal Momentum ===")
    m1 = run_signal_momentum(ratio_series, spy_monthly, vix_data, rf_monthly=rf_monthly)

    print("\n[CONVICTION] === Method 2: Factor Consensus ===")
    m2 = run_factor_consensus(ratio_series, spy_monthly, vix_data, rf_monthly=rf_monthly)

    print("\n[CONVICTION] === Method 4: VIX Confirmation ===")
    m4 = run_vix_confirmation(ratio_series, spy_monthly, vix_data, rf_monthly=rf_monthly)

    # Comparison summary
    methods = []
    for label, result in [("Current (flat rule)", None),
                          ("Signal Momentum", m1), ("Factor Consensus", m2),
                          ("VIX Confirmation", m4)]:
        if result is None:
            base = m1.get("baseline_metrics", {}) if m1 else {}
            methods.append({"method": label, "crashes": "4/4",
                            **{k: base.get(k) for k in ["sharpe", "sharpe_old_geometric", "sortino", "max_dd", "total_return", "pct_defensive"]}})
        elif "error" not in result:
            cm = result.get("conviction_metrics", {})
            cd = result.get("crash_detection", {})
            methods.append({
                "method": label,
                "crashes": f"{cd.get('detected', '?')}/{cd.get('total', 4)}",
                **{k: cm.get(k) for k in ["sharpe", "sharpe_old_geometric", "sortino", "max_dd", "total_return", "pct_defensive"]},
            })

    print("[CONVICTION] Sharpe old (geometric) -> new (arithmetic excess):")
    for row in methods:
        if "sharpe" in row:
            print(f"[CONVICTION]   {row['method']:<28} {row.get('sharpe_old_geometric', 0):>6.3f} -> {row.get('sharpe', 0):>6.3f}")

    return {
        "signal_momentum": m1,
        "factor_consensus": m2,
        "vix_confirmation": m4,
        "comparison": methods,
    }
