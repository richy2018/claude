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
COMP_LABELS = {"quantity_signal": "Qty", "rate_signal": "Rates", "spread_signal": "Credit", "curve_signal": "Curve", "m2_signal": "M2"}
DEFAULT_W = [0.25, 0.25, 0.20, 0.15, 0.15]


def run_sweep(ratio_series, spy_monthly, fred_data=None, vix_data=None):
    """Run full sweep across all 216 configurations. Return leaderboard + top config detail."""
    # Extract data
    comp = pd.Series(
        {pd.Timestamp(r["date"]): r.get("composite_signal") for r in ratio_series},
        dtype=float).dropna().sort_index()
    components = {}
    for key in COMP_KEYS:
        s = pd.Series(
            {pd.Timestamp(r["date"]): r.get(key) for r in ratio_series},
            dtype=float).dropna().sort_index()
        if len(s) > 0:
            components[key] = s

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
            if n_filtered < 30:
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
            for q in range(5):
                qm = (quintiles == q) & filt_mask
                vals = r6.reindex(common)[qm].dropna()
                q_avgs.append(float(vals.mean()) if len(vals) > 2 else None)

            spread = (q_avgs[0] - q_avgs[4]) if q_avgs[0] is not None and q_avgs[4] is not None else None
            valid_q = [x for x in q_avgs if x is not None]
            mono = float(sp_stats.spearmanr(range(len(valid_q)), valid_q)[0]) if len(valid_q) >= 4 else None

            # OOS correlation (simple split)
            mid = len(common) // 2
            oos_corr = _corr_simple(sig_c.iloc[mid:], r6.reindex(common[mid:]))

            for obj in OPT_OBJECTIVES:
                leaderboard.append({
                    "signal": sig_key, "signal_name": sig_name,
                    "filter": filt_key, "filter_name": REGIME_LABELS.get(filt_key, filt_key),
                    "objective": obj, "n": n_filtered,
                    "corr_3m": corr3, "corr_6m": corr6, "corr_12m": corr12,
                    "oos_corr_6m": oos_corr,
                    "spread_6m": round(spread, 2) if spread is not None else None,
                    "monotonicity": round(mono, 3) if mono is not None else None,
                    "q_avgs": [round(x, 2) if x is not None else None for x in q_avgs],
                    "weights": dict(zip(COMP_KEYS, DEFAULT_W)),  # Default; optimize on selection
                })

    # Sort by OOS 6M correlation (most negative = best predictor)
    leaderboard.sort(key=lambda x: x.get("oos_corr_6m") or 0)

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
        comp_diag[key] = {
            "corr_3m": _corr_simple(cs, r3),
            "corr_6m": _corr_simple(cs, r6),
            "corr_12m": _corr_simple(cs, r12),
        }

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

    return {
        "leaderboard": top,
        "summary": summary,
        "total_configs": len(leaderboard),
        "component_diagnostics": comp_diag,
        "marginal_contribution": marginal,
        "drawdown_analysis": drawdowns,
    }


def run_detail(ratio_series, spy_monthly, signal_type, regime_filter, components_cache=None,
               fred_data=None, vix_data=None):
    """Run detailed analysis for a single selected config with weight optimization."""
    comp = pd.Series(
        {pd.Timestamp(r["date"]): r.get("composite_signal") for r in ratio_series},
        dtype=float).dropna().sort_index()
    components = components_cache or {}
    if not components:
        for key in COMP_KEYS:
            s = pd.Series({pd.Timestamp(r["date"]): r.get(key) for r in ratio_series}, dtype=float).dropna().sort_index()
            if len(s) > 0:
                components[key] = s

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
    opt_w = _optimize_weights(COMP_KEYS, components, common, r6, sig_fn, filt)

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

    return {
        "regime_table": regime_table,
        "optimized_weights": opt_w,
        "ts_chart": ts,
        "transition_matrix": trans_table,
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


def _optimize_weights(comp_keys, components, dates, fwd_ret, transform_fn, mask):
    """Optimize component weights."""
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

    try:
        res = minimize(_obj, DEFAULT_W, method='SLSQP',
                       bounds=[(0.05, 0.50)] * len(comp_keys),
                       constraints={'type': 'eq', 'fun': lambda w: sum(w) - 1.0},
                       options={'maxiter': 100})
        return {k: round(float(v), 3) for k, v in zip(comp_keys, res.x)}
    except Exception:
        return dict(zip(comp_keys, DEFAULT_W))


def _analyze_drawdowns(spy_monthly, signal):
    """Analyze signal state during major SPY drawdowns."""
    spy_m = spy_monthly.resample("MS").last().dropna()
    if len(spy_m) < 50:
        return []

    peak = spy_m.expanding().max()
    dd = (spy_m - peak) / peak * 100

    drawdowns = []
    in_dd = False
    dd_start = None

    for date, val in dd.items():
        if val < -10 and not in_dd:
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

            drawdowns.append({
                "peak": dd_start.strftime("%Y-%m-%d"),
                "trough": trough_date.strftime("%Y-%m-%d"),
                "depth": round(trough_dd, 1),
                "sig_3m_before": _get_sig(dd_start - pd.DateOffset(months=3)),
                "sig_at_peak": _get_sig(dd_start),
                "sig_at_trough": _get_sig(trough_date),
            })

    drawdowns.sort(key=lambda x: x["depth"])
    return drawdowns[:10]
