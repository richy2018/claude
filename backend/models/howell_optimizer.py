"""Howell Liquidity — Phase 4 (Optimization) + Phase 5 (Validation).

Stepwise component selection + constrained regression to fit
candidate components to the implied liquidity series.
"""

import numpy as np
import pandas as pd
from scipy.optimize import nnls


def _fit_nnls(X, y, weights=None):
    """Non-negative least squares with optional confidence weighting."""
    if weights is not None:
        W = np.sqrt(np.array(weights))
        X_w = X * W[:, None]
        y_w = y * W
    else:
        X_w = X
        y_w = y
    try:
        w, _ = nnls(X_w, y_w)
    except Exception:
        w = np.zeros(X.shape[1])
    predicted = X @ w
    ss_res = float(np.sum((predicted - y) ** 2 * (weights if weights is not None else 1)))
    ss_tot = float(np.sum((y - y.mean()) ** 2 * (weights if weights is not None else 1)))
    r2 = 1 - ss_res / max(ss_tot, 1e-10)
    return w, round(r2, 4), predicted


def run_stepwise_selection(candidates_df, target, confidence_weights=None, max_components=6):
    """Greedy forward selection: add component that maximizes R² at each step."""
    if candidates_df.empty or len(target) < 10:
        return {"error": "Insufficient data"}

    # Align
    common = candidates_df.dropna().index.intersection(target.dropna().index)
    if len(common) < 10:
        return {"error": f"Only {len(common)} common dates"}

    X_full = candidates_df.reindex(common).fillna(0).values
    y = target.reindex(common).values
    cols = list(candidates_df.columns)
    cw = np.ones(len(common)) if confidence_weights is None else np.array(
        [confidence_weights.get(d, 1.0) for d in common])

    selected = []
    selected_idx = []
    results = []
    prev_r2 = 0

    for step in range(min(max_components, len(cols))):
        best_improvement = -1
        best_col = None
        best_col_idx = None

        remaining = [(i, c) for i, c in enumerate(cols) if i not in selected_idx]
        for idx, col_name in remaining:
            trial_idx = selected_idx + [idx]
            X_trial = X_full[:, trial_idx]
            _, r2, _ = _fit_nnls(X_trial, y, cw)
            improvement = r2 - prev_r2
            if improvement > best_improvement:
                best_improvement = improvement
                best_col = col_name
                best_col_idx = idx
                best_r2 = r2

        if best_improvement < 0.005 or best_col is None:
            break

        selected.append(best_col)
        selected_idx.append(best_col_idx)
        prev_r2 = best_r2

        # Get weights for current selection
        X_sel = X_full[:, selected_idx]
        weights, r2, _ = _fit_nnls(X_sel, y, cw)

        results.append({
            "step": step + 1,
            "component": best_col,
            "marginal_r2": round(best_improvement, 4),
            "cumulative_r2": round(best_r2, 4),
            "weight": round(float(weights[-1]), 4),
        })
        print(f"[HOWELL OPT] Step {step+1}: +{best_col} (ΔR²={best_improvement:.3f}, total R²={best_r2:.3f})")

    # Final fit with selected components
    if selected_idx:
        X_sel = X_full[:, selected_idx]
        final_weights, final_r2, predicted = _fit_nnls(X_sel, y, cw)
        weight_dict = {selected[i]: round(float(final_weights[i]), 4) for i in range(len(selected))}
    else:
        final_r2 = 0
        predicted = np.zeros(len(y))
        weight_dict = {}

    # M2 comparison (control)
    m2_r2 = None
    if "global_m2_proxy" in cols:
        m2_idx = cols.index("global_m2_proxy")
        _, m2_r2, _ = _fit_nnls(X_full[:, [m2_idx]], y, cw)
        print(f"[HOWELL OPT] M2 control R²: {m2_r2}")
    elif "us_m2" in cols:
        m2_idx = cols.index("us_m2")
        _, m2_r2, _ = _fit_nnls(X_full[:, [m2_idx]], y, cw)
        print(f"[HOWELL OPT] US M2 control R²: {m2_r2}")

    # Build liquidity_hat series
    liq_hat = pd.Series(predicted, index=common, name="liquidity_hat")

    return {
        "steps": results,
        "selected_components": selected,
        "final_weights": weight_dict,
        "final_r2": final_r2,
        "m2_comparison_r2": m2_r2,
        "liquidity_hat": liq_hat,
        "n_common_dates": len(common),
    }


