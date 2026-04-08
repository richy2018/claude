"""Composite signal backtest engine — signal transforms, regime filters, diagnostics."""

import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from scipy.optimize import minimize


# Signal transformation functions
def _signal_level(comp):
    """Raw composite level."""
    return comp

def _signal_momentum(comp, months=1):
    """N-month change in composite."""
    return comp.diff(months)

def _signal_acceleration(comp):
    """Change in 3M momentum (second derivative)."""
    return comp.diff(3).diff(3)

def _signal_zscore(comp, window=12):
    """Rolling z-score over trailing window."""
    m = comp.rolling(window, min_periods=max(6, window // 2)).mean()
    s = comp.rolling(window, min_periods=max(6, window // 2)).std().replace(0, np.nan)
    return ((comp - m) / s).clip(-3, 3)

def _signal_percentile(comp, window=60):
    """Rolling percentile rank."""
    return comp.rolling(window, min_periods=12).apply(
        lambda x: sp_stats.percentileofscore(x, x.iloc[-1]) if len(x) > 1 else 50, raw=False)


SIGNAL_TRANSFORMS = {
    "level": ("Level", lambda c: _signal_level(c)),
    "mom_1m": ("Momentum (1M)", lambda c: _signal_momentum(c, 1)),
    "mom_3m": ("Momentum (3M)", lambda c: _signal_momentum(c, 3)),
    "mom_6m": ("Momentum (6M)", lambda c: _signal_momentum(c, 6)),
    "accel": ("Acceleration", lambda c: _signal_acceleration(c)),
    "zscore_12m": ("Z-Score (12M)", lambda c: _signal_zscore(c, 12)),
    "zscore_36m": ("Z-Score (36M)", lambda c: _signal_zscore(c, 36)),
    "pctl_60m": ("Percentile (60M)", lambda c: _signal_percentile(c, 60)),
}


def run_backtest(
    ratio_series: list,
    spy_monthly: pd.Series,
    signal_type: str = "level",
    regime_filter: str = "unconditional",
    opt_objective: str = "spread",
    fred_data: pd.DataFrame = None,
    vix_data: pd.Series = None,
) -> dict:
    """Run comprehensive backtest of composite signal.

    Args:
        ratio_series: List of dicts from debt_ratio computation.
        spy_monthly: SPY monthly close prices.
        signal_type: Key from SIGNAL_TRANSFORMS.
        regime_filter: Filter name.
        opt_objective: Optimization objective.
        fred_data: FRED DataFrame for regime filters.
        vix_data: VIX series for regime filters.
    """
    # Extract composite signal and components
    comp = pd.Series(
        {pd.Timestamp(r["date"]): r.get("composite_signal") for r in ratio_series},
        dtype=float).dropna().sort_index()

    comp_keys = ["quantity_signal", "rate_signal", "spread_signal", "curve_signal", "m2_signal"]
    components = {}
    for key in comp_keys:
        s = pd.Series(
            {pd.Timestamp(r["date"]): r.get(key) for r in ratio_series},
            dtype=float).dropna().sort_index()
        if len(s) > 0:
            components[key] = s

    # Apply signal transformation
    transform_name = SIGNAL_TRANSFORMS.get(signal_type, SIGNAL_TRANSFORMS["level"])[0]
    transform_fn = SIGNAL_TRANSFORMS.get(signal_type, SIGNAL_TRANSFORMS["level"])[1]
    signal = transform_fn(comp).dropna()

    if len(signal) < 30:
        return {"error": f"Not enough data after {transform_name} transform: {len(signal)} points"}

    # Forward returns at 3M, 6M, 12M
    spy_ret_3m = spy_monthly.pct_change(3).shift(-3) * 100
    spy_ret_6m = spy_monthly.pct_change(6).shift(-6) * 100
    spy_ret_12m = spy_monthly.pct_change(12).shift(-12) * 100

    # Align
    common = signal.index.intersection(spy_ret_3m.dropna().index)
    common = common.intersection(spy_ret_6m.dropna().index)
    if len(common) < 30:
        return {"error": f"Not enough overlapping data: {len(common)} months"}

    sig = signal.reindex(common)
    r3 = spy_ret_3m.reindex(common)
    r6 = spy_ret_6m.reindex(common)
    r12 = spy_ret_12m.reindex(common)

    # 12M: include all months where 12M data exists
    common_12m = signal.index.intersection(spy_ret_12m.dropna().index)
    r12_full = spy_ret_12m.reindex(common_12m)
    sig_12m = signal.reindex(common_12m)

    # Regime filter
    filter_mask = pd.Series(True, index=common)
    filter_desc = "All months"
    if regime_filter != "unconditional" and spy_monthly is not None:
        filter_mask, filter_desc = _apply_regime_filter(
            regime_filter, common, spy_monthly, fred_data, vix_data)

    # Correlations
    def _corr(a, b, mask=None):
        if mask is not None:
            idx = a.index.intersection(b.dropna().index)
            m = mask.reindex(idx).fillna(False)
            a, b = a.reindex(idx)[m], b.reindex(idx)[m]
        else:
            idx = a.index.intersection(b.dropna().index)
            a, b = a.reindex(idx), b.reindex(idx)
        if len(a) < 15:
            return None
        return round(float(np.corrcoef(a, b)[0, 1]), 4)

    correlations = {
        "3m": _corr(sig, r3, filter_mask),
        "6m": _corr(sig, r6, filter_mask),
        "12m": _corr(sig_12m, r12_full),
    }

    # Quintile analysis — quintile breakpoints from ALL data, returns from filtered
    try:
        quintile_labels = ["Q1 Most Loose", "Q2 Loose", "Q3 Neutral", "Q4 Tight", "Q5 Most Tight"]
        quintiles = pd.qcut(sig, 5, labels=False, duplicates='drop')
    except Exception:
        quintiles = pd.Series(0, index=common)
        quintile_labels = ["All"]

    regime_table = []
    for q in range(min(5, quintiles.max() + 1)):
        q_mask = (quintiles == q)
        if filter_mask is not None:
            q_mask = q_mask & filter_mask.reindex(q_mask.index, fill_value=True)
        dts = sig[q_mask].index
        n = int(q_mask.sum())

        def _avg(ret, dates):
            v = ret.reindex(dates).dropna()
            return round(float(v.mean()), 2) if len(v) > 2 else None

        def _hitrate(ret, dates):
            v = ret.reindex(dates).dropna()
            return round(float((v > 0).mean()) * 100, 1) if len(v) > 2 else None

        regime_table.append({
            "quintile": quintile_labels[q] if q < len(quintile_labels) else f"Q{q+1}",
            "count": n,
            "avg_3m": _avg(r3, dts), "avg_6m": _avg(r6, dts), "avg_12m": _avg(r12_full, dts),
            "hit_3m": _hitrate(r3, dts), "hit_6m": _hitrate(r6, dts),
        })

    # Q1-Q5 spread
    q1_6m = regime_table[0]["avg_6m"] if regime_table else None
    q5_6m = regime_table[-1]["avg_6m"] if regime_table else None
    spread_6m = round(q1_6m - q5_6m, 2) if q1_6m is not None and q5_6m is not None else None

    # Component-level diagnostics
    component_diag = {}
    for key in comp_keys:
        if key not in components:
            continue
        cs = components[key].reindex(common)
        component_diag[key] = {
            "corr_3m": _corr(cs, r3),
            "corr_6m": _corr(cs, r6),
            "corr_12m": _corr(cs.reindex(common_12m), r12_full) if len(common_12m) > 20 else None,
        }

    # Weight optimization
    default_w = [0.25, 0.25, 0.20, 0.15, 0.15]
    opt_result = _optimize_weights(
        comp_keys, components, common, r6, spy_monthly,
        transform_fn, default_w, opt_objective, filter_mask)

    # Robustness: in-sample vs out-of-sample
    mid = len(common) // 2
    is_corr = _corr(sig.iloc[:mid], r6.reindex(common[:mid]))
    oos_corr = _corr(sig.iloc[mid:], r6.reindex(common[mid:]))
    overfit = is_corr is not None and oos_corr is not None and abs(is_corr - oos_corr) > 0.15

    # Quintile transition matrix
    transitions = _compute_transition_matrix(quintiles)

    # Drawdown analysis
    drawdown_analysis = _analyze_drawdowns(spy_monthly, sig, quintiles)

    # Time series for chart (signal + SPY cumulative return)
    spy_cum = ((1 + spy_monthly.pct_change().fillna(0)).cumprod() - 1) * 100
    ts_chart = []
    for d in sig.index:
        entry = {"date": d.strftime("%Y-%m-%d"), "signal": float(sig[d])}
        if d in spy_cum.index:
            entry["spy_cum"] = float(spy_cum[d])
        q_val = quintiles.get(d)
        if q_val is not None and not np.isnan(q_val):
            entry["quintile"] = int(q_val)
        ts_chart.append(entry)

    return {
        "signal_type": signal_type,
        "signal_name": transform_name,
        "regime_filter": regime_filter,
        "filter_desc": filter_desc,
        "data_points": len(common),
        "filtered_points": int(filter_mask.sum()) if filter_mask is not None else len(common),
        "correlations": correlations,
        "regime_table": regime_table,
        "spread_6m": spread_6m,
        "component_diagnostics": component_diag,
        "manual_weights": dict(zip(comp_keys, default_w)),
        "optimized_weights": opt_result.get("weights", {}),
        "opt_correlation": opt_result.get("correlation", {}),
        "opt_objective": opt_objective,
        "in_sample_corr": is_corr,
        "out_of_sample_corr": oos_corr,
        "overfit_warning": overfit,
        "transition_matrix": transitions,
        "drawdown_analysis": drawdown_analysis,
        "ts_chart": ts_chart[-240:],  # Last 20 years
    }


def _apply_regime_filter(filter_name, dates, spy_monthly, fred_data, vix_data):
    """Apply regime filter and return boolean mask + description."""
    mask = pd.Series(True, index=dates)
    desc = "All months"

    spy_aligned = spy_monthly.reindex(dates, method="ffill")

    if filter_name == "spy_below_200dma":
        ma200 = spy_monthly.rolling(200).mean()
        ma_aligned = ma200.reindex(dates, method="ffill")
        mask = spy_aligned < ma_aligned
        desc = "SPY below 200dma"
    elif filter_name == "spy_below_50dma":
        ma50 = spy_monthly.rolling(50).mean()
        ma_aligned = ma50.reindex(dates, method="ffill")
        mask = spy_aligned < ma_aligned
        desc = "SPY below 50dma"
    elif filter_name == "vix_gt_20" and vix_data is not None:
        v = vix_data.resample("MS").last().reindex(dates, method="ffill")
        mask = v > 20
        desc = "VIX > 20"
    elif filter_name == "vix_gt_25" and vix_data is not None:
        v = vix_data.resample("MS").last().reindex(dates, method="ffill")
        mask = v > 25
        desc = "VIX > 25"
    elif filter_name == "drawdown_gt_5":
        high = spy_monthly.rolling(252).max()
        dd = (spy_monthly - high) / high * 100
        dd_aligned = dd.reindex(dates, method="ffill")
        mask = dd_aligned < -5
        desc = "Drawdown > 5%"
    elif filter_name == "drawdown_gt_10":
        high = spy_monthly.rolling(252).max()
        dd = (spy_monthly - high) / high * 100
        dd_aligned = dd.reindex(dates, method="ffill")
        mask = dd_aligned < -10
        desc = "Drawdown > 10%"
    elif filter_name == "rising_rates" and fred_data is not None and "DGS10" in fred_data.columns:
        y10 = fred_data["DGS10"].resample("MS").last()
        chg = y10.diff(6)
        chg_aligned = chg.reindex(dates, method="ffill")
        mask = chg_aligned > 0
        desc = "Rising 10Y rates"
    elif filter_name == "falling_rates" and fred_data is not None and "DGS10" in fred_data.columns:
        y10 = fred_data["DGS10"].resample("MS").last()
        chg = y10.diff(6)
        chg_aligned = chg.reindex(dates, method="ffill")
        mask = chg_aligned < 0
        desc = "Falling 10Y rates"

    return mask.fillna(False), desc


def _optimize_weights(comp_keys, components, dates, fwd_ret, spy_monthly,
                      transform_fn, default_w, objective, filter_mask):
    """Optimize component weights for given objective."""
    def _build_composite(weights):
        s = pd.Series(0.0, index=dates)
        for i, key in enumerate(comp_keys):
            if key in components:
                s += weights[i] * components[key].reindex(dates, method="ffill").fillna(0)
        return s

    def _objective(weights):
        raw = _build_composite(weights)
        sig = transform_fn(raw).dropna()
        common = sig.index.intersection(fwd_ret.dropna().index)
        if filter_mask is not None:
            m = filter_mask.reindex(common, fill_value=True)
            common = common[m.reindex(common, fill_value=True)]
        if len(common) < 20:
            return 0

        sig_c = sig.reindex(common)
        ret_c = fwd_ret.reindex(common)

        if objective == "correlation":
            return np.corrcoef(sig_c, ret_c)[0, 1]  # minimize = most negative
        elif objective == "monotonicity":
            try:
                q = pd.qcut(sig_c, 5, labels=False, duplicates='drop')
                avg_rets = [ret_c[q == i].mean() for i in range(5)]
                # Spearman correlation of quintile rank vs return (want negative)
                return sp_stats.spearmanr(range(len(avg_rets)), avg_rets)[0]
            except Exception:
                return 0
        else:  # spread
            try:
                q = pd.qcut(sig_c, 5, labels=False, duplicates='drop')
                q1 = ret_c[q == 0].mean()
                q5 = ret_c[q == q.max()].mean()
                return -(q1 - q5)  # minimize negative spread = maximize spread
            except Exception:
                return 0

    try:
        result = minimize(_objective, default_w, method='SLSQP',
                          bounds=[(0.05, 0.50)] * len(comp_keys),
                          constraints={'type': 'eq', 'fun': lambda w: sum(w) - 1.0},
                          options={'maxiter': 200})
        opt_w = {k: round(float(v), 3) for k, v in zip(comp_keys, result.x)}

        # Compute optimized correlations
        opt_raw = _build_composite(list(result.x))
        opt_sig = transform_fn(opt_raw).dropna()
        spy_r6 = spy_monthly.pct_change(6).shift(-6) * 100
        opt_common = opt_sig.index.intersection(spy_r6.dropna().index)

        def _c(a, b):
            idx = a.index.intersection(b.dropna().index)
            if len(idx) < 15: return None
            return round(float(np.corrcoef(a.reindex(idx), b.reindex(idx))[0, 1]), 4)

        spy_r3 = spy_monthly.pct_change(3).shift(-3) * 100
        spy_r12 = spy_monthly.pct_change(12).shift(-12) * 100

        opt_corr = {
            "3m": _c(opt_sig, spy_r3),
            "6m": _c(opt_sig, spy_r6),
            "12m": _c(opt_sig, spy_r12),
        }
        return {"weights": opt_w, "correlation": opt_corr}
    except Exception as e:
        print(f"[BACKTEST] Optimization failed: {e}")
        return {"weights": dict(zip(comp_keys, default_w)), "correlation": {}}


def _compute_transition_matrix(quintiles):
    """Compute quintile-to-quintile transition probabilities."""
    n = int(quintiles.max()) + 1 if len(quintiles) > 0 else 0
    if n < 2:
        return []

    matrix = np.zeros((n, n))
    prev = None
    for val in quintiles.values:
        if np.isnan(val):
            continue
        v = int(val)
        if prev is not None:
            matrix[prev][v] += 1
        prev = v

    # Normalize to percentages
    result = []
    for i in range(n):
        row_sum = matrix[i].sum()
        row = {"from": f"Q{i+1}"}
        for j in range(n):
            row[f"Q{j+1}"] = round(float(matrix[i][j] / row_sum * 100), 1) if row_sum > 0 else 0
        result.append(row)
    return result


def _analyze_drawdowns(spy_monthly, signal, quintiles):
    """Analyze signal state during major SPY drawdowns."""
    if len(spy_monthly) < 50:
        return []

    # Find peak-to-trough drawdowns > 10%
    spy_m = spy_monthly.resample("MS").last().dropna()
    peak = spy_m.expanding().max()
    dd = (spy_m - peak) / peak * 100

    # Find trough points
    drawdowns = []
    in_dd = False
    dd_start = None
    dd_peak_val = None

    for i, (date, val) in enumerate(dd.items()):
        if val < -10 and not in_dd:
            in_dd = True
            # Find the peak date (where price was highest before this)
            dd_start = peak[:date].idxmax()
            dd_peak_val = float(peak[dd_start])
        elif val > -2 and in_dd:
            in_dd = False
            trough_date = dd[dd_start:date].idxmin()
            trough_dd = float(dd[trough_date])

            # Get signal quintile at key moments
            def _get_q(dt):
                nearby = quintiles.index[quintiles.index <= dt]
                if len(nearby) > 0:
                    return int(quintiles[nearby[-1]]) + 1 if not np.isnan(quintiles[nearby[-1]]) else None
                return None

            drawdowns.append({
                "peak_date": dd_start.strftime("%Y-%m-%d"),
                "trough_date": trough_date.strftime("%Y-%m-%d"),
                "drawdown_pct": round(trough_dd, 1),
                "q_at_peak": _get_q(dd_start),
                "q_3m_before": _get_q(dd_start - pd.DateOffset(months=3)),
                "q_at_trough": _get_q(trough_date),
            })

    # Sort by severity, take top 10
    drawdowns.sort(key=lambda x: x["drawdown_pct"])
    return drawdowns[:10]
