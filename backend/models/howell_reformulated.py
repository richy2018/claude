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

    Searches scale 3.0-15.0, λ 0.01-5.0. Logs top 5 fits and GLI at key dates.
    Includes both ratio anchors AND liquidity level anchors.
    """
    common = m2_base.index.intersection(gli_z.index).intersection(debt.index)
    if len(common) < 10:
        return None, None, float('inf'), []

    m2 = m2_base.reindex(common)
    gli = gli_z.reindex(common).fillna(0)
    d = debt.reindex(common)

    # Debug: GLI values at key crisis dates
    for label, date_str in [("2008-09", "2008-09-01"), ("2011-06", "2011-06-01"), ("2021-06", "2021-06-01"), ("current", None)]:
        if date_str:
            target_d = pd.Timestamp(date_str)
            diffs = abs(common - target_d)
            idx = diffs.argmin()
            if diffs[idx].days < 180:
                print(f"[HOWELL CAL] GLI at {label}: {float(gli.iloc[idx]):.4f} (date={common[idx].strftime('%Y-%m')})")
        else:
            print(f"[HOWELL CAL] GLI at {label}: {float(gli.iloc[-1]):.4f}")

    # Prepare anchor targets — BOTH ratio and liquidity level anchors
    ratio_targets = []
    level_targets = []
    for a in anchors:
        ad = pd.Timestamp(a.get("date_aligned", a["date"]))
        diffs = abs(common - ad)
        nearest_idx = diffs.argmin()
        if diffs[nearest_idx].days > 180:
            continue
        weight = 1.0 if a.get("confidence") == "stated" else 0.5

        if a.get("ratio") is not None:
            ratio_targets.append((nearest_idx, float(a["ratio"]), weight))
        if a.get("liquidity") is not None:
            level_targets.append((nearest_idx, float(a["liquidity"]), weight))

    if len(ratio_targets) + len(level_targets) < 2:
        return 8.5, 0.5, float('inf'), []

    # Wider grid search
    top_fits = []
    for scale in np.arange(3.0, 15.25, 0.25):
        for lam in np.arange(0.01, 5.01, 0.05):
            eff_liq = m2.values * scale * (1 + gli.values * lam)
            eff_liq = np.clip(eff_liq, m2.values * scale * 0.2, None)
            ratio = d.values / eff_liq

            score = 0.0
            for idx, target_ratio, weight in ratio_targets:
                score += weight * (ratio[idx] - target_ratio) ** 2
            # Level targets: compare effective liquidity to stated liquidity
            for idx, target_level, weight in level_targets:
                # Normalize level error to ratio-scale (divide by ~100 to make comparable)
                level_error = (eff_liq[idx] - target_level) / 100
                score += weight * level_error ** 2

            top_fits.append((score, scale, lam))

    top_fits.sort(key=lambda x: x[0])
    best_score, best_scale, best_lambda = top_fits[0]

    print(f"[HOWELL CAL] Top 5 fits:")
    for i, (s, sc, la) in enumerate(top_fits[:5]):
        print(f"[HOWELL CAL]   #{i+1}: scale={sc:.2f}, λ={la:.2f}, score={s:.4f}")

    rmse = np.sqrt(best_score / max(len(ratio_targets) + len(level_targets), 1))
    return round(best_scale, 2), round(best_lambda, 2), round(rmse, 3), top_fits[:5]


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
    scale, lam, rmse, top_fits = calibrate_ratio(m2_q, gli_q, debt_q, anchors)
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

    # Anchor comparison — ALL anchors (ratio AND level)
    anchor_comparison = []
    for a in anchors:
        ad = pd.Timestamp(a.get("date_aligned", a["date"]))
        diffs = abs(common - ad)
        nearest_idx = diffs.argmin()
        if diffs[nearest_idx].days > 180:
            continue
        model_ratio_val = float(ratio.iloc[nearest_idx])
        model_liq_val = float(eff_liq.iloc[nearest_idx])

        entry = {
            "date": common[nearest_idx].strftime("%Y-%m"),
            "confidence": a.get("confidence", ""),
            "model_ratio": round(model_ratio_val, 2),
            "model_liquidity": round(model_liq_val, 1),
        }

        if a.get("ratio") is not None:
            stated = float(a["ratio"])
            error_pct = round((model_ratio_val - stated) / stated * 100, 1)
            entry["stated_ratio"] = stated
            entry["ratio_error_pct"] = error_pct
            entry["match"] = abs(error_pct) < 10
            entry["type"] = "ratio"
        elif a.get("liquidity") is not None:
            stated_liq = float(a["liquidity"])
            error_pct = round((model_liq_val - stated_liq) / stated_liq * 100, 1)
            entry["stated_liquidity"] = stated_liq
            entry["liq_error_pct"] = error_pct
            entry["match"] = abs(error_pct) < 15  # Wider tolerance for level
            entry["type"] = "level"
        else:
            continue

        anchor_comparison.append(entry)

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
