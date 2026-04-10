"""GLI Real-Time Signal Validation — Publication Lag Simulation.

Tests whether the 5F model survives when each factor is lagged by its
real-world publication delay. Credit (BIS) has 6-month lag.
Also tests a 4F fallback model (drops Credit entirely).
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
_ALLOC = ALLOCATION_RULES["production"]  # 100/100/100/10/10

# Publication lags in months (how many months old is the latest available data)
PUBLICATION_LAGS = {
    "quantity_signal": 0,       # WALCL: weekly, ~0M at monthly resolution
    "m2_signal": 1,             # M2SL: monthly, ~1M lag
    "spread_signal": 0,        # BAMLH0A0HYM2: daily, ~0M
    "dollar_stress_signal": 0,  # Xccy basis: weekly, ~0M
    "rate_signal": 0,          # Fed Funds: daily, ~0M
}

# BIS credit is embedded in quantity_signal via the debt ratio
# The real lag is on the BIS total credit data which feeds the ratio
# quantity_signal = z-score of BIS ratio RoC — BIS data has 6M lag
# So quantity_signal in practice has ~6M lag, not 0
PUBLICATION_LAGS_REALISTIC = {
    "quantity_signal": 6,       # BIS ratio: quarterly + 3-6M publication delay
    "m2_signal": 1,
    "spread_signal": 0,
    "dollar_stress_signal": 0,
    "rate_signal": 0,
}

TAIL_EVENTS = [
    {"name": "GFC", "start": "2007-09-01"},
    {"name": "COVID", "start": "2020-02-01"},
    {"name": "Rate Shock", "start": "2022-01-01"},
    {"name": "Vol Shock Q4-2018", "start": "2018-10-01"},
]


def _build_signal_with_lags(components, lags, keys=None, weights=None):
    """Build composite signal applying publication lags to each factor.

    For each factor at month t, use the value from month t - lag.
    """
    if keys is None:
        keys = _PROD_KEYS
    if weights is None:
        weights = _PROD_WEIGHTS

    # Find common base index
    base_idx = components[keys[0]].index
    for k in keys[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()

    comp = pd.Series(0.0, index=base_idx)
    for k in keys:
        if k not in components:
            continue
        s = components[k]
        lag = lags.get(k, 0)
        if lag > 0:
            # At month t, use value from month t-lag (shift forward = use older data)
            lagged = s.shift(lag)
        else:
            lagged = s
        comp += weights[k] * lagged.reindex(base_idx, method="ffill").fillna(0)

    signal = _signal_momentum(comp, 1).dropna()  # 1M momentum
    return signal, comp


def _expanding_quintile_series(signal):
    """Expanding-window quintiles (no future info)."""
    quintiles = pd.Series(3, index=signal.index, dtype=int)
    for i in range(20, len(signal)):
        hist = signal.iloc[:i+1]
        pct = float((hist <= hist.iloc[-1]).mean()) * 100
        quintiles.iloc[i] = 1 if pct < 20 else 2 if pct < 40 else 3 if pct < 60 else 4 if pct < 80 else 5
    return quintiles


def _backtest(quintiles, spy_ret, alloc_map, vix_data=None, target_vol=0.10):
    """Run backtest from quintile series."""
    common = quintiles.index.intersection(spy_ret.index)
    q = quintiles.reindex(common)
    r = spy_ret.reindex(common)
    w = q.map(alloc_map).astype(float)

    if vix_data is not None and len(vix_data) > 12:
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
            "total_return": total, "ann_return": round(ann_ret * 100, 2)}


def _check_crashes(quintiles):
    """Check if signal was Q4+ at each crash onset."""
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


def run_realtime_validation(ratio_series, spy_monthly, vix_data=None):
    """Run real-time simulation: compare full-data vs lagged backtests."""
    components = _extract_components(ratio_series)
    missing = [k for k in _PROD_KEYS if k not in components]
    if missing:
        return {"error": f"Missing: {missing}"}

    spy_ret = spy_monthly.pct_change().dropna()

    # --- Full data (no lags — current backtest) ---
    print("[REALTIME] Building full-data signal (no lags)...")
    sig_full, _ = _build_signal_with_lags(components, {k: 0 for k in _PROD_KEYS})
    q_full = _expanding_quintile_series(sig_full)
    m_full = _backtest(q_full, spy_ret, _ALLOC, vix_data)
    crashes_full, crash_det_full = _check_crashes(q_full)

    # --- Real-time simulated (with publication lags) ---
    print("[REALTIME] Building real-time simulated signal (with lags)...")
    sig_rt, _ = _build_signal_with_lags(components, PUBLICATION_LAGS_REALISTIC)
    q_rt = _expanding_quintile_series(sig_rt)
    m_rt = _backtest(q_rt, spy_ret, _ALLOC, vix_data)
    crashes_rt, crash_det_rt = _check_crashes(q_rt)

    # --- Quintile agreement ---
    common = q_full.index.intersection(q_rt.index)
    q_agree = float((q_full.reindex(common) == q_rt.reindex(common)).mean()) * 100
    sig_corr = float(sig_full.reindex(common).corr(sig_rt.reindex(common)))

    print(f"[REALTIME] Full: Sharpe={m_full['sharpe']}, Crashes={crashes_full}/4")
    print(f"[REALTIME] RT:   Sharpe={m_rt['sharpe']}, Crashes={crashes_rt}/4")
    print(f"[REALTIME] Agreement: {q_agree:.1f}%, Corr: {sig_corr:.3f}")
    print(f"[REALTIME] Sharpe degradation: {m_full['sharpe'] - m_rt['sharpe']:.3f}")

    # --- 4F fallback (drop quantity_signal which carries BIS lag) ---
    print("[REALTIME] Building 4F fallback (no BIS/Credit)...")
    keys_4f = ["m2_signal", "spread_signal", "dollar_stress_signal", "rate_signal"]
    weights_4f = {k: 0.25 for k in keys_4f}
    # 4F with no lags
    sig_4f_full, _ = _build_signal_with_lags(components, {k: 0 for k in keys_4f}, keys_4f, weights_4f)
    q_4f_full = _expanding_quintile_series(sig_4f_full)
    m_4f_full = _backtest(q_4f_full, spy_ret, _ALLOC, vix_data)
    crashes_4f, crash_det_4f = _check_crashes(q_4f_full)
    # 4F with realistic lags (only M2 has 1M lag, rest are real-time)
    sig_4f_rt, _ = _build_signal_with_lags(components, {"m2_signal": 1}, keys_4f, weights_4f)
    q_4f_rt = _expanding_quintile_series(sig_4f_rt)
    m_4f_rt = _backtest(q_4f_rt, spy_ret, _ALLOC, vix_data)
    crashes_4f_rt, crash_det_4f_rt = _check_crashes(q_4f_rt)

    print(f"[REALTIME] 4F full: Sharpe={m_4f_full['sharpe']}, Crashes={crashes_4f}/4")
    print(f"[REALTIME] 4F RT:   Sharpe={m_4f_rt['sharpe']}, Crashes={crashes_4f_rt}/4")

    sharpe_deg = round(m_full["sharpe"] - m_rt["sharpe"], 3)

    # Determine signal confidence
    if crashes_rt >= 4 and abs(sharpe_deg) < 0.1:
        verdict = "SAFE — real-time signal maintains 4/4 crash detection with minimal Sharpe degradation. Forward-fill is safe."
        forward_fill_safe = True
    elif crashes_rt >= 4 and abs(sharpe_deg) < 0.3:
        verdict = "ACCEPTABLE — crash detection preserved but moderate Sharpe degradation. Forward-fill with caution."
        forward_fill_safe = True
    elif crashes_rt < 4:
        verdict = f"WARNING — real-time signal misses {4 - crashes_rt} crash(es). BIS lag provides essential timing. Consider 4F fallback."
        forward_fill_safe = False
    else:
        verdict = f"DEGRADED — Sharpe drops {sharpe_deg:.3f}. The backtest materially overstates live performance."
        forward_fill_safe = False

    comparison = [
        {"model": "5F Full Data", **m_full, "crashes": f"{crashes_full}/4", "lags": "None"},
        {"model": "5F Real-Time", **m_rt, "crashes": f"{crashes_rt}/4", "lags": "Qty=6M, M2=1M"},
        {"model": "4F Full Data", **m_4f_full, "crashes": f"{crashes_4f}/4", "lags": "None"},
        {"model": "4F Real-Time", **m_4f_rt, "crashes": f"{crashes_4f_rt}/4", "lags": "M2=1M only"},
    ]

    return {
        "comparison": comparison,
        "quintile_agreement_pct": round(q_agree, 1),
        "signal_correlation": round(sig_corr, 3),
        "sharpe_degradation": sharpe_deg,
        "crashes_full": {"detected": crashes_full, "details": crash_det_full},
        "crashes_realtime": {"detected": crashes_rt, "details": crash_det_rt},
        "crashes_4f": {"detected": crashes_4f, "details": crash_det_4f},
        "verdict": verdict,
        "forward_fill_safe": forward_fill_safe,
        "publication_lags": PUBLICATION_LAGS_REALISTIC,
    }
