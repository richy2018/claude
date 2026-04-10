"""GLI Real-Time Signal Validation — Publication Lag Simulation + MC Tests.

Tests whether the 5F model survives when each factor is lagged by its
real-world publication delay. Also tests 4F fallback (drops Qty/BIS).
Includes Monte Carlo significance and per-crash quintile detail.
"""

import numpy as np
import pandas as pd

from .backtest_engine import (
    _extract_components, SIGNAL_TRANSFORMS, PRODUCTION_MODELS,
    ALLOCATION_RULES, sortino_ratio, _signal_momentum,
)

_PROD = PRODUCTION_MODELS["5f"]
_PROD_KEYS = _PROD["keys"]
_PROD_WEIGHTS = _PROD["weights"]
_SIG_TYPE = _PROD["signal_type"]  # "mom6"
_SIG_FN = SIGNAL_TRANSFORMS[_SIG_TYPE][1]
_ALLOC = ALLOCATION_RULES["production"]

# Realistic publication lags in months
PUBLICATION_LAGS_REALISTIC = {
    "quantity_signal": 6,       # BIS ratio: quarterly + 3-6M publication delay
    "m2_signal": 1,             # M2SL: monthly, ~1M lag
    "spread_signal": 0,         # HY OAS: daily
    "dollar_stress_signal": 0,  # Xccy basis: weekly
    "rate_signal": 0,           # Fed Funds: daily
}

TAIL_EVENTS = [
    {"name": "GFC", "start": "2007-09-01"},
    {"name": "COVID", "start": "2020-02-01"},
    {"name": "Rate Shock", "start": "2022-01-01"},
    {"name": "Vol Shock Q4-2018", "start": "2018-10-01"},
]


def _build_signal_with_lags(components, lags, keys=None, weights=None):
    """Build composite signal applying publication lags. Uses production signal type."""
    if keys is None:
        keys = _PROD_KEYS
    if weights is None:
        weights = _PROD_WEIGHTS

    # Use first component's full index and ffill others (matches Signal Validation)
    base_idx = next(iter(components.values())).index

    comp = pd.Series(0.0, index=base_idx)
    for k in keys:
        if k not in components:
            continue
        s = components[k]
        lag = lags.get(k, 0)
        lagged = s.shift(lag) if lag > 0 else s
        comp += weights[k] * lagged.reindex(base_idx, method="ffill").fillna(0)

    signal = _SIG_FN(comp).dropna()  # Uses production signal type (mom6)
    return signal, comp


def _expanding_quintile_series(signal):
    """Expanding-window quintiles (no future info)."""
    quintiles = pd.Series(3, index=signal.index, dtype=int)
    for i in range(20, len(signal)):
        hist = signal.iloc[:i+1]
        pct = float((hist <= hist.iloc[-1]).mean()) * 100
        quintiles.iloc[i] = 1 if pct < 20 else 2 if pct < 40 else 3 if pct < 60 else 4 if pct < 80 else 5
    return quintiles


def _backtest(quintiles, spy_ret, alloc_map, vix_data=None, target_vol=0.10, apply_vol_scaling=True):
    """Run backtest from quintile series. Vol-scaling is optional."""
    common = quintiles.index.intersection(spy_ret.index)
    q = quintiles.reindex(common)
    r = spy_ret.reindex(common)
    w = q.map(alloc_map).astype(float)

    if apply_vol_scaling and vix_data is not None and len(vix_data) > 12:
        vix_m = vix_data.resample("MS").last().dropna() / 100
        realized = r.rolling(5, min_periods=3).std() * np.sqrt(12)
        realized = realized.clip(lower=0.05)
        vix_al = vix_m.reindex(common, method="ffill")
        vol = vix_al.fillna(realized).clip(lower=0.05)
        vs = (target_vol / vol).clip(upper=2.0)
        w = (w * vs).clip(0, 1)

    port_ret = r * w
    eq = (1 + port_ret).cumprod()
    years = len(port_ret) / 12
    ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
    ann_vol = float(port_ret.std() * np.sqrt(12))
    sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 1e-8 else 0
    sort = sortino_ratio(port_ret)
    peak = eq.expanding().max()
    max_dd = round(float(((eq - peak) / peak).min()) * 100, 1)
    total = round(float(eq.iloc[-1] - 1) * 100, 1)
    return {"sharpe": sharpe, "sortino": sort, "max_dd": max_dd,
            "total_return": total, "ann_return": round(ann_ret * 100, 2)}, port_ret


