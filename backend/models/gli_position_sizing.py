"""Track 3 — Portfolio Construction Layer for GLI 3FA model.

Holds the signal fixed, improves how signal maps to position size:
- Asymmetric response: concave on long side, binary on short
- Volatility scaling: target-vol sizing using realized SPY vol
- Drawdown circuit breaker: reduce position when trailing DD > threshold
- Signal smoothing: EMA to reduce turnover/whipsaw
"""

import numpy as np
import pandas as pd

from .backtest_engine import (
    _extract_components, SIGNAL_TRANSFORMS, PRODUCTION_MODELS,
    ALLOCATION_RULES,
)

_3FA = PRODUCTION_MODELS["3fa"]
_3FA_KEYS = _3FA["keys"]
_3FA_WEIGHTS = _3FA["weights"]
_SIG_FN = SIGNAL_TRANSFORMS["mom6"][1]


def _build_3fa_signal(components):
    """Build production 3FA Mom6M signal."""
    base_idx = components[_3FA_KEYS[0]].index
    for k in _3FA_KEYS[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()

    comp = pd.Series(0.0, index=base_idx)
    for k in _3FA_KEYS:
        if k in components:
            comp += _3FA_WEIGHTS[k] * components[k].reindex(base_idx, method="ffill").fillna(0)
    return _SIG_FN(comp).dropna()


def _metrics(port_ret, spy_ret):
    """Compute Sharpe, MaxDD, Calmar, turnover from return series."""
    eq = (1 + port_ret).cumprod()
    bh = (1 + spy_ret).cumprod()
    years = len(port_ret) / 12

    ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
    ann_vol = float(port_ret.std() * np.sqrt(12))
    sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 1e-8 else 0

    peak = eq.expanding().max()
    max_dd = round(float(((eq - peak) / peak).min()) * 100, 1)
    calmar = round(ann_ret / abs(max_dd / 100), 2) if abs(max_dd) > 0.1 else 0

    bh_ann = float(bh.iloc[-1] ** (1 / max(years, 0.5)) - 1) if bh.iloc[-1] > 0 else 0
    bh_vol = float(spy_ret.std() * np.sqrt(12))
    bh_sharpe = round(bh_ann / bh_vol, 3) if bh_vol > 1e-8 else 0
    bh_peak = bh.expanding().max()
    bh_dd = round(float(((bh - bh_peak) / bh_peak).min()) * 100, 1)

    return {
        "sharpe": sharpe,
        "ann_return": round(ann_ret * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "max_dd": max_dd,
        "calmar": calmar,
        "bh_sharpe": bh_sharpe,
        "bh_max_dd": bh_dd,
    }


def baseline_quintile(signal, spy_ret):
    """Baseline: quintile-based allocation (aggressive preset)."""
    alloc = ALLOCATION_RULES["aggressive"]
    aligned = pd.concat([signal.rename("sig"), spy_ret.rename("ret")], axis=1).dropna()
    if len(aligned) < 30:
        return None, None, None

    try:
        q = pd.qcut(aligned["sig"], 5, labels=[1, 2, 3, 4, 5], duplicates='drop')
    except Exception:
        return None, None, None

    weights = q.map(alloc).astype(float)
    port_ret = aligned["ret"] * weights
    turnover = weights.diff().abs().mean()

    return port_ret, aligned["ret"], round(float(turnover), 4)


def asymmetric_response(signal, spy_ret, cap=0.8):
    """Signal < 0 → 0% equity. Signal > 0 → sqrt scaling capped at cap.

    Rationale: liquidity withdrawal is reliably negative; expansion is less reliably positive.
    """
    aligned = pd.concat([signal.rename("sig"), spy_ret.rename("ret")], axis=1).dropna()
    if len(aligned) < 30:
        return None, None, None

    pct = aligned["sig"].rank(pct=True)
    weights = pd.Series(0.0, index=aligned.index)
    positive = pct > 0.5
    # Concave (sqrt) mapping on positive side
    weights[positive] = np.sqrt((pct[positive] - 0.5) * 2) * cap
    weights[~positive] = 0.0

    port_ret = aligned["ret"] * weights
    turnover = weights.diff().abs().mean()
    return port_ret, aligned["ret"], round(float(turnover), 4)


def vol_scaled(signal, spy_monthly, vix_data, target_vol=0.12):
    """Scale position by target_vol / realized_vol.

    Uses VIX as real-time vol proxy (no lookahead — VIX is observable).
    """
    spy_ret = spy_monthly.pct_change().dropna()
    aligned = pd.concat([signal.rename("sig"), spy_ret.rename("ret")], axis=1).dropna()
    if len(aligned) < 30 or vix_data is None:
        return None, None, None

    # VIX is annualized vol in %. Convert to decimal.
    vix_m = vix_data.resample("MS").last().dropna() / 100
    vix_aligned = vix_m.reindex(aligned.index, method="ffill")

    # Quintile allocation
    alloc = ALLOCATION_RULES["aggressive"]
    try:
        q = pd.qcut(aligned["sig"], 5, labels=[1, 2, 3, 4, 5], duplicates='drop')
    except Exception:
        return None, None, None

    base_weights = q.map(alloc).astype(float)

    # Vol scaling: multiply base position by (target / realized)
    vol_scalar = target_vol / vix_aligned.clip(lower=0.05)  # Floor at 5% vol
    vol_scalar = vol_scalar.clip(upper=2.0)  # Cap at 2x leverage
    weights = (base_weights * vol_scalar).clip(upper=1.0)  # No leverage after scaling

    port_ret = aligned["ret"] * weights
    turnover = weights.diff().abs().mean()
    return port_ret, aligned["ret"], round(float(turnover), 4)


def drawdown_control(signal, spy_ret, dd_threshold=-10, recovery=-5, reduce_to=0.5):
    """Circuit breaker: if trailing 3M return < threshold, reduce to reduce_to
    until recovery to recovery level."""
    alloc = ALLOCATION_RULES["aggressive"]
    aligned = pd.concat([signal.rename("sig"), spy_ret.rename("ret")], axis=1).dropna()
    if len(aligned) < 30:
        return None, None, None

    try:
        q = pd.qcut(aligned["sig"], 5, labels=[1, 2, 3, 4, 5], duplicates='drop')
    except Exception:
        return None, None, None

    base_weights = q.map(alloc).astype(float)
    port_ret_base = aligned["ret"] * base_weights

    # Rolling 3M return
    roll_3m = (1 + port_ret_base).rolling(3).apply(lambda x: x.prod() - 1, raw=True) * 100

    weights = base_weights.copy()
    in_breaker = False
    for i in range(3, len(weights)):
        r3 = roll_3m.iloc[i] if not np.isnan(roll_3m.iloc[i]) else 0
        if r3 < dd_threshold and not in_breaker:
            in_breaker = True
        elif r3 > recovery and in_breaker:
            in_breaker = False
        if in_breaker:
            weights.iloc[i] = base_weights.iloc[i] * reduce_to

    port_ret = aligned["ret"] * weights
    turnover = weights.diff().abs().mean()
    return port_ret, aligned["ret"], round(float(turnover), 4)


def signal_smoothing(signal, spy_ret, halflife=2):
    """EMA smoothing to reduce turnover."""
    alloc = ALLOCATION_RULES["aggressive"]
    smoothed = signal.ewm(halflife=halflife).mean()
    aligned = pd.concat([smoothed.rename("sig"), spy_ret.rename("ret")], axis=1).dropna()
    if len(aligned) < 30:
        return None, None, None

    try:
        q = pd.qcut(aligned["sig"], 5, labels=[1, 2, 3, 4, 5], duplicates='drop')
    except Exception:
        return None, None, None

    weights = q.map(alloc).astype(float)
    port_ret = aligned["ret"] * weights
    turnover = weights.diff().abs().mean()
    return port_ret, aligned["ret"], round(float(turnover), 4)


def run_position_analysis(ratio_series, spy_monthly, vix_data=None):
    """Run all portfolio construction variants.

    Returns comparison table: baseline vs each variant.
    """
    components = _extract_components(ratio_series)
    missing = [k for k in _3FA_KEYS if k not in components]
    if missing:
        return {"error": f"Missing components: {missing}"}

    signal = _build_3fa_signal(components)
    spy_ret = spy_monthly.pct_change().dropna()

    print(f"[POSITION] Signal: {len(signal)} pts")
    variants = []

    # Baseline
    pr, sr, to = baseline_quintile(signal, spy_ret)
    if pr is not None:
        m = _metrics(pr, sr)
        m["turnover"] = to
        m["net_sharpe"] = round(m["sharpe"] - to * 0.001 * 12, 3)  # ~10bps cost × turnover × 12
        variants.append({"name": "Baseline (quintile)", **m})
        print(f"[POSITION] Baseline: Sharpe={m['sharpe']}, DD={m['max_dd']}%")

    # Asymmetric response
    for cap in [0.6, 0.8, 1.0]:
        pr, sr, to = asymmetric_response(signal, spy_ret, cap=cap)
        if pr is not None:
            m = _metrics(pr, sr)
            m["turnover"] = to
            m["net_sharpe"] = round(m["sharpe"] - to * 0.001 * 12, 3)
            variants.append({"name": f"Asymmetric (cap={int(cap*100)}%)", **m})

    # Vol scaling (requires VIX)
    if vix_data is not None and len(vix_data) > 60:
        for tv in [0.10, 0.12, 0.15]:
            pr, sr, to = vol_scaled(signal, spy_monthly, vix_data, target_vol=tv)
            if pr is not None:
                m = _metrics(pr, sr)
                m["turnover"] = to
                m["net_sharpe"] = round(m["sharpe"] - to * 0.001 * 12, 3)
                variants.append({"name": f"Vol-scaled ({int(tv*100)}% target)", **m})
    else:
        print("[POSITION] Skipping vol-scaling — no VIX data")

    # Drawdown control
    for thresh, recov in [(-10, -5), (-7, -3), (-15, -7)]:
        pr, sr, to = drawdown_control(signal, spy_ret, dd_threshold=thresh, recovery=recov)
        if pr is not None:
            m = _metrics(pr, sr)
            m["turnover"] = to
            m["net_sharpe"] = round(m["sharpe"] - to * 0.001 * 12, 3)
            variants.append({"name": f"DD breaker ({thresh}%/{recov}%)", **m})

    # Signal smoothing
    for hl in [1, 2, 3]:
        pr, sr, to = signal_smoothing(signal, spy_ret, halflife=hl)
        if pr is not None:
            m = _metrics(pr, sr)
            m["turnover"] = to
            m["net_sharpe"] = round(m["sharpe"] - to * 0.001 * 12, 3)
            variants.append({"name": f"EMA smooth (hl={hl}M)", **m})

    # Sort by Sharpe descending
    variants.sort(key=lambda x: x.get("sharpe", 0), reverse=True)

    # Mark best
    if variants:
        variants[0]["is_best"] = True

    baseline = next((v for v in variants if v["name"] == "Baseline (quintile)"), None)

    print(f"[POSITION] {len(variants)} variants tested")
    return {
        "variants": variants,
        "baseline": baseline,
        "best": variants[0] if variants else None,
        "improvement": round(variants[0]["sharpe"] - baseline["sharpe"], 3) if variants and baseline else None,
    }


if __name__ == "__main__":
    print("=" * 60)
    print("GLI 3FA Portfolio Construction Analysis")
    print("=" * 60)
    print("Call run_position_analysis(ratio_series, spy_monthly, vix_data)")
