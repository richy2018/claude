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

    # Auto-summary
    best = top[0] if top else None
    if best and best.get("oos_corr_6m") is not None:
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

    # Weight stability across walk-forward windows (120M train, 60M test)
    stability = []
    window_train = 120
    window_test = 60
    all_dates = sorted(common)
    for start in range(0, len(all_dates) - window_train - window_test, 24):  # step by 24 months
        train_dates = all_dates[start:start + window_train]
        test_dates = all_dates[start + window_train:start + window_train + window_test]
        if len(test_dates) < 10:
            break
        train_idx = pd.DatetimeIndex(train_dates)
        test_idx = pd.DatetimeIndex(test_dates)
        train_filt = filt.reindex(train_idx, fill_value=True)

        w = _optimize_weights(use_keys, components, train_idx, r6, sig_fn, train_filt,
                              init_weights=use_default_w, bounds=w_bounds)

        # Test OOS
        test_comp = pd.Series(0.0, index=test_idx)
        for i, k in enumerate(COMP_KEYS):
            if k in components:
                test_comp += w.get(k, 0.2) * components[k].reindex(test_idx, method="ffill").fillna(0)
        test_sig = sig_fn(test_comp).dropna()
        test_filt = filt.reindex(test_idx, fill_value=True)
        test_oos = _corr_filtered(test_sig, r6, test_filt.reindex(test_sig.index, fill_value=True))

        stability.append({
            "period": f"{train_dates[0].strftime('%Y')}-{train_dates[-1].strftime('%Y')} / {test_dates[0].strftime('%Y')}-{test_dates[-1].strftime('%Y')}",
            "weights": w,
            "oos_corr": test_oos,
        })

    # Weight std + OOS summary across windows
    weight_std = {}
    oos_summary = {}
    if len(stability) >= 2:
        for k in COMP_KEYS:
            vals = [s["weights"].get(k, 0) for s in stability]
            weight_std[k] = round(float(np.std(vals)) * 100, 1)
        oos_vals = [s["oos_corr"] for s in stability if s.get("oos_corr") is not None]
        if oos_vals:
            oos_summary = {
                "mean": round(float(np.mean(oos_vals)), 4),
                "std": round(float(np.std(oos_vals)), 4),
                "n_positive": sum(1 for v in oos_vals if v > 0),  # wrong-sign windows
                "n_windows": len(oos_vals),
            }

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
        "stability": stability,
        "weight_std": weight_std,
        "oos_summary": oos_summary,
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