def _check_crashes(quintiles):
    """Check quintile at each crash onset. Return per-event detail."""
    detected = 0
    details = []
    for event in TAIL_EVENTS:
        d = pd.Timestamp(event["start"])
        d_before = d - pd.DateOffset(months=1)
        q_at = int(quintiles.get(d, 3)) if d in quintiles.index else None
        q_before = int(quintiles.get(d_before, 3)) if d_before in quintiles.index else None
        was_def = (q_at is not None and q_at >= 4) or (q_before is not None and q_before >= 4)
        if was_def:
            detected += 1
        details.append({"event": event["name"], "q_at_start": q_at,
                         "q_before": q_before, "detected": was_def})
    return detected, details


def _monte_carlo_sharpe(signal, spy_ret, alloc_map, vix_data, n_perms=5000):
    """Monte Carlo: shuffle signal, compute null Sharpe distribution."""
    quintiles = _expanding_quintile_series(signal)
    real_metrics, _ = _backtest(quintiles, spy_ret, alloc_map, vix_data)
    real_sharpe = real_metrics["sharpe"]

    common = quintiles.index.intersection(spy_ret.index)
    q_vals = quintiles.reindex(common).values
    r_vals = spy_ret.reindex(common).values

    null_sharpes = np.empty(n_perms)
    for i in range(n_perms):
        shuf_q = np.random.permutation(q_vals)
        w = np.array([alloc_map.get(int(q), 1.0) for q in shuf_q])
        pr = r_vals * w
        eq_c = np.cumprod(1 + pr)
        yrs = len(pr) / 12
        ar = float(eq_c[-1] ** (1 / max(yrs, 0.5)) - 1) if eq_c[-1] > 0 else 0
        av = float(np.std(pr) * np.sqrt(12))
        null_sharpes[i] = round(ar / av, 3) if av > 1e-8 else 0
        if (i + 1) % 1000 == 0:
            print(f"[MC] {i+1}/{n_perms}")

    p_value = float(np.mean(null_sharpes >= real_sharpe))
    return {
        "real_sharpe": real_sharpe,
        "p_value": round(p_value, 4),
        "null_mean": round(float(np.mean(null_sharpes)), 3),
        "null_std": round(float(np.std(null_sharpes)), 3),
    }