def run_validation(liq_hat, debt_series, anchors, target):
    """Phase 5: Validate the reconstructed liquidity against Howell's properties."""
    checks = {}

    # Check 1: R² at anchor points
    if len(liq_hat) > 0 and len(target) > 0:
        common = liq_hat.index.intersection(target.dropna().index)
        if len(common) > 3:
            ss_res = float(((liq_hat.reindex(common) - target.reindex(common)) ** 2).sum())
            ss_tot = float(((target.reindex(common) - target.reindex(common).mean()) ** 2).sum())
            r2 = round(1 - ss_res / max(ss_tot, 1e-10), 3)
            checks["r2_at_anchors"] = {"value": r2, "pass": r2 > 0.90}

    # Check 2: Ratio inflection points
    if len(liq_hat) > 0 and len(debt_series) > 0:
        common = liq_hat.index.intersection(debt_series.index)
        ratio_hat = debt_series.reindex(common) / liq_hat.reindex(common)
        ratio_hat = ratio_hat.dropna()

        # 2008 peak
        r_2008 = ratio_hat["2007":"2009"]
        r_pre = ratio_hat["2005":"2007"]
        peak_2008 = len(r_2008) > 0 and len(r_pre) > 0 and float(r_2008.max()) > float(r_pre.mean())
        checks["inflection_2008_peak"] = {"value": peak_2008, "pass": peak_2008}

        # 2011 peak
        r_2011 = ratio_hat["2010":"2012"]
        r_2009 = ratio_hat["2009":"2010"]
        peak_2011 = len(r_2011) > 0 and len(r_2009) > 0 and float(r_2011.max()) > float(r_2009.min())
        checks["inflection_2011_peak"] = {"value": peak_2011, "pass": peak_2011}

        # 2021 trough
        r_2021 = ratio_hat["2020":"2022"]
        r_2019 = ratio_hat["2018":"2020"]
        trough_2021 = len(r_2021) > 0 and len(r_2019) > 0 and float(r_2021.min()) < float(r_2019.mean())
        checks["inflection_2021_trough"] = {"value": trough_2021, "pass": trough_2021}

        # Rising from 2022
        r_recent = ratio_hat["2022":]
        if len(r_recent) > 4:
            rising = float(r_recent.iloc[-1]) > float(r_recent.iloc[0])
            checks["inflection_rising_now"] = {"value": rising, "pass": rising}

    # Check 3: 65-month cycle
    if len(liq_hat) > 20:
        try:
            from scipy.signal import periodogram
            growth = liq_hat.pct_change(4).dropna()  # YoY quarterly
            if len(growth) > 20:
                freqs, power = periodogram(growth.values, fs=4)
                if len(freqs) > 1:
                    periods_months = (1 / freqs[1:]) * 12
                    dominant = float(periods_months[np.argmax(power[1:])])
                    checks["dominant_cycle_months"] = {
                        "value": round(dominant, 0),
                        "pass": 55 <= dominant <= 75
                    }
        except Exception as e:
            print(f"[HOWELL VAL] Cycle check error: {e}")

    # Check 4: Current level
    if len(liq_hat) > 0:
        current = float(liq_hat.iloc[-1])
        checks["current_level_T"] = {
            "value": round(current, 1),
            "pass": 100 <= current <= 300  # Wide range given our lower debt numerator
        }

    # Check 5: M2 divergence (passed in from optimization)

    n_pass = sum(1 for c in checks.values() if c.get("pass", False))
    n_total = len(checks)

    return {
        "checks": checks,
        "n_pass": n_pass,
        "n_total": n_total,
        "overall_pass": n_pass >= n_total * 0.6,
    }


def _normalize_to_quarter_end(s):
    """Normalize a Series index to quarter-end dates for consistent alignment."""
    if len(s) == 0:
        return s
    s = s.copy()
    s.index = pd.to_datetime(s.index).to_period('Q').to_timestamp('Q')
    # Remove duplicates (keep last)
    s = s[~s.index.duplicated(keep='last')]
    return s.sort_index()


