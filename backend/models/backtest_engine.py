"""Composite signal backtest engine — automated sweep across all configurations."""

import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from scipy.optimize import minimize


# Signal transformation functions
def _signal_level(comp):
    return comp

def _signal_momentum(comp, months=1):
    return comp.diff(months)

def _signal_acceleration(comp):
    return comp.diff(3).diff(3)

def _signal_zscore(comp, window=12):
    m = comp.rolling(window, min_periods=max(6, window // 2)).mean()
    s = comp.rolling(window, min_periods=max(6, window // 2)).std().replace(0, np.nan)
    return ((comp - m) / s).clip(-3, 3)

def _signal_percentile(comp, window=60):
    return comp.rolling(window, min_periods=12).apply(
        lambda x: sp_stats.percentileofscore(x, x.iloc[-1]) if len(x) > 1 else 50, raw=False)

SIGNAL_TRANSFORMS = {
    "level": ("Level", lambda c: _signal_level(c)),
    "mom1": ("Mom 1M", lambda c: _signal_momentum(c, 1)),
    "mom3": ("Mom 3M", lambda c: _signal_momentum(c, 3)),
    "mom6": ("Mom 6M", lambda c: _signal_momentum(c, 6)),
    "accel": ("Accel", lambda c: _signal_acceleration(c)),
    "z12": ("Z-Score 12M", lambda c: _signal_zscore(c, 12)),
    "z36": ("Z-Score 36M", lambda c: _signal_zscore(c, 36)),
    "pctl60": ("Pctl 60M", lambda c: _signal_percentile(c, 60)),
}

REGIME_FILTERS = ["all", "below200", "below50", "vix20", "vix25", "dd5", "dd10", "rates_up", "rates_down"]
REGIME_LABELS = {
    "all": "All", "below200": "<200dma", "below50": "<50dma",
    "vix20": "VIX>20", "vix25": "VIX>25", "dd5": "DD>5%", "dd10": "DD>10%",
    "rates_up": "Rates Up", "rates_down": "Rates Down",
}
OPT_OBJECTIVES = ["spread", "monotonicity", "corr"]
COMP_KEYS = ["quantity_signal", "rate_signal", "spread_signal", "curve_signal", "m2_signal"]
COMP_LABELS = {"quantity_signal": "Qty", "rate_signal": "Rates", "spread_signal": "Credit",
               "curve_signal": "Curve", "m2_signal": "M2", "dollar_stress_signal": "Dollar"}
DEFAULT_W = [0.25, 0.25, 0.20, 0.15, 0.15]

# Production signal configs (fixed weights from optimization)
# NOTE: Weights should be re-derived after data source changes by calling
#       GET /api/gli/reoptimize?models=4f,3fb,2f after a REFRESH.
PRODUCTION_MODELS = {
    "4f": {
        "keys": ["quantity_signal", "spread_signal", "m2_signal", "dollar_stress_signal"],
        "weights": {"quantity_signal": 0.21, "spread_signal": 0.14, "m2_signal": 0.30, "dollar_stress_signal": 0.35},
        "label": "4F (Qty + Credit + M2 + Dollar)",
        "signal_type": "mom6",
        "description": "More stable across regimes. Recommended for allocation decisions.",
    },
    "3fa": {
        "keys": ["quantity_signal", "spread_signal", "m2_signal"],
        "weights": {"quantity_signal": 0.26, "spread_signal": 0.30, "m2_signal": 0.44},
        "label": "3F-A (Qty + Credit + M2)",
        "signal_type": "mom6",
        "description": "Production model. Strongest MC correlation and lowest p-value.",
    },
    "3fb": {
        "keys": ["spread_signal", "m2_signal", "dollar_stress_signal"],
        "weights": {"spread_signal": 0.30, "m2_signal": 0.30, "dollar_stress_signal": 0.40},
        "label": "3F-B (Credit + M2 + Dollar)",
        "signal_type": "mom6",
        "description": "Three-factor model focused on credit, money supply, and dollar stress.",
    },
    "2f": {
        "keys": ["spread_signal", "dollar_stress_signal"],
        "weights": {"spread_signal": 0.42, "dollar_stress_signal": 0.58},
        "label": "2F (Credit + Dollar)",
        "signal_type": "mom6",
        "description": "Simpler, more responsive. Shows the two core drivers directly.",
    },
}

# TODO: After 3-factor optimization and Phase 3 (Dollar Stress), revisit
# Curve as a conditional overlay that only activates during hiking cycles
# (Rates Up regime). Economic rationale: curve inversion signals policy
# error only when Fed is actively tightening.


def compute_production_signal(ratio_series, spy_monthly, model="3fa"):
    """Compute the production composite signal using fixed optimized weights."""
    cfg = PRODUCTION_MODELS.get(model, PRODUCTION_MODELS["3fa"])
    sig_fn = SIGNAL_TRANSFORMS.get(cfg["signal_type"], SIGNAL_TRANSFORMS["mom6"])[1]

    # Extract components
    all_keys = list(set(COMP_KEYS + ["dollar_stress_signal"]))
    components = {}
    for key in all_keys:
        s = pd.Series(
            {pd.Timestamp(r["date"]): r.get(key) for r in ratio_series},
            dtype=float).dropna().sort_index()
        if len(s) > 0:
            components[key] = s

    # Check required keys
    missing = [k for k in cfg["keys"] if k not in components]
    if missing:
        return {"error": f"Missing components: {missing}. Run REFRESH first."}

    # Log component date ranges for debugging
    for k in cfg["keys"]:
        s = components[k]
        valid = s.dropna()
        print(f"[PROD] {k}: {len(valid)} obs, {valid.index[0].strftime('%Y-%m')} to {valid.index[-1].strftime('%Y-%m')}, latest={valid.iloc[-1]:.3f}")

    # Build composite with fixed weights — use intersection of all component dates
    date_sets = [set(components[k].dropna().index) for k in cfg["keys"]]
    common_dates = sorted(set.intersection(*date_sets)) if date_sets else []
    if len(common_dates) < 30:
        return {"error": f"Only {len(common_dates)} common dates across components"}
    base_idx = pd.DatetimeIndex(common_dates)
    comp = pd.Series(0.0, index=base_idx)
    for k in cfg["keys"]:
        comp += cfg["weights"][k] * components[k].reindex(base_idx, method="ffill").fillna(0)
    print(f"[PROD] Composite: {len(comp)} points, {base_idx[0].strftime('%Y-%m')} to {base_idx[-1].strftime('%Y-%m')}")

    # Apply signal transformation
    signal_raw = sig_fn(comp)
    signal = signal_raw.dropna()
    print(f"[PROD] Pre-transform composite: {len(comp)} pts, last={comp.index[-1].strftime('%Y-%m')}")
    print(f"[PROD] Post-transform ({cfg['signal_type']}): {len(signal_raw)} total, {signal_raw.isna().sum()} NaN, {len(signal)} valid")
    print(f"[PROD] Signal range: {signal.index[0].strftime('%Y-%m')} to {signal.index[-1].strftime('%Y-%m')}, last value={signal.iloc[-1]:.4f}")

    # Print last 10 values of each component for debugging
    for k in cfg["keys"]:
        s = components[k].dropna()
        tail = s.tail(10)
        tail_str = ', '.join(f"{d.strftime('%Y-%m')}={v:.3f}" for d, v in tail.items())
        print(f"[PROD] {k} last 10: {tail_str}")

    if len(signal) < 30:
        return {"error": f"Not enough data after transform: {len(signal)} points"}

    # Current reading — BOTH level and momentum
    # Momentum (Mom 6M)
    mom_latest = float(signal.iloc[-1])
    mom_pct = float(sp_stats.percentileofscore(signal.values, mom_latest))
    mom_q = 1 if mom_pct < 20 else 2 if mom_pct < 40 else 3 if mom_pct < 60 else 4 if mom_pct < 80 else 5

    # Level (raw composite)
    level_latest = float(comp.iloc[-1])
    level_pct = float(sp_stats.percentileofscore(comp.values, level_latest))
    level_q = 1 if level_pct < 20 else 2 if level_pct < 40 else 3 if level_pct < 60 else 4 if level_pct < 80 else 5

    q_labels = {1: "DEEPLY LOOSE", 2: "LOOSE", 3: "NEUTRAL", 4: "TIGHT", 5: "DEEPLY TIGHT"}
    mom_labels = {1: "LOOSENING FAST", 2: "LOOSENING", 3: "NEUTRAL", 4: "TIGHTENING", 5: "TIGHTENING FAST"}

    # Combined implication based on level percentile + momentum direction
    level_loose = level_pct < 25
    level_tight = level_pct > 75
    mom_loosening = mom_latest < 0
    mom_tightening = mom_latest > 0

    if level_loose and mom_loosening:
        implication = "Loose and loosening — most favorable regime for risk"
    elif level_loose and mom_tightening:
        implication = "Loose but tightening — favorable but monitor for deterioration"
    elif level_tight and mom_loosening:
        implication = "Tight but loosening — worst may be behind, watch for confirmation"
    elif level_tight and mom_tightening:
        implication = "Tight and tightening — defensive positioning recommended"
    elif not level_loose and not level_tight and mom_loosening:
        implication = "Neutral and loosening — conditions improving"
    elif not level_loose and not level_tight and mom_tightening:
        implication = "Neutral and tightening — caution warranted"
    else:
        implication = "Neutral — no strong directional view"

    # SPY 6M forward (shifted back for overlay)
    spy_6m_fwd = spy_monthly.pct_change(6).shift(-6) * 100

    # Chart data: plot raw composite LEVEL (good visual range)
    # Signal reading uses Mom 6M but chart shows the level for visual clarity
    def _z(s):
        m = s.rolling(36, min_periods=12).mean()
        st = s.rolling(36, min_periods=12).std().replace(0, np.nan)
        return ((s - m) / st).clip(-3, 3)

    # Z-score both the composite level and SPY fwd for the chart
    comp_z = _z(comp)
    fwd_aligned = spy_6m_fwd.reindex(comp.index)
    fwd_z = _z(fwd_aligned.dropna()).reindex(comp.index)
    roll_corr = comp.rolling(36, min_periods=12).corr(fwd_aligned)

    # Quintile breakpoints
    try:
        quintiles = pd.qcut(signal, 5, labels=False, duplicates='drop')
    except Exception:
        quintiles = pd.Series(2, index=signal.index)

    # Quintile context for current quintile
    r6 = spy_monthly.pct_change(6).shift(-6) * 100
    r12 = spy_monthly.pct_change(12).shift(-12) * 100
    q_context = []
    q_names = ["Q1 Most Loose", "Q2 Loose", "Q3 Neutral", "Q4 Tight", "Q5 Most Tight"]
    for qi in range(5):
        qm = quintiles == qi
        dts = signal[qm].index
        r6v = r6.reindex(dts).dropna()
        r12v = r12.reindex(dts).dropna()
        q_context.append({
            "quintile": q_names[qi] if qi < len(q_names) else f"Q{qi+1}",
            "avg_6m": round(float(r6v.mean()), 1) if len(r6v) > 3 else None,
            "avg_12m": round(float(r12v.mean()), 1) if len(r12v) > 3 else None,
            "hit_6m": round(float((r6v > 0).mean()) * 100, 0) if len(r6v) > 3 else None,
            "is_current": qi == (mom_q - 1),
        })

    # Time series for chart (last 240 months) — uses composite LEVEL (z-scored)
    chart = []
    for d in comp.index[-240:]:
        entry = {"date": d.strftime("%Y-%m-%d")}
        entry["comp_z"] = float(comp_z[d]) if pd.notna(comp_z.get(d)) else None
        entry["spy_fwd_z"] = float(-fwd_z[d]) if pd.notna(fwd_z.get(d)) else None
        entry["roll_corr"] = float(roll_corr[d]) if pd.notna(roll_corr.get(d)) else None
        qv = quintiles.get(d) if d in quintiles.index else None
        entry["q"] = int(qv) if qv is not None and not np.isnan(qv) else None
        chart.append(entry)

    # Component readings
    comp_readings = []
    for k in cfg["keys"]:
        if k not in components:
            continue
        s = components[k]
        curr = float(s.iloc[-1]) if len(s) > 0 else None
        prev_3m = float(s.iloc[-4]) if len(s) > 3 else curr
        trend = "rising" if curr is not None and prev_3m is not None and curr > prev_3m + 0.02 else \
                "falling" if curr is not None and prev_3m is not None and curr < prev_3m - 0.02 else "flat"
        direction = "tightening" if curr is not None and curr > 0 else "loosening"
        comp_readings.append({
            "key": k, "label": COMP_LABELS.get(k, k),
            "weight": cfg["weights"][k],
            "value": round(curr, 3) if curr is not None else None,
            "trend": trend, "direction": direction,
        })

    # Dominant driver
    dominant = max(comp_readings, key=lambda c: abs(c["value"] or 0) * c["weight"]) if comp_readings else None

    return {
        "model": model,
        "model_label": cfg["label"],
        "model_description": cfg["description"],
        "signal_type": cfg["signal_type"],
        "current": {
            "level_value": round(level_latest, 3),
            "level_percentile": round(level_pct, 1),
            "level_quintile": level_q,
            "level_label": q_labels.get(level_q, ""),
            "mom_value": round(mom_latest, 3),
            "mom_percentile": round(mom_pct, 1),
            "mom_quintile": mom_q,
            "mom_label": mom_labels.get(mom_q, ""),
            "implication": implication,
            "date": comp.index[-1].strftime("%Y-%m-%d"),
        },
        "weights": cfg["weights"],
        "chart": chart,
        "components": comp_readings,
        "dominant_driver": dominant,
        "quintile_context": q_context,
    }

MODEL_CONFIGS = {
    "2f": {"keys": ["spread_signal", "dollar_stress_signal"],
           "label": "2F (Credit+Dollar)", "default_w": [0.60, 0.40], "bounds": [(0.20, 0.80)]},
    "3fa": {"keys": ["quantity_signal", "spread_signal", "m2_signal"],
            "label": "3F-A (Qty+Credit+M2)", "default_w": [0.25, 0.45, 0.30], "bounds": [(0.10, 0.70)]},
    "3fb": {"keys": ["spread_signal", "m2_signal", "dollar_stress_signal"],
            "label": "3F-B (Credit+M2+Dollar)", "default_w": [0.40, 0.30, 0.30], "bounds": [(0.10, 0.60)]},
    "4f": {"keys": ["quantity_signal", "spread_signal", "m2_signal", "dollar_stress_signal"],
           "label": "4F (Qty+Credit+M2+Dollar)", "default_w": [0.20, 0.35, 0.25, 0.20], "bounds": [(0.05, 0.50)]},
    "5f": {"keys": COMP_KEYS, "label": "5F (All)", "default_w": DEFAULT_W, "bounds": [(0.05, 0.50)]},
}


def run_sweep(ratio_series, spy_monthly, fred_data=None, vix_data=None, model="3fa", n_factors=None):
    """Run full sweep. model selects component config from MODEL_CONFIGS."""
    # Support legacy n_factors parameter
    if n_factors is not None and model in ("3fa", None):
        model = "3fa" if n_factors == 3 else "5f"

    cfg = MODEL_CONFIGS.get(model, MODEL_CONFIGS["3fa"])
    use_keys = cfg["keys"]
    use_default_w = cfg["default_w"]
    w_bounds = cfg["bounds"] * len(use_keys) if len(cfg["bounds"]) == 1 else cfg["bounds"]

    # Extract ALL components (including dollar_stress_signal if present)
    all_keys = list(set(COMP_KEYS + ["dollar_stress_signal"]))
    comp = pd.Series(
        {pd.Timestamp(r["date"]): r.get("composite_signal") for r in ratio_series},
        dtype=float).dropna().sort_index()
    components = {}
    for key in all_keys:
        s = pd.Series(
            {pd.Timestamp(r["date"]): r.get(key) for r in ratio_series},
            dtype=float).dropna().sort_index()
        if len(s) > 0:
            components[key] = s

    # Validate required keys exist
    missing_keys = [k for k in use_keys if k not in components]
    if missing_keys:
        return {"error": f"Components not found: {missing_keys}. Run REFRESH first.", "leaderboard": []}

    # Find common start date where ALL selected components have data (truncation)
    start_dates = [components[k].first_valid_index() for k in use_keys if k in components]
    if start_dates:
        trunc_date = max(start_dates)
        print(f"[SWEEP] Truncation date: {trunc_date.strftime('%Y-%m')} (all {model} components available)")
    else:
        trunc_date = comp.index[0]

    # Build composite from selected components only (truncated to common window)
    comp = comp[comp.index >= trunc_date]
    comp_custom = pd.Series(0.0, index=comp.index)
    for i, k in enumerate(use_keys):
        if k in components:
            comp_custom += use_default_w[i] * components[k].reindex(comp.index, method="ffill").fillna(0)
    comp = comp_custom

    # Forward returns
    r3 = spy_monthly.pct_change(3).shift(-3) * 100
    r6 = spy_monthly.pct_change(6).shift(-6) * 100
    r12 = spy_monthly.pct_change(12).shift(-12) * 100

    # Pre-compute regime filter masks
    filter_masks = _precompute_filters(comp.index, spy_monthly, fred_data, vix_data)

    # Sweep all configs (optimize only top configs for speed)
    leaderboard = []
    for sig_key, (sig_name, sig_fn) in SIGNAL_TRANSFORMS.items():
        signal = sig_fn(comp).dropna()
        if len(signal) < 30:
            continue

        for filt_key in REGIME_FILTERS:
            mask = filter_masks.get(filt_key, pd.Series(True, index=comp.index))
            common = signal.index.intersection(r6.dropna().index)
            if len(common) < 30:
                continue

            sig_c = signal.reindex(common)
            filt_mask = mask.reindex(common, fill_value=True)
            n_filtered = int(filt_mask.sum())
            if n_filtered < 60:  # Hard floor: N < 60 is not statistically meaningful
                continue

            # Correlations (on filtered data)
            corr3 = _corr_filtered(sig_c, r3, filt_mask)
            corr6 = _corr_filtered(sig_c, r6, filt_mask)
            corr12 = _corr_filtered(sig_c, r12, filt_mask)

            # Quintile stats
            try:
                quintiles = pd.qcut(sig_c, 5, labels=False, duplicates='drop')
            except Exception:
                continue

            q_avgs = []
            q_avgs_12m = []
            for q in range(5):
                qm = (quintiles == q) & filt_mask
                vals6 = r6.reindex(common)[qm].dropna()
                q_avgs.append(float(vals6.mean()) if len(vals6) > 2 else None)
                # 12M returns for quintile
                common_12 = signal.index.intersection(r12.dropna().index)
                sig_12 = signal.reindex(common_12)
                try:
                    q12 = pd.qcut(sig_12, 5, labels=False, duplicates='drop')
                    qm12 = (q12 == q) & mask.reindex(common_12, fill_value=True)
                    vals12 = r12.reindex(common_12)[qm12].dropna()
                    q_avgs_12m.append(float(vals12.mean()) if len(vals12) > 2 else None)
                except Exception:
                    q_avgs_12m.append(None)

            spread = (q_avgs[0] - q_avgs[4]) if q_avgs[0] is not None and q_avgs[4] is not None else None
            valid_q = [x for x in q_avgs if x is not None]
            # Monotonicity: negative Spearman = Q1 has highest return (good). Negate so positive = good.
            mono = -float(sp_stats.spearmanr(range(len(valid_q)), valid_q)[0]) if len(valid_q) >= 4 else None

            # OOS correlation WITH regime filter applied
            mid = len(common) // 2
            oos_mask = filt_mask.reindex(common[mid:], fill_value=True)
            oos_sig = sig_c.iloc[mid:][oos_mask]
            oos_ret = r6.reindex(common[mid:])[oos_mask]
            oos_common = oos_sig.dropna().index.intersection(oos_ret.dropna().index)
            oos_corr = round(float(np.corrcoef(oos_sig.reindex(oos_common), oos_ret.reindex(oos_common))[0, 1]), 4) if len(oos_common) >= 15 else None

            # 12M correlation (wider date range)
            common_12m = signal.index.intersection(r12.dropna().index)
            corr12 = _corr_filtered(signal.reindex(common_12m), r12, mask.reindex(common_12m, fill_value=True)) if len(common_12m) > 20 else None

            # Confidence interval: CI = r ± 1.96 / sqrt(N - 3)
            ci = round(1.96 / np.sqrt(max(n_filtered - 3, 4)), 3) if n_filtered > 10 else None

            # Per-quintile N warning
            q_ns = [int(((quintiles == q) & filt_mask).sum()) for q in range(5)]
            small_quintile = any(n < 10 for n in q_ns)

            for obj in OPT_OBJECTIVES:
                leaderboard.append({
                    "signal": sig_key, "signal_name": sig_name,
                    "filter": filt_key, "filter_name": REGIME_LABELS.get(filt_key, filt_key),
                    "objective": obj, "n": n_filtered,
                    "corr_3m": corr3, "corr_6m": corr6, "corr_12m": corr12,
                    "oos_corr_6m": oos_corr, "ci_95": ci,
                    "spread_6m": round(spread, 2) if spread is not None else None,
                    "monotonicity": round(mono, 3) if mono is not None else None,
                    "q_avgs": [round(x, 2) if x is not None else None for x in q_avgs],
                    "q_ns": q_ns, "small_quintile": small_quintile,
                    "weights": dict(zip(COMP_KEYS, DEFAULT_W)),
                })

    # Sort by OOS 6M correlation (most negative = best), tie-break by higher N
    leaderboard.sort(key=lambda x: (x.get("oos_corr_6m") or 0, -x.get("n", 0)))

    # Deduplicate: keep best objective per signal+filter combo
    seen = set()
    deduped = []
    for entry in leaderboard:
        k = (entry["signal"], entry["filter"])
        if k not in seen:
            seen.add(k)
            deduped.append(entry)

    # Take top 30
    top = deduped[:30]

    # Fixed-weight walk-forward for top 10 configs
    for entry in top[:10]:
        sig_fn = SIGNAL_TRANSFORMS.get(entry["signal"], SIGNAL_TRANSFORMS["level"])[1]
        filt = filter_masks.get(entry["filter"], pd.Series(True, index=comp.index))

        # First optimize on full sample to get fixed weights
        full_common = sig_fn(comp).dropna().index.intersection(r6.dropna().index)
        if len(full_common) < 30:
            entry["fw_fixed_mean"] = None
            continue

        full_filt = filt.reindex(full_common, fill_value=True)
        fixed_w = _optimize_weights(use_keys, components, full_common, r6, sig_fn, full_filt,
                                    init_weights=use_default_w, bounds=w_bounds)
        fixed_w_list = [fixed_w.get(k, 1.0/len(use_keys)) for k in use_keys]

        # Walk-forward with fixed weights (Approach B)
        all_dates = sorted(full_common)
        fw_oos_vals = []
        wt = 48; ws = 24
        for start in range(0, len(all_dates) - wt - ws, 24):
            test_dates = all_dates[start + wt:start + wt + ws]
            if len(test_dates) < 10:
                break
            test_idx = pd.DatetimeIndex(test_dates)
            # Build composite with FIXED weights
            test_comp = pd.Series(0.0, index=test_idx)
            for i, k in enumerate(use_keys):
                if k in components:
                    test_comp += fixed_w_list[i] * components[k].reindex(test_idx, method="ffill").fillna(0)
            test_sig = sig_fn(test_comp).dropna()
            test_filt = filt.reindex(test_idx, fill_value=True).reindex(test_sig.index, fill_value=True)
            oos_val = _corr_filtered(test_sig, r6, test_filt)
            if oos_val is not None:
                fw_oos_vals.append(oos_val)

        if fw_oos_vals:
            entry["fw_fixed_mean"] = round(float(np.mean(fw_oos_vals)), 4)
            entry["fw_fixed_std"] = round(float(np.std(fw_oos_vals)), 4)
            entry["fw_fixed_wrong"] = sum(1 for v in fw_oos_vals if v > 0)
            entry["fw_fixed_n"] = len(fw_oos_vals)
            entry["fw_fixed_weights"] = fixed_w
        else:
            entry["fw_fixed_mean"] = None

    # Re-sort top by fixed-weight FW mean (most negative = best)
    top.sort(key=lambda x: x.get("fw_fixed_mean") or 0)

    # Auto-summary
    best = top[0] if top else None
    if best is not None and best.get("oos_corr_6m") is not None:
        oos = best["oos_corr_6m"]
        if oos < -0.10:
            summary = f"Signal: USABLE — {best['signal_name']} + {best['filter_name']} shows {oos:.3f} OOS correlation at 6M with {best['n']} months"
        elif oos < -0.05:
            summary = f"Signal: WEAK — best config ({best['signal_name']} + {best['filter_name']}) shows marginal {oos:.3f} OOS correlation, use with caution"
        else:
            summary = "Signal: NO EDGE — composite liquidity signal does not predict equity returns in any tested configuration"
    else:
        summary = "Signal: INSUFFICIENT DATA for conclusive assessment"

    # Component diagnostics
    comp_diag = {}
    for key in COMP_KEYS:
        if key not in components:
            continue
        cs = components[key].reindex(comp.index.intersection(r6.dropna().index))
        c3 = _corr_simple(cs, r3)
        c6 = _corr_simple(cs, r6)
        c12 = _corr_simple(cs, r12)
        # Label: all negative = SIGNAL CARRIER, all near zero = NO SIGNAL, any positive = HARMFUL
        vals = [v for v in [c3, c6, c12] if v is not None]
        if vals and all(v < -0.05 for v in vals):
            label = "SIGNAL CARRIER"
        elif vals and any(v > 0.05 for v in vals):
            label = "HARMFUL"
        else:
            label = "NO SIGNAL"
        comp_diag[key] = {"corr_3m": c3, "corr_6m": c6, "corr_12m": c12, "label": label}

    # Marginal contribution
    marginal = {}
    base_corr = _corr_simple(comp.reindex(r6.dropna().index), r6)
    for key in COMP_KEYS:
        if key not in components:
            continue
        # Build composite WITHOUT this component
        wo = pd.Series(0.0, index=comp.index)
        remaining_w = sum(DEFAULT_W[i] for i, k in enumerate(COMP_KEYS) if k != key)
        for i, k in enumerate(COMP_KEYS):
            if k == key or k not in components:
                continue
            wo += (DEFAULT_W[i] / remaining_w) * components[k].reindex(comp.index, method="ffill").fillna(0)
        wo_corr = _corr_simple(wo.reindex(r6.dropna().index), r6)
        marginal[key] = {
            "with": base_corr, "without": wo_corr,
            "harmful": wo_corr is not None and base_corr is not None and wo_corr < base_corr,
        }

    # Drawdown analysis
    drawdowns = _analyze_drawdowns(spy_monthly, comp)

    # Current signal reading (using best unconditional config's transform)
    current_reading = None
    best_uncond = next((x for x in top if x["filter"] == "all"), None)
    if best_uncond:
        best_sig_fn = SIGNAL_TRANSFORMS.get(best_uncond["signal"], SIGNAL_TRANSFORMS["level"])[1]
        best_signal = best_sig_fn(comp).dropna()
        if len(best_signal) > 0:
            latest_val = float(best_signal.iloc[-1])
            try:
                pct = float(sp_stats.percentileofscore(best_signal.values, latest_val))
            except Exception:
                pct = 50
            # Quintile
            q = 1 if pct < 20 else 2 if pct < 40 else 3 if pct < 60 else 4 if pct < 80 else 5
            imp = ("Deeply loose → lean into risk" if q <= 1 else
                   "Loose → favorable for risk" if q <= 2 else
                   "Neutral → no strong directional view" if q <= 3 else
                   "Tight → reduce risk exposure" if q <= 4 else
                   "Deeply tight → get defensive")
            current_reading = {
                "signal_name": best_uncond["signal_name"],
                "value": round(latest_val, 4),
                "percentile": round(pct, 1),
                "quintile": q,
                "date": best_signal.index[-1].strftime("%Y-%m-%d"),
                "implication": imp,
            }

    return {
        "leaderboard": top,
        "summary": summary,
        "total_configs": len(leaderboard),
        "n_factors": n_factors,
        "component_keys": use_keys,
        "component_diagnostics": comp_diag,
        "marginal_contribution": marginal,
        "drawdown_analysis": drawdowns,
        "current_reading": current_reading,
    }


def run_detail(ratio_series, spy_monthly, signal_type, regime_filter, components_cache=None,
               fred_data=None, vix_data=None, model="3fa", n_factors=None):
    """Run detailed analysis for a single selected config with weight optimization."""
    if n_factors is not None and model in ("3fa", None):
        model = "3fa" if n_factors == 3 else "5f"
    cfg = MODEL_CONFIGS.get(model, MODEL_CONFIGS["3fa"])
    use_keys = cfg["keys"]
    use_default_w = cfg["default_w"]
    w_bounds = cfg["bounds"] * len(use_keys) if len(cfg["bounds"]) == 1 else cfg["bounds"]

    components = components_cache or {}
    if not components:
        all_keys = list(set(COMP_KEYS + ["dollar_stress_signal"]))
        for key in all_keys:
            s = pd.Series({pd.Timestamp(r["date"]): r.get(key) for r in ratio_series}, dtype=float).dropna().sort_index()
            if len(s) > 0:
                components[key] = s

    # Build composite from selected components
    base_idx = next(iter(components.values())).index if components else pd.DatetimeIndex([])
    comp = pd.Series(0.0, index=base_idx)
    for i, k in enumerate(use_keys):
        if k in components:
            comp += use_default_w[i] * components[k].reindex(base_idx, method="ffill").fillna(0)

    sig_fn = SIGNAL_TRANSFORMS.get(signal_type, SIGNAL_TRANSFORMS["level"])[1]
    signal = sig_fn(comp).dropna()

    r3 = spy_monthly.pct_change(3).shift(-3) * 100
    r6 = spy_monthly.pct_change(6).shift(-6) * 100
    r12 = spy_monthly.pct_change(12).shift(-12) * 100

    common = signal.index.intersection(r6.dropna().index)
    if len(common) < 30:
        return {"error": "Not enough data"}

    filter_masks = _precompute_filters(comp.index, spy_monthly, fred_data, vix_data)
    filt = filter_masks.get(regime_filter, pd.Series(True, index=comp.index)).reindex(common, fill_value=True)

    sig_c = signal.reindex(common)

    # Optimize weights
    opt_w = _optimize_weights(use_keys, components, common, r6, sig_fn, filt,
                              init_weights=use_default_w, bounds=w_bounds)

    # Quintile table with hit rates
    try:
        quintiles = pd.qcut(sig_c, 5, labels=False, duplicates='drop')
    except Exception:
        quintiles = pd.Series(0, index=common)

    labels = ["Q1 Most Loose", "Q2 Loose", "Q3 Neutral", "Q4 Tight", "Q5 Most Tight"]
    regime_table = []
    for q in range(min(5, quintiles.max() + 1)):
        qm = (quintiles == q) & filt
        dts = sig_c[qm].index
        def _a(r): v = r.reindex(dts).dropna(); return round(float(v.mean()), 2) if len(v) > 2 else None
        def _h(r): v = r.reindex(dts).dropna(); return round(float((v > 0).mean()) * 100, 1) if len(v) > 2 else None
        regime_table.append({
            "quintile": labels[q] if q < len(labels) else f"Q{q+1}",
            "count": int(qm.sum()),
            "avg_3m": _a(r3), "avg_6m": _a(r6), "avg_12m": _a(r12),
            "hit_3m": _h(r3), "hit_6m": _h(r6),
        })

    # Time series chart data
    spy_cum = ((1 + spy_monthly.pct_change().fillna(0)).cumprod())
    ts = []
    for d in sig_c.index[-240:]:
        entry = {"date": d.strftime("%Y-%m-%d"), "signal": float(sig_c[d])}
        if d in spy_cum.index:
            entry["spy"] = float(spy_cum[d])
        q_val = quintiles.get(d)
        if q_val is not None and not np.isnan(q_val):
            entry["q"] = int(q_val)
        ts.append(entry)

    # Transition matrix
    n_q = int(quintiles.max()) + 1 if len(quintiles) > 0 else 0
    trans = np.zeros((n_q, n_q))
    prev = None
    for v in quintiles.values:
        if np.isnan(v): continue
        iv = int(v)
        if prev is not None: trans[prev][iv] += 1
        prev = iv
    trans_table = []
    for i in range(n_q):
        rs = trans[i].sum()
        row = {"from": f"Q{i+1}"}
        for j in range(n_q):
            row[f"Q{j+1}"] = round(float(trans[i][j] / rs * 100), 1) if rs > 0 else 0
        trans_table.append(row)

    # Drop tests: for each component in use_keys, test without it
    drop_tests = []
    for drop_key in use_keys:
        remaining = [k for k in use_keys if k != drop_key]
        if len(remaining) < 2 or not all(k in components for k in remaining):
            continue
        try:
            eq_w = [1.0 / len(remaining)] * len(remaining)
            dw = _optimize_weights(remaining, components, common, r6, sig_fn, filt,
                                   init_weights=eq_w, bounds=[(0.10, 0.80)] * len(remaining))
            d_comp = pd.Series(0.0, index=common)
            for k in remaining:
                d_comp += dw.get(k, eq_w[0]) * components[k].reindex(common, method="ffill").fillna(0)
            d_sig = sig_fn(d_comp).dropna()
            d_common = d_sig.index.intersection(r6.dropna().index)
            d_mid = len(d_common) // 2
            d_oos = _corr_simple(d_sig.reindex(d_common[d_mid:]), r6.reindex(d_common[d_mid:]))
            d_full = _corr_simple(d_sig, r6)
            drop_tests.append({
                "dropped": drop_key,
                "dropped_label": COMP_LABELS.get(drop_key, drop_key),
                "remaining": remaining,
                "oos_corr": d_oos,
                "full_corr": d_full,
            })
        except Exception:
            pass

    # Weight stability: Approach A (re-optimized) + Approach B (fixed weights)
    stability_a = []  # Re-optimized per window
    stability_b = []  # Fixed weights from full sample
    wt, ws = 48, 24   # Shorter windows for more walk-forward splits
    all_dates = sorted(common)

    for start in range(0, len(all_dates) - wt - ws, 24):
        train_dates = all_dates[start:start + wt]
        test_dates = all_dates[start + wt:start + wt + ws]
        if len(test_dates) < 10:
            break
        train_idx = pd.DatetimeIndex(train_dates)
        test_idx = pd.DatetimeIndex(test_dates)
        train_filt = filt.reindex(train_idx, fill_value=True)
        period = f"{train_dates[0].strftime('%Y')}-{train_dates[-1].strftime('%Y')} / {test_dates[0].strftime('%Y')}-{test_dates[-1].strftime('%Y')}"

        # Approach A: re-optimize
        w = _optimize_weights(use_keys, components, train_idx, r6, sig_fn, train_filt,
                              init_weights=use_default_w, bounds=w_bounds)
        test_comp_a = pd.Series(0.0, index=test_idx)
        for i, k in enumerate(use_keys):
            if k in components:
                test_comp_a += w.get(k, 1.0/len(use_keys)) * components[k].reindex(test_idx, method="ffill").fillna(0)
        test_sig_a = sig_fn(test_comp_a).dropna()
        test_filt_a = filt.reindex(test_idx, fill_value=True).reindex(test_sig_a.index, fill_value=True)
        oos_a = _corr_filtered(test_sig_a, r6, test_filt_a)
        stability_a.append({"period": period, "weights": w, "oos_corr": oos_a})

        # Approach B: fixed weights from opt_w
        test_comp_b = pd.Series(0.0, index=test_idx)
        for k in use_keys:
            if k in components:
                test_comp_b += opt_w.get(k, 1.0/len(use_keys)) * components[k].reindex(test_idx, method="ffill").fillna(0)
        test_sig_b = sig_fn(test_comp_b).dropna()
        test_filt_b = filt.reindex(test_idx, fill_value=True).reindex(test_sig_b.index, fill_value=True)
        oos_b = _corr_filtered(test_sig_b, r6, test_filt_b)
        stability_b.append({"period": period, "weights": opt_w, "oos_corr": oos_b})

    # Summaries for both approaches
    def _fw_summary(stab):
        vals = [s["oos_corr"] for s in stab if s.get("oos_corr") is not None]
        if not vals:
            return {}
        return {
            "mean": round(float(np.mean(vals)), 4),
            "std": round(float(np.std(vals)), 4),
            "n_positive": sum(1 for v in vals if v > 0),
            "n_windows": len(vals),
        }

    weight_std = {}
    if len(stability_a) >= 2:
        for k in use_keys:
            vals = [s["weights"].get(k, 0) for s in stability_a]
            weight_std[k] = round(float(np.std(vals)) * 100, 1)

    # SPY 6M forward return overlay with z-score normalization + rolling correlation
    spy_6m_fwd = spy_monthly.pct_change(6).shift(-6) * 100

    # Z-score normalize both for comparable visual
    def _z(s):
        m = s.rolling(36, min_periods=12).mean()
        st = s.rolling(36, min_periods=12).std().replace(0, np.nan)
        return ((s - m) / st).clip(-3, 3)

    sig_z = _z(sig_c)
    fwd_aligned = spy_6m_fwd.reindex(sig_c.index)
    fwd_z = _z(fwd_aligned.dropna()).reindex(sig_c.index)

    # Rolling 36M correlation
    roll_corr = sig_c.rolling(36, min_periods=12).corr(fwd_aligned)

    overlay_chart = []
    for d in sig_c.index[-240:]:
        entry = {"date": d.strftime("%Y-%m-%d")}
        entry["signal_z"] = float(sig_z[d]) if pd.notna(sig_z.get(d)) else None
        entry["spy_fwd_z"] = float(-fwd_z[d]) if pd.notna(fwd_z.get(d)) else None  # Invert so lines move together
        entry["roll_corr"] = float(roll_corr[d]) if pd.notna(roll_corr.get(d)) else None
        q_val = quintiles.get(d)
        if q_val is not None and not np.isnan(q_val):
            entry["q"] = int(q_val)
        overlay_chart.append(entry)

    return {
        "regime_table": regime_table,
        "optimized_weights": opt_w,
        "ts_chart": ts,
        "overlay_chart": overlay_chart,
        "transition_matrix": trans_table,
        "drop_tests": drop_tests,
        "stability_a": stability_a,
        "stability_b": stability_b,
        "fw_summary_a": _fw_summary(stability_a),
        "fw_summary_b": _fw_summary(stability_b),
        "weight_std": weight_std,
    }


def _precompute_filters(dates, spy_monthly, fred_data, vix_data):
    """Pre-compute all regime filter masks."""
    masks = {"all": pd.Series(True, index=dates)}
    spy_a = spy_monthly.reindex(dates, method="ffill")

    # Moving averages (daily → resample to approximate)
    if len(spy_monthly) > 200:
        ma200 = spy_monthly.rolling(200).mean().reindex(dates, method="ffill")
        masks["below200"] = spy_a < ma200
    if len(spy_monthly) > 50:
        ma50 = spy_monthly.rolling(50).mean().reindex(dates, method="ffill")
        masks["below50"] = spy_a < ma50

    # VIX
    if vix_data is not None and len(vix_data) > 0:
        v = vix_data.resample("MS").last().reindex(dates, method="ffill")
        masks["vix20"] = v > 20
        masks["vix25"] = v > 25

    # Drawdowns
    high = spy_monthly.rolling(252).max()
    dd = ((spy_monthly - high) / high * 100).reindex(dates, method="ffill")
    masks["dd5"] = dd < -5
    masks["dd10"] = dd < -10

    # Rates
    if fred_data is not None and isinstance(fred_data, pd.DataFrame) and "DGS10" in fred_data.columns:
        y10 = fred_data["DGS10"].resample("MS").last().diff(6).reindex(dates, method="ffill")
        masks["rates_up"] = y10 > 0
        masks["rates_down"] = y10 < 0

    # Fill NaN with False
    for k in masks:
        masks[k] = masks[k].fillna(False)

    return masks


def _corr_filtered(signal, returns, mask):
    idx = signal.index.intersection(returns.dropna().index)
    m = mask.reindex(idx, fill_value=True)
    a, b = signal.reindex(idx)[m], returns.reindex(idx)[m]
    if len(a) < 15: return None
    return round(float(np.corrcoef(a, b)[0, 1]), 4)


def _corr_simple(a, b):
    idx = a.index.intersection(b.dropna().index)
    if len(idx) < 15: return None
    return round(float(np.corrcoef(a.reindex(idx), b.reindex(idx))[0, 1]), 4)


def _optimize_weights(comp_keys, components, dates, fwd_ret, transform_fn, mask,
                      init_weights=None, bounds=None):
    """Optimize component weights."""
    n = len(comp_keys)
    if init_weights is None:
        init_weights = [1.0 / n] * n  # Equal weights as default
    if bounds is None:
        bounds = [(0.05, 0.50)] * n

    def _build(weights):
        s = pd.Series(0.0, index=dates)
        for i, key in enumerate(comp_keys):
            if key in components:
                s += weights[i] * components[key].reindex(dates, method="ffill").fillna(0)
        return s

    def _obj(weights):
        raw = _build(weights)
        sig = transform_fn(raw).dropna()
        common = sig.index.intersection(fwd_ret.dropna().index)
        m = mask.reindex(common, fill_value=True)
        if m.sum() < 20: return 0
        return np.corrcoef(sig.reindex(common)[m], fwd_ret.reindex(common)[m])[0, 1]

    init_val = _obj(init_weights)
    try:
        res = minimize(_obj, init_weights, method='SLSQP',
                       bounds=bounds,
                       constraints={'type': 'eq', 'fun': lambda w: sum(w) - 1.0},
                       options={'maxiter': 200})
        final_val = _obj(list(res.x))
        print(f"[OPT] {n}F: init obj={init_val:.4f} → final obj={final_val:.4f}, weights={[round(x,3) for x in res.x]}")
        return {k: round(float(v), 3) for k, v in zip(comp_keys, res.x)}
    except Exception as e:
        print(f"[OPT] Failed: {e}")
        return dict(zip(comp_keys, init_weights))


DRAWDOWN_DRIVERS = {
    "2007": "Credit crisis / GFC",
    "2008": "Credit crisis / GFC",
    "2009": "Credit crisis / GFC",
    "2011": "European debt crisis",
    "2015": "China deval / oil crash",
    "2016": "China deval / oil crash",
    "2018": "Fed QT / autopilot",
    "2019": "Trade war",
    "2020": "COVID exogenous shock",
    "2021": "Fed hiking / inflation",
    "2022": "Fed hiking / inflation",
    "2023": "Banking stress",
    "2024": "Yen carry unwind",
    "2025": "Tariff shock",
}


def _analyze_drawdowns(spy_monthly, signal):
    """Analyze signal state during major SPY drawdowns (>7%)."""
    spy_m = spy_monthly.resample("MS").last().dropna()
    if len(spy_m) < 50:
        return []

    peak = spy_m.expanding().max()
    dd = (spy_m - peak) / peak * 100

    drawdowns = []
    in_dd = False
    dd_start = None

    for date, val in dd.items():
        if val < -7 and not in_dd:  # Lowered from -10 to -7
            in_dd = True
            dd_start = peak[:date].idxmax()
        elif val > -2 and in_dd:
            in_dd = False
            trough_date = dd[dd_start:date].idxmin()
            trough_dd = float(dd[trough_date])

            def _get_sig(dt):
                nearby = signal.index[signal.index <= dt]
                if len(nearby) > 0:
                    v = signal[nearby[-1]]
                    return round(float(v), 3) if not np.isnan(v) else None
                return None

            peak_year = dd_start.strftime("%Y")
            driver = DRAWDOWN_DRIVERS.get(peak_year, "")

            drawdowns.append({
                "peak": dd_start.strftime("%Y-%m-%d"),
                "trough": trough_date.strftime("%Y-%m-%d"),
                "depth": round(trough_dd, 1),
                "driver": driver,
                "sig_3m_before": _get_sig(dd_start - pd.DateOffset(months=3)),
                "sig_at_peak": _get_sig(dd_start),
                "sig_at_trough": _get_sig(trough_date),
            })

    # Deduplicate by peak date
    seen_peaks = set()
    deduped = []
    for dd in drawdowns:
        pk = dd["peak"][:7]  # YYYY-MM
        if pk not in seen_peaks:
            seen_peaks.add(pk)
            deduped.append(dd)
    deduped.sort(key=lambda x: x["depth"])
    return deduped[:15]


# ─── Signal Validation: Monte Carlo, Equity Curve, Bootstrap ────────────────

def monte_carlo_permutation_test(signal, spy_fwd_returns, n_permutations=10000):
    """Shuffle signal dates randomly, recompute correlation each time.
    Returns p-value and distribution of null correlations."""
    aligned = pd.concat([signal.rename("sig"), spy_fwd_returns.rename("ret")], axis=1).dropna()
    if len(aligned) < 30:
        return {"error": "Not enough aligned data"}

    actual_corr = float(aligned["sig"].corr(aligned["ret"]))
    sig_vals = aligned["sig"].values
    ret_vals = aligned["ret"].values

    null_corrs = np.empty(n_permutations)
    for i in range(n_permutations):
        shuffled = np.random.permutation(sig_vals)
        null_corrs[i] = np.corrcoef(shuffled, ret_vals)[0, 1]

    p_value = float(np.mean(null_corrs <= actual_corr))
    hist_counts, hist_edges = np.histogram(null_corrs, bins=50)

    return {
        "actual_corr": round(actual_corr, 4),
        "p_value": round(p_value, 4),
        "null_mean": round(float(np.mean(null_corrs)), 4),
        "null_std": round(float(np.std(null_corrs)), 4),
        "null_5th_pct": round(float(np.percentile(null_corrs, 5)), 4),
        "null_1st_pct": round(float(np.percentile(null_corrs, 1)), 4),
        "percentile_rank": round(float(np.mean(null_corrs >= actual_corr) * 100), 1),
        "n_permutations": n_permutations,
        "n_data_points": len(aligned),
        "histogram": {"counts": hist_counts.tolist(), "edges": [round(e, 4) for e in hist_edges.tolist()]},
    }


ALLOCATION_RULES = {
    "aggressive": {1: 1.0, 2: 1.0, 3: 0.7, 4: 0.4, 5: 0.2},
    "moderate":   {1: 1.0, 2: 1.0, 3: 0.85, 4: 0.65, 5: 0.45},
    "gentle":     {1: 1.0, 2: 1.0, 3: 0.90, 4: 0.75, 5: 0.60},
    "minimal":    {1: 1.0, 2: 1.0, 3: 0.95, 4: 0.85, 5: 0.70},
    "symmetric":  {1: 1.2, 2: 1.1, 3: 1.0, 4: 0.9, 5: 0.8},
    "long_only":  {1: 1.0, 2: 0.95, 3: 0.85, 4: 0.75, 5: 0.65},
    "binary":     {1: 1.0, 2: 1.0, 3: 1.0, 4: 0.5, 5: 0.5},
    "q5_only":    {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 0.5},
}

DEFAULT_ALLOC = ALLOCATION_RULES["aggressive"]


def simulate_equity_curve(signal, spy_monthly_returns, alloc_map=None):
    """Simulate portfolio returns using signal-based allocation rules."""
    if alloc_map is None:
        alloc_map = DEFAULT_ALLOC
    aligned = pd.concat([signal.rename("sig"), spy_monthly_returns.rename("ret")], axis=1).dropna()
    if len(aligned) < 30:
        return {"error": "Not enough data"}

    try:
        quintiles = pd.qcut(aligned["sig"], 5, labels=[1, 2, 3, 4, 5], duplicates='drop')
    except Exception:
        return {"error": "Cannot form quintiles"}

    spy_weight = quintiles.map(alloc_map).astype(float)
    port_ret = aligned["ret"] * spy_weight

    port_eq = (1 + port_ret).cumprod()
    bh_eq = (1 + aligned["ret"]).cumprod()

    def _max_dd(eq):
        peak = eq.expanding().max()
        return float(((eq - peak) / peak).min())

    def _ann_ret(eq):
        years = len(eq) / 12
        return float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0

    def _ann_vol(rets):
        return float(rets.std() * np.sqrt(12))

    def _sharpe(rets):
        ar = _ann_ret((1 + rets).cumprod())
        av = _ann_vol(rets)
        return round(ar / av, 3) if av > 0 else 0

    chart = []
    for d in port_eq.index:
        chart.append({
            "date": d.strftime("%Y-%m-%d"),
            "portfolio": round(float(port_eq[d]), 4),
            "buyhold": round(float(bh_eq[d]), 4),
            "allocation": float(spy_weight[d]),
            "quintile": int(quintiles[d]),
        })

    return {
        "chart": chart,
        "metrics": {
            "portfolio": {
                "total_return": round(float(port_eq.iloc[-1] - 1) * 100, 1),
                "annualized_return": round(_ann_ret(port_eq) * 100, 2),
                "annualized_vol": round(_ann_vol(port_ret) * 100, 2),
                "sharpe": _sharpe(port_ret),
                "max_drawdown": round(_max_dd(port_eq) * 100, 1),
            },
            "buyhold": {
                "total_return": round(float(bh_eq.iloc[-1] - 1) * 100, 1),
                "annualized_return": round(_ann_ret(bh_eq) * 100, 2),
                "annualized_vol": round(_ann_vol(aligned["ret"]) * 100, 2),
                "sharpe": _sharpe(aligned["ret"]),
                "max_drawdown": round(_max_dd(bh_eq) * 100, 1),
            },
        },
    }


def bootstrap_equity_curves(signal, spy_monthly_returns, n_bootstrap=1000, alloc_map=None):
    """Resample (signal, return) pairs with replacement. Compute terminal values."""
    if alloc_map is None:
        alloc_map = DEFAULT_ALLOC
    aligned = pd.concat([signal.rename("sig"), spy_monthly_returns.rename("ret")], axis=1).dropna()
    if len(aligned) < 30:
        return {"error": "Not enough data"}

    n = len(aligned)

    tv_port = np.empty(n_bootstrap)
    tv_bh = np.empty(n_bootstrap)

    for b in range(n_bootstrap):
        idx = np.random.choice(n, size=n, replace=True)
        sampled_sig = aligned.iloc[idx, 0].values
        sampled_ret = aligned.iloc[idx, 1].values

        try:
            q = pd.qcut(pd.Series(sampled_sig), 5, labels=[1, 2, 3, 4, 5], duplicates='drop')
            weights = q.map(alloc_map).fillna(0.7).values
        except Exception:
            weights = np.full(n, 0.7)

        tv_port[b] = np.prod(1 + sampled_ret * weights)
        tv_bh[b] = np.prod(1 + sampled_ret)

    outperf_rate = float(np.mean(tv_port > tv_bh))

    def _pcts(arr):
        return {k: round(float(np.percentile(arr, v)), 2) for k, v in
                [("5th", 5), ("25th", 25), ("50th", 50), ("75th", 75), ("95th", 95)]}

    return {
        "portfolio_percentiles": _pcts(tv_port),
        "buyhold_percentiles": _pcts(tv_bh),
        "outperformance_rate": round(outperf_rate, 3),
        "outperformance_median_pct": round(float(np.median(tv_port / tv_bh - 1) * 100), 1),
        "n_bootstrap": n_bootstrap,
    }


def optimize_allocations(signal, spy_monthly_returns, n_quintiles=5):
    """Find SPY allocation per quintile that maximizes portfolio Sharpe ratio.
    Uses multiple starting points to avoid local minima."""
    aligned = pd.concat([signal.rename("sig"), spy_monthly_returns.rename("ret")], axis=1).dropna()
    if len(aligned) < 30:
        return {i + 1: 1.0 for i in range(n_quintiles)}, 0

    try:
        quintiles = pd.qcut(aligned["sig"], n_quintiles, labels=range(1, n_quintiles + 1), duplicates='drop')
    except Exception:
        return {i + 1: 1.0 for i in range(n_quintiles)}, 0

    ret_vals = aligned["ret"].values
    q_vals = quintiles.fillna(3).astype(int).values

    def _neg_sharpe(allocs):
        weights = np.array([allocs[q - 1] for q in q_vals])
        port = ret_vals * weights
        ann_ret = float(np.prod(1 + port) ** (12.0 / len(port)) - 1)
        ann_vol = float(np.std(port) * np.sqrt(12))
        if ann_vol < 1e-8:
            return 0
        return -(ann_ret / ann_vol)

    bounds = [(0.1, 1.0)] * n_quintiles
    # Monotonicity: Q1 >= Q2 >= Q3 >= Q4 >= Q5
    mono_constraints = [
        {'type': 'ineq', 'fun': lambda w, i=i: w[i] - w[i+1]}
        for i in range(n_quintiles - 1)
    ]

    # Multiple starting points to avoid local minima
    starts = [
        [1.0, 1.0, 0.7, 0.4, 0.2],      # aggressive
        [1.0, 1.0, 0.85, 0.65, 0.45],    # moderate
        [1.0, 1.0, 1.0, 1.0, 1.0],       # passive (buy-and-hold)
    ]

    best_sharpe = -999
    best_allocs = {i + 1: 1.0 for i in range(n_quintiles)}

    for x0 in starts:
        try:
            result = minimize(_neg_sharpe, x0[:n_quintiles], method='SLSQP',
                              bounds=bounds, constraints=mono_constraints,
                              options={'maxiter': 500})
            sharpe = -float(result.fun)
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_allocs = {i + 1: round(float(result.x[i]), 3) for i in range(n_quintiles)}
        except Exception:
            continue

    # Sanity check: optimized should beat aggressive preset
    agg_ec = simulate_equity_curve(signal, spy_monthly_returns, alloc_map=ALLOCATION_RULES["aggressive"])
    agg_sharpe = agg_ec.get("metrics", {}).get("portfolio", {}).get("sharpe", 0) if "error" not in agg_ec else 0
    if best_sharpe < agg_sharpe:
        print(f"[ALLOC OPT] WARNING: optimized Sharpe {best_sharpe:.3f} < aggressive preset {agg_sharpe:.3f}")

    print(f"[ALLOC OPT] Best Sharpe: {best_sharpe:.3f}, allocs: {best_allocs}")
    return best_allocs, round(best_sharpe, 3)


def run_allocation_comparison(signal, spy_returns):
    """Run equity curve sim for all predefined rules + optimizer. Return comparison."""
    results = []

    for name, alloc in ALLOCATION_RULES.items():
        ec = simulate_equity_curve(signal, spy_returns, alloc_map=alloc)
        if "error" in ec:
            continue
        m = ec["metrics"]["portfolio"]
        results.append({
            "name": name,
            "allocs": alloc,
            "total_return": m["total_return"],
            "annualized_return": m["annualized_return"],
            "annualized_vol": m["annualized_vol"],
            "sharpe": m["sharpe"],
            "max_drawdown": m["max_drawdown"],
        })

    # Optimized
    opt_allocs, opt_sharpe = optimize_allocations(signal, spy_returns)
    ec_opt = simulate_equity_curve(signal, spy_returns, alloc_map=opt_allocs)
    if "error" not in ec_opt:
        m = ec_opt["metrics"]["portfolio"]
        results.append({
            "name": "optimized",
            "allocs": opt_allocs,
            "total_return": m["total_return"],
            "annualized_return": m["annualized_return"],
            "annualized_vol": m["annualized_vol"],
            "sharpe": m["sharpe"],
            "max_drawdown": m["max_drawdown"],
        })

    # Buy & hold baseline
    bh = simulate_equity_curve(signal, spy_returns, alloc_map={1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 1.0})
    if "error" not in bh:
        m = bh["metrics"]["buyhold"]
        results.append({
            "name": "buyhold",
            "allocs": {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 1.0},
            "total_return": m["total_return"],
            "annualized_return": m["annualized_return"],
            "annualized_vol": m["annualized_vol"],
            "sharpe": m["sharpe"],
            "max_drawdown": m["max_drawdown"],
        })

    # Sort by Sharpe descending
    results.sort(key=lambda x: x.get("sharpe", 0), reverse=True)

    # Get equity curves for top 3 + buyhold for chart
    top3_charts = {}
    for r in results[:3]:
        if r["name"] == "buyhold":
            continue
        ec = simulate_equity_curve(signal, spy_returns, alloc_map=r["allocs"])
        if "error" not in ec:
            top3_charts[r["name"]] = ec["chart"]

    # Bootstrap on the winner
    winner = results[0] if results else None
    winner_bootstrap = None
    if winner and winner["name"] != "buyhold":
        winner_bootstrap = bootstrap_equity_curves(signal, spy_returns, alloc_map=winner["allocs"])

    return {
        "comparison": results,
        "top3_charts": top3_charts,
        "winner": winner,
        "winner_bootstrap": winner_bootstrap,
    }


def run_signal_validation(ratio_series, spy_monthly, model="3fa"):
    """Run all three validation tests on the production signal."""
    cfg = PRODUCTION_MODELS.get(model, PRODUCTION_MODELS["3fa"])
    sig_fn = SIGNAL_TRANSFORMS.get(cfg["signal_type"], SIGNAL_TRANSFORMS["mom6"])[1]

    # Diagnostic logging
    print(f"[VALIDATION] Model: {model}, Signal: {cfg['signal_type']}, Weights: {cfg['weights']}")

    # Extract components and build composite
    all_keys = list(set(COMP_KEYS + ["dollar_stress_signal"]))
    components = {}
    for key in all_keys:
        s = pd.Series(
            {pd.Timestamp(r["date"]): r.get(key) for r in ratio_series},
            dtype=float).dropna().sort_index()
        if len(s) > 0:
            components[key] = s

    missing = [k for k in cfg["keys"] if k not in components]
    if missing:
        return {"error": f"Missing: {missing}"}

    base_idx = next(iter(components.values())).index
    comp = pd.Series(0.0, index=base_idx)
    for k in cfg["keys"]:
        comp += cfg["weights"][k] * components[k].reindex(base_idx, method="ffill").fillna(0)

    signal = sig_fn(comp).dropna()
    spy_ret = spy_monthly.pct_change().dropna()
    spy_fwd = spy_monthly.pct_change(6).shift(-6) * 100

    # Diagnostic: print dollar_stress_signal last 5
    ds = components.get("dollar_stress_signal")
    if ds is not None:
        tail = ds.tail(5)
        tail_str = ', '.join(f"{d.strftime('%Y-%m')}={v:.3f}" for d, v in tail.items())
        print(f"[VALIDATION] dollar_stress_signal last 5: {tail_str}")
    else:
        print("[VALIDATION] dollar_stress_signal: NOT PRESENT")

    print(f"[VALIDATION] Signal: {len(signal)} pts, range {signal.index[0].strftime('%Y-%m')} to {signal.index[-1].strftime('%Y-%m')}")

    spy_aligned = spy_ret.reindex(signal.index)

    mc = monte_carlo_permutation_test(signal, spy_fwd)
    ec = simulate_equity_curve(signal, spy_aligned)
    bs = bootstrap_equity_curves(signal, spy_aligned)
    alloc_comp = run_allocation_comparison(signal, spy_aligned)

    # Auto-interpretation
    if mc.get("p_value", 1) < 0.01:
        mc_verdict = f"STATISTICALLY SIGNIFICANT at 99% confidence (p={mc['p_value']:.3f})"
    elif mc.get("p_value", 1) < 0.05:
        mc_verdict = f"Significant at 95% confidence (p={mc['p_value']:.3f})"
    else:
        mc_verdict = f"NOT significant (p={mc['p_value']:.3f}) — cannot reject noise"

    return {
        "model": model,
        "monte_carlo": mc,
        "monte_carlo_verdict": mc_verdict,
        "equity_curve": ec,
        "bootstrap": bs,
        "allocation_comparison": alloc_comp,
    }