def run_realtime_validation(ratio_series, spy_monthly, vix_data=None):
    """Run real-time simulation with MC tests and per-crash quintile detail."""
    components = _extract_components(ratio_series)
    missing = [k for k in _PROD_KEYS if k not in components]
    if missing:
        return {"error": f"Missing: {missing}"}

    spy_ret = spy_monthly.pct_change().dropna()
    no_lags = {k: 0 for k in _PROD_KEYS}

    # --- Run all 4 variants, both unscaled and vol-scaled ---
    print(f"[REALTIME] Signal type: {_SIG_TYPE}")
    variants = []

    # 5F Full
    print("[REALTIME] 5F Full Data...")
    sig_5f_full, _ = _build_signal_with_lags(components, no_lags)
    q_5f_full = _expanding_quintile_series(sig_5f_full)
    m_5f_full_raw, ret_5f_full_raw = _backtest(q_5f_full, spy_ret, _ALLOC, vix_data, apply_vol_scaling=False)
    m_5f_full_vs, ret_5f_full_vs = _backtest(q_5f_full, spy_ret, _ALLOC, vix_data, apply_vol_scaling=True)
    c_5f_full, cd_5f_full = _check_crashes(q_5f_full)

    # 5F Real-Time
    print("[REALTIME] 5F Real-Time (Qty=6M lag, M2=1M lag)...")
    sig_5f_rt, _ = _build_signal_with_lags(components, PUBLICATION_LAGS_REALISTIC)
    q_5f_rt = _expanding_quintile_series(sig_5f_rt)
    m_5f_rt_raw, ret_5f_rt_raw = _backtest(q_5f_rt, spy_ret, _ALLOC, vix_data, apply_vol_scaling=False)
    m_5f_rt_vs, ret_5f_rt_vs = _backtest(q_5f_rt, spy_ret, _ALLOC, vix_data, apply_vol_scaling=True)
    c_5f_rt, cd_5f_rt = _check_crashes(q_5f_rt)

    # 4F (drop quantity_signal)
    keys_4f = ["m2_signal", "spread_signal", "dollar_stress_signal", "rate_signal"]
    weights_4f = {k: 0.25 for k in keys_4f}

    print("[REALTIME] 4F Full Data (no Qty)...")
    sig_4f_full, _ = _build_signal_with_lags(components, no_lags, keys_4f, weights_4f)
    q_4f_full = _expanding_quintile_series(sig_4f_full)
    m_4f_full_raw, ret_4f_full_raw = _backtest(q_4f_full, spy_ret, _ALLOC, vix_data, apply_vol_scaling=False)
    m_4f_full_vs, ret_4f_full_vs = _backtest(q_4f_full, spy_ret, _ALLOC, vix_data, apply_vol_scaling=True)
    c_4f_full, cd_4f_full = _check_crashes(q_4f_full)

    print("[REALTIME] 4F Real-Time (M2=1M lag)...")
    sig_4f_rt, _ = _build_signal_with_lags(components, {"m2_signal": 1}, keys_4f, weights_4f)
    q_4f_rt = _expanding_quintile_series(sig_4f_rt)
    m_4f_rt_raw, ret_4f_rt_raw = _backtest(q_4f_rt, spy_ret, _ALLOC, vix_data, apply_vol_scaling=False)
    m_4f_rt_vs, ret_4f_rt_vs = _backtest(q_4f_rt, spy_ret, _ALLOC, vix_data, apply_vol_scaling=True)
    c_4f_rt, cd_4f_rt = _check_crashes(q_4f_rt)

    # --- Build equity curves (UNSCALED — the production model) ---
    common_dates = ret_5f_full_raw.index.intersection(ret_5f_rt_raw.index).intersection(ret_4f_rt_raw.index).intersection(spy_ret.index)
    common_dates = sorted(common_dates)
    eq_5f_full_raw = (1 + ret_5f_full_raw.reindex(common_dates).fillna(0)).cumprod()
    eq_5f_rt_raw = (1 + ret_5f_rt_raw.reindex(common_dates).fillna(0)).cumprod()
    eq_4f_full_raw = (1 + ret_4f_full_raw.reindex(common_dates).fillna(0)).cumprod()
    eq_4f_rt_raw = (1 + ret_4f_rt_raw.reindex(common_dates).fillna(0)).cumprod()
    eq_bh = (1 + spy_ret.reindex(common_dates).fillna(0)).cumprod()

    chart = []
    for d in common_dates:
        chart.append({
            "date": d.strftime("%Y-%m-%d"),
            "f5_full": round(float(eq_5f_full_raw[d]), 4),
            "f5_rt": round(float(eq_5f_rt_raw[d]), 4),
            "f4_full": round(float(eq_4f_full_raw[d]), 4),
            "f4_rt": round(float(eq_4f_rt_raw[d]), 4),
            "buyhold": round(float(eq_bh[d]), 4),
        })

    # --- Monte Carlo for 5F-RT and 4F-RT (unscaled) ---
    print("[REALTIME] Monte Carlo 5F Real-Time (5000 shuffles, unscaled)...")
    mc_5f_rt = _monte_carlo_sharpe(sig_5f_rt, spy_ret, _ALLOC, None, n_perms=5000)
    print(f"[REALTIME] 5F-RT MC: p={mc_5f_rt['p_value']}")

    print("[REALTIME] Monte Carlo 4F Real-Time (5000 shuffles, unscaled)...")
    mc_4f_rt = _monte_carlo_sharpe(sig_4f_rt, spy_ret, _ALLOC, None, n_perms=5000)
    print(f"[REALTIME] 4F-RT MC: p={mc_4f_rt['p_value']}")

    # --- Quintile agreement ---
    common = q_5f_full.index.intersection(q_5f_rt.index)
    q_agree = round(float((q_5f_full.reindex(common) == q_5f_rt.reindex(common)).mean()) * 100, 1)
    sig_corr = round(float(sig_5f_full.reindex(common).corr(sig_5f_rt.reindex(common))), 3)

    # --- Per-crash quintile matrix ---
    crash_matrix = []
    for i, event in enumerate(TAIL_EVENTS):
        crash_matrix.append({
            "event": event["name"],
            "5f_full_q": cd_5f_full[i]["q_at_start"],
            "5f_full_q_before": cd_5f_full[i]["q_before"],
            "5f_full_detected": cd_5f_full[i]["detected"],
            "5f_rt_q": cd_5f_rt[i]["q_at_start"],
            "5f_rt_q_before": cd_5f_rt[i]["q_before"],
            "5f_rt_detected": cd_5f_rt[i]["detected"],
            "4f_full_q": cd_4f_full[i]["q_at_start"],
            "4f_full_q_before": cd_4f_full[i]["q_before"],
            "4f_full_detected": cd_4f_full[i]["detected"],
            "4f_rt_q": cd_4f_rt[i]["q_at_start"],
            "4f_rt_q_before": cd_4f_rt[i]["q_before"],
            "4f_rt_detected": cd_4f_rt[i]["detected"],
        })

    # Print crash matrix for diagnostics
    print("\n[REALTIME] === CRASH QUINTILE MATRIX ===")
    for cm in crash_matrix:
        print(f"  {cm['event']:20s} | 5F-Full: Q{cm['5f_full_q']}(Q{cm['5f_full_q_before']} before) {'✓' if cm['5f_full_detected'] else '✗'} "
              f"| 5F-RT: Q{cm['5f_rt_q']}(Q{cm['5f_rt_q_before']} before) {'✓' if cm['5f_rt_detected'] else '✗'} "
              f"| 4F-Full: Q{cm['4f_full_q']}(Q{cm['4f_full_q_before']} before) {'✓' if cm['4f_full_detected'] else '✗'} "
              f"| 4F-RT: Q{cm['4f_rt_q']}(Q{cm['4f_rt_q_before']} before) {'✓' if cm['4f_rt_detected'] else '✗'}")

    sharpe_deg = round(m_5f_full_raw["sharpe"] - m_5f_rt_raw["sharpe"], 3)

    if c_5f_rt >= 4 and abs(sharpe_deg) < 0.1:
        verdict = "SAFE — real-time signal maintains 4/4 crash detection with minimal Sharpe degradation."
        forward_fill_safe = True
    elif c_5f_rt >= 4 and abs(sharpe_deg) < 0.3:
        verdict = "ACCEPTABLE — crash detection preserved but moderate Sharpe degradation."
        forward_fill_safe = True
    elif c_5f_rt < 4:
        verdict = f"WARNING — 5F real-time misses {4 - c_5f_rt} crash(es). BIS lag matters. Consider 4F fallback ({c_4f_rt}/4 with 4F-RT)."
        forward_fill_safe = False
    else:
        verdict = f"DEGRADED — Sharpe drops {sharpe_deg:.3f}."
        forward_fill_safe = False

    def _row(label, m_raw, m_vs, crashes, lags, mc_p=None):
        return {
            "model": label, "crashes": f"{crashes}/4", "lags": lags, "mc_p": mc_p,
            "sharpe": m_raw["sharpe"], "sortino": m_raw["sortino"],
            "max_dd": m_raw["max_dd"], "total_return": m_raw["total_return"],
            "ann_return": m_raw["ann_return"],
            "sharpe_vs": m_vs["sharpe"], "sortino_vs": m_vs["sortino"],
            "max_dd_vs": m_vs["max_dd"], "total_return_vs": m_vs["total_return"],
        }

    comparison = [
        _row("5F Full Data", m_5f_full_raw, m_5f_full_vs, c_5f_full, "None"),
        _row("5F Real-Time", m_5f_rt_raw, m_5f_rt_vs, c_5f_rt, "Qty=6M, M2=1M", mc_5f_rt["p_value"]),
        _row("4F Full Data", m_4f_full_raw, m_4f_full_vs, c_4f_full, "None"),
        _row("4F Real-Time", m_4f_rt_raw, m_4f_rt_vs, c_4f_rt, "M2=1M only", mc_4f_rt["p_value"]),
    ]

    print(f"\n[REALTIME] Verdict: {verdict}")
    return {
        "comparison": comparison,
        "crash_matrix": crash_matrix,
        "chart": chart,
        "quintile_agreement_pct": q_agree,
        "signal_correlation": sig_corr,
        "sharpe_degradation": sharpe_deg,
        "monte_carlo_5f_rt": mc_5f_rt,
        "monte_carlo_4f_rt": mc_4f_rt,
        "verdict": verdict,
        "forward_fill_safe": forward_fill_safe,
        "signal_type": _SIG_TYPE,
    }
