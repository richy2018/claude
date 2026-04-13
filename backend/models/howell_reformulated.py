"""Howell Reformulated Debt/Liquidity Ratio.

Uses M2 as the base level + GLI production signal as the cyclical overlay.
Calibrates (scale, λ) against Howell's anchor points.
"""

import numpy as np
import pandas as pd


def _normalize_qtr(s):
    """Normalize Series index to quarter-end for alignment."""
    if len(s) == 0:
        return s
    s = s.copy()
    s.index = pd.to_datetime(s.index).to_period('Q').to_timestamp('Q')
    s = s[~s.index.duplicated(keep='last')]
    return s.sort_index()


def calibrate_ratio(m2_base, gli_z, debt, anchors):
    """Grid search (scale, λ) to minimize weighted MSE against Howell anchors.

    Effective_Liquidity = m2_base × scale × (1 + gli_z × λ)
    Ratio = debt / Effective_Liquidity
    """
    # Align all series
    common = m2_base.index.intersection(gli_z.index).intersection(debt.index)
    if len(common) < 10:
        return None, None, float('inf')

    m2 = m2_base.reindex(common)
    gli = gli_z.reindex(common).fillna(0)
    d = debt.reindex(common)

    # Prepare anchor targets
    anchor_targets = []
    for a in anchors:
        if a.get("ratio") is None:
            continue
        ad = pd.Timestamp(a.get("date_aligned", a["date"]))
        # Find nearest date in common
        diffs = abs(common - ad)
        nearest_idx = diffs.argmin()
        if diffs[nearest_idx].days > 180:
            continue
        weight = 1.0 if a.get("confidence") == "stated" else 0.5
        anchor_targets.append((nearest_idx, float(a["ratio"]), weight))

    if len(anchor_targets) < 2:
        return 8.5, 0.5, float('inf')  # Defaults

    best_score = float('inf')
    best_scale = 8.5
    best_lambda = 0.5

    for scale in np.arange(5.0, 12.0, 0.25):
        for lam in np.arange(0.05, 2.05, 0.05):
            eff_liq = m2.values * scale * (1 + gli.values * lam)
            eff_liq = np.clip(eff_liq, m2.values * scale * 0.3, None)
            ratio = d.values / eff_liq

            score = 0.0
            for idx, target_ratio, weight in anchor_targets:
                score += weight * (ratio[idx] - target_ratio) ** 2

            if score < best_score:
                best_score = score
                best_scale = scale
                best_lambda = lam

    rmse = np.sqrt(best_score / max(len(anchor_targets), 1))
    return round(best_scale, 2), round(best_lambda, 2), round(rmse, 3)


def run_howell_reformulated(debt_series, m2_series, gli_signal_chart, anchors):
    """Build GLI-calibrated debt/liquidity ratio.

    Args:
        debt_series: Quarterly AE total debt in $T (from Phase 1)
        m2_series: Quarterly US M2 in $T (from Phase 3)
        gli_signal_chart: List of {date, comp_z} from production signal cache
        anchors: Enriched anchor points from Phase 2
    """
    # Extract GLI z-score series from chart data
    gli_z = pd.Series(
        {pd.Timestamp(p["date"]): p.get("comp_z") for p in gli_signal_chart if p.get("comp_z") is not None},
        dtype=float).dropna().sort_index()

    if len(gli_z) < 20:
        return {"error": f"Only {len(gli_z)} GLI data points"}

    # Normalize all to quarterly
    debt_q = _normalize_qtr(debt_series)
    m2_q = _normalize_qtr(m2_series)
    gli_q = _normalize_qtr(gli_z.resample("QE").last().dropna())

    print(f"[HOWELL REF] Debt: {len(debt_q)} qtrs, M2: {len(m2_q)} qtrs, GLI: {len(gli_q)} qtrs")
    print(f"[HOWELL REF] Latest: Debt=${debt_q.iloc[-1]:.1f}T, M2=${m2_q.iloc[-1]:.1f}T, GLI_z={gli_q.iloc[-1]:.3f}")

    # Calibrate
    print("[HOWELL REF] Calibrating (scale, λ) against anchors...")
    scale, lam, rmse = calibrate_ratio(m2_q, gli_q, debt_q, anchors)
    print(f"[HOWELL REF] Best: scale={scale}, λ={lam}, anchor RMSE={rmse}")

    # Compute full series
    common = m2_q.index.intersection(gli_q.index).intersection(debt_q.index)
    m2 = m2_q.reindex(common)
    gli = gli_q.reindex(common).fillna(0)
    debt = debt_q.reindex(common)

    eff_liq = m2 * scale * (1 + gli * lam)
    eff_liq = eff_liq.clip(lower=m2 * scale * 0.3)
    ratio = debt / eff_liq

    # Current readings
    current_ratio = float(ratio.iloc[-1])
    current_gli = float(gli.iloc[-1])
    if current_ratio < 1.8:
        regime = "BUBBLE"
    elif current_ratio < 2.2:
        regime = "NEUTRAL"
    elif current_ratio < 2.7:
        regime = "STRESS"
    else:
        regime = "CRISIS"

    # Anchor comparison
    anchor_comparison = []
    for a in anchors:
        if a.get("ratio") is None:
            continue
        ad = pd.Timestamp(a.get("date_aligned", a["date"]))
        diffs = abs(common - ad)
        nearest_idx = diffs.argmin()
        if diffs[nearest_idx].days > 180:
            continue
        model_ratio = float(ratio.iloc[nearest_idx])
        stated = float(a["ratio"])
        error_pct = round((model_ratio - stated) / stated * 100, 1)
        anchor_comparison.append({
            "date": common[nearest_idx].strftime("%Y-%m"),
            "stated_ratio": stated,
            "model_ratio": round(model_ratio, 2),
            "error_pct": error_pct,
            "match": abs(error_pct) < 10,
        })

    # Chart data
    chart = []
    for d in common:
        chart.append({
            "date": d.strftime("%Y-%m-%d"),
            "ratio": round(float(ratio[d]), 2),
            "debt": round(float(debt[d]), 1),
            "eff_liq": round(float(eff_liq[d]), 1),
            "gli_z": round(float(gli[d]), 3),
        })

    n_match = sum(1 for a in anchor_comparison if a["match"])
    print(f"[HOWELL REF] Current: ratio={current_ratio:.2f}x ({regime}), {n_match}/{len(anchor_comparison)} anchors matched")

    return {
        "calibration": {
            "m2_scale": scale,
            "lambda": lam,
            "anchor_rmse": rmse,
        },
        "current": {
            "debt_T": round(float(debt.iloc[-1]), 1),
            "effective_liquidity_T": round(float(eff_liq.iloc[-1]), 1),
            "ratio": round(current_ratio, 2),
            "gli_z": round(current_gli, 3),
            "regime": regime,
        },
        "ratio_chart": chart,
        "anchor_comparison": anchor_comparison,
        "n_anchors_matched": n_match,
        "n_anchors_total": len(anchor_comparison),
    }