def run_howell_phase3_5(debt_series, implied_liquidity, anchors, api_key=None):
    """Run Phases 3-5: fetch components, optimize, validate."""
    from .howell_components import fetch_liquidity_candidates

    print("[HOWELL] === Phase 3: Fetch Candidate Components ===")
    candidates, meta = fetch_liquidity_candidates(api_key)
    if candidates.empty:
        return {"error": "No candidate components fetched"}
    print(f"[HOWELL] {len(candidates.columns)} components, {len(candidates)} quarters")

    # Normalize all series to quarter-end dates for alignment
    implied_liquidity = _normalize_to_quarter_end(implied_liquidity)
    debt_series = _normalize_to_quarter_end(debt_series)
    for col in candidates.columns:
        candidates[col] = _normalize_to_quarter_end(candidates[col])
    candidates.index = pd.to_datetime(candidates.index).to_period('Q').to_timestamp('Q')
    candidates = candidates[~candidates.index.duplicated(keep='last')].sort_index()

    print(f"[HOWELL] After normalization: implied_liq {len(implied_liquidity)} pts "
          f"({implied_liquidity.index[0].strftime('%Y-%m')} to {implied_liquidity.index[-1].strftime('%Y-%m')}), "
          f"candidates {len(candidates)} pts "
          f"({candidates.index[0].strftime('%Y-%m')} to {candidates.index[-1].strftime('%Y-%m')})")

    # Check overlap
    common_check = implied_liquidity.index.intersection(candidates.dropna(how='all').index)
    print(f"[HOWELL] Common dates after normalization: {len(common_check)}")

    # Build confidence weights from anchors
    conf_weights = {}
    for a in anchors:
        d = pd.Timestamp(a["date_aligned"])
        conf_weights[d] = a.get("confidence_weight", 1.0)

    print("\n[HOWELL] === Phase 4: Optimization (LEVELS) ===")
    opt = run_stepwise_selection(candidates, implied_liquidity, max_components=6)
    if "error" in opt:
        return {"error": f"Optimization failed: {opt['error']}"}

    liq_hat = opt.pop("liquidity_hat")  # Remove Series before JSON

    # Build ratio_hat chart
    common = liq_hat.index.intersection(debt_series.index)
    ratio_hat = debt_series.reindex(common) / liq_hat.reindex(common)

    chart = []
    for d in common:
        chart.append({
            "date": d.strftime("%Y-%m-%d"),
            "liquidity_hat": round(float(liq_hat.get(d, 0)), 1),
            "ratio_hat": round(float(ratio_hat.get(d, 0)), 2),
            "debt": round(float(debt_series.get(d, 0)), 1),
        })

    # === Phase 4b: Growth Rate Decomposition ===
    print("\n[HOWELL] === Phase 4b: Optimization (YoY GROWTH RATES) ===")
    target_growth = implied_liquidity.pct_change(4).dropna()  # 4 quarters = YoY
    components_growth = candidates.pct_change(4).dropna()

    # Replace inf/nan from pct_change on near-zero values
    components_growth = components_growth.replace([np.inf, -np.inf], np.nan).fillna(0)
    target_growth = target_growth.replace([np.inf, -np.inf], np.nan).fillna(0)

    growth_opt = run_stepwise_selection(components_growth, target_growth, max_components=6)
    if "error" not in growth_opt:
        growth_liq_hat = growth_opt.pop("liquidity_hat", None)  # Remove Series
        print(f"[HOWELL] Growth-rate R²: {growth_opt['final_r2']} vs Level R²: {opt['final_r2']}")
        print(f"[HOWELL] Growth M2 R²: {growth_opt.get('m2_comparison_r2')} vs Level M2 R²: {opt.get('m2_comparison_r2')}")
    else:
        print(f"[HOWELL] Growth-rate optimization failed: {growth_opt.get('error')}")
        growth_opt = None

    print("\n[HOWELL] === Phase 5: Validation ===")
    val = run_validation(liq_hat, debt_series, anchors, implied_liquidity)
    val["checks"]["m2_divergence"] = {
        "optimized_r2": opt["final_r2"],
        "m2_r2": opt.get("m2_comparison_r2"),
        "pass": opt.get("m2_comparison_r2") is not None and opt["final_r2"] > (opt["m2_comparison_r2"] + 0.05),
    }

    result = {
        "optimization": opt,
        "growth_optimization": growth_opt,
        "validation": val,
        "ratio_chart": chart,
        "components_fetched": list(candidates.columns),
        "components_meta": meta,
    }
    return result
