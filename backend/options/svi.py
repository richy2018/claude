"""SVI (raw) per-maturity slice fit with a butterfly no-arbitrage repair.

The raw last-print IV grid has ~27% butterfly violations (no quotes, stalest in
far-OTM/long-dated strikes). We do NOT force the raw prints arbitrage-free;
instead we fit a smooth SVI slice per maturity and repair butterfly violations,
so a second, arbitrage-free surface sits alongside the raw one (B2).

Parameterisation (Gatheral raw SVI), total variance vs log-moneyness k=log(K/F):
    w(k) = a + b*( rho*(k-m) + sqrt((k-m)^2 + sigma^2) )

Butterfly no-arbitrage ⟺ the Gatheral function g(k) ≥ 0 everywhere. After the
least-squares fit we shrink b (the wing weight) until g ≥ 0 on a dense grid —
a monotone lever (b→0 gives flat vol, g→1>0), so it always terminates. We then
report the residual violation count. This is SVI-per-slice with a butterfly
repair (not a full Fengler spline); stated as such in the payload.
"""

import math

_MIN_W = 1e-8


def svi_w(p, k):
    a, b, rho, m, sig = p
    x = k - m
    return a + b * (rho * x + math.sqrt(x * x + sig * sig))


def _svi_derivs(p, k):
    a, b, rho, m, sig = p
    x = k - m
    R = math.sqrt(x * x + sig * sig)
    w = a + b * (rho * x + R)
    wp = b * (rho + x / R)
    wpp = b * sig * sig / (R ** 3)
    return max(w, _MIN_W), wp, wpp


def gatheral_g(p, k):
    """g(k) ≥ 0 ⟺ no butterfly arbitrage at k."""
    w, wp, wpp = _svi_derivs(p, k)
    return (1 - k * wp / (2 * w)) ** 2 - (wp * wp / 4.0) * (1.0 / w + 0.25) + wpp / 2.0


def count_butterfly_violations(p, ks):
    return sum(1 for k in ks if gatheral_g(p, k) < 0)


def fit_slice(ks, ws):
    """Least-squares SVI fit of total variances ws at log-moneyness ks, then a
    butterfly repair. Returns (params, n_violations_after) or (None, None) if
    the slice is too thin to fit."""
    pts = [(k, w) for k, w in zip(ks, ws) if w is not None and w > 0]
    if len(pts) < 5:
        return None, None
    ks2 = [k for k, _ in pts]
    ws2 = [w for _, w in pts]
    p = _fit(ks2, ws2)
    if p is None:
        return None, None
    # dense grid over the observed range for the repair check
    lo, hi = min(ks2), max(ks2)
    grid = [lo + (hi - lo) * i / 60.0 for i in range(61)] if hi > lo else ks2
    a, b, rho, m, sig = p
    for _ in range(200):
        if count_butterfly_violations((a, b, rho, m, sig), grid) == 0:
            break
        b *= 0.97                       # shrink wing weight until arb-free
        if b < 1e-6:
            break
    p = (a, b, rho, m, sig)
    return p, count_butterfly_violations(p, grid)


def _fit(ks, ws):
    try:
        import numpy as np
        from scipy.optimize import least_squares
    except Exception:
        return None
    kk = np.array(ks)
    ww = np.array(ws)
    a0 = max(float(ww.min()), 1e-6)
    p0 = [a0, 0.1, -0.3, 0.0, 0.1]
    lb = [0.0, 0.0, -0.999, kk.min() - 1.0, 1e-3]
    ub = [max(float(ww.max()), a0 + 1.0), 10.0, 0.999, kk.max() + 1.0, 5.0]
    # clamp p0 into bounds
    p0 = [min(max(v, lo), hi) for v, lo, hi in zip(p0, lb, ub)]

    def resid(p):
        return [svi_w(p, k) - w for k, w in zip(ks, ws)]

    try:
        sol = least_squares(resid, p0, bounds=(lb, ub), max_nfev=2000)
        return tuple(sol.x)
    except Exception:
        return None
