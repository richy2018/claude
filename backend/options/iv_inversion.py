"""Black-Scholes price, delta, and implied-vol inversion.

Used by the surface reconstruction (scripts/backfill_surface.py) to rebuild
historical IV from each contract's daily CLOSE price — the tier gives historical
prices/greeks but a constant-maturity IV series has to be reconstructed. This
module is pure math; the honesty rules live in the caller (reconstructed IV is
always labelled 'reconstructed', never blended with live vendor IV unlabelled).

Constants (r, q) are passed in by the caller and match the gamma model
(RISK_FREE=0.04, DIV_YIELD=0.015) so reconstructed and live surfaces share one
convention.
"""

import math

from .config import RISK_FREE, DIV_YIELD, IV_INVERT_LO, IV_INVERT_HI

_SQRT2 = math.sqrt(2.0)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def _d1(S, K, T, sigma, r, q):
    return (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))


def bs_price(S, K, T, sigma, ctype, r=RISK_FREE, q=DIV_YIELD):
    """Black-Scholes European option price. ctype in {'call','put'}."""
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return 0.0
    d1 = _d1(S, K, T, sigma, r, q)
    d2 = d1 - sigma * math.sqrt(T)
    disc_s = S * math.exp(-q * T)
    disc_k = K * math.exp(-r * T)
    if ctype == "call":
        return disc_s * _norm_cdf(d1) - disc_k * _norm_cdf(d2)
    return disc_k * _norm_cdf(-d2) - disc_s * _norm_cdf(-d1)


def bs_delta(S, K, T, sigma, ctype, r=RISK_FREE, q=DIV_YIELD):
    """Black-Scholes delta (call in [0,1], put in [-1,0])."""
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return None
    d1 = _d1(S, K, T, sigma, r, q)
    edq = math.exp(-q * T)
    return edq * _norm_cdf(d1) if ctype == "call" else -edq * _norm_cdf(-d1)


def implied_vol(price, S, K, T, ctype, r=RISK_FREE, q=DIV_YIELD,
                lo=IV_INVERT_LO, hi=IV_INVERT_HI):
    """Invert an option CLOSE price to implied vol by bisection.

    Returns None for junk the spec says to discard:
      - non-positive price, or price below (discounted) intrinsic
      - price not attainable within the [lo, hi] vol bracket (i.e. implied vol
        outside 3%..150%) — these are stale/zero-bid quality marks.
    """
    if price is None or price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return None
    intrinsic = max(S * math.exp(-q * T) - K * math.exp(-r * T), 0.0) if ctype == "call" \
        else max(K * math.exp(-r * T) - S * math.exp(-q * T), 0.0)
    if price < intrinsic - 1e-8:
        return None

    def f(sig):
        return bs_price(S, K, T, sig, ctype, r, q) - price

    f_lo, f_hi = f(lo), f(hi)
    if f_lo > 0 or f_hi < 0:      # outside the admissible vol range → discard
        return None
    a, b = lo, hi
    for _ in range(80):
        mid = 0.5 * (a + b)
        fm = f(mid)
        if abs(fm) < 1e-8:
            return mid
        if fm > 0:
            b = mid
        else:
            a = mid
    return 0.5 * (a + b)
