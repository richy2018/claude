"""Dealer gamma [MODEL] — Black-Scholes re-pricing spot sweep.

Everything in this module is a MODEL output, not an observation. The inventory
assumption (config.GAMMA_ASSUMPTION_TEXT) is: dealers long call OI, short put
OI. The dealer-long-call share `a` parameterises how much of that assumption
to believe: net dealer gamma at hypothetical spot S is

    net(S) = [ (2a-1) * Σ_calls γ_i(S)·OI_i  -  Σ_puts γ_i(S)·OI_i ] · mult

so a=1.00 reproduces the baseline (+calls −puts), a=0.50 zeroes the call book,
a=0.25 makes dealers net short calls. Crossings are listed per scenario and
NEVER collapsed to a single point estimate.

γ_i(S) re-prices Black-Scholes gamma at each hypothetical spot using the
contract's own snapshot IV (held fixed across the sweep — stated limitation).

Dollar gamma units: gamma × OI × 100 × S² × 0.01 = "$ per 1% move".
"""

import math
import datetime as dt

from .config import (
    RISK_FREE, DIV_YIELD, SWEEP_LO, SWEEP_HI, SWEEP_STEP, A_SCENARIOS,
    CONTRACT_MULT,
)

_MIN_T = 0.5 / 365.0   # floor on time-to-expiry (half a day) so 0DTE doesn't blow up


def _phi(x: float) -> float:
    """Standard normal pdf."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_gamma(S: float, K: float, T: float, sigma: float,
             r: float = RISK_FREE, q: float = DIV_YIELD) -> float:
    """Black-Scholes gamma (same for calls and puts), with dividend yield q.

    gamma = e^{-qT} · φ(d1) / (S · σ · √T)
    """
    if S <= 0 or K <= 0 or sigma <= 0:
        return 0.0
    T = max(T, _MIN_T)
    sqT = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqT)
    return math.exp(-q * T) * _phi(d1) / (S * sigma * sqT)


def years_to_expiry(expiry: str, asof: str) -> float:
    """Calendar days / 365 from asof to expiry (both YYYY-MM-DD)."""
    d = (dt.date.fromisoformat(expiry) - dt.date.fromisoformat(asof)).days
    return max(d, 0) / 365.0


def sweep_spots(spot: float):
    """Hypothetical spot grid: −15%..+15% in 0.5% steps (inclusive)."""
    n = int(round((SWEEP_HI - SWEEP_LO) / SWEEP_STEP))
    return [spot * (1.0 + SWEEP_LO + i * SWEEP_STEP) for i in range(n + 1)]


def run_sweep(contracts, spot: float, asof: str, a_scenarios=A_SCENARIOS):
    """Full spot sweep over the filtered contract set.

    contracts: dicts with strike, expiry, ctype ('call'|'put'), oi, iv.
    Contracts missing iv or oi are skipped and counted (reported, per the
    no-silent-fabrication rule).

    Returns {spots, curves: {a: [net $γ per 1% move]}, crossings: {a: [spot...]},
             gross_at_spot, net_at_spot: {a: value}, skipped: {count, oi}}.
    """
    usable = []
    skipped = 0
    skipped_oi = 0
    for c in contracts:
        if c.get("iv") and c.get("oi"):
            usable.append((float(c["strike"]),
                           years_to_expiry(c["expiry"], asof),
                           c["ctype"], float(c["oi"]), float(c["iv"])))
        else:
            skipped += 1
            skipped_oi += int(c.get("oi") or 0)

    spots = sweep_spots(spot)
    call_sum = [0.0] * len(spots)   # Σ γ_i(S)·OI_i over calls, per sweep point
    put_sum = [0.0] * len(spots)

    for K, T, ctype, oi, iv in usable:
        target = call_sum if ctype == "call" else put_sum
        for i, S in enumerate(spots):
            target[i] += bs_gamma(S, K, T, iv) * oi

    def dollarize(raw, S):
        # gamma × OI already summed in raw; × 100 (mult) × S² × 0.01
        return raw * CONTRACT_MULT * S * S * 0.01

    curves = {}
    crossings = {}
    for a in a_scenarios:
        w_call = 2.0 * a - 1.0
        curve = [dollarize(w_call * call_sum[i] - put_sum[i], spots[i])
                 for i in range(len(spots))]
        curves[f"{a:.2f}"] = curve
        crossings[f"{a:.2f}"] = find_zero_crossings(spots, curve)

    # values at (nearest grid point to) current spot
    at_idx = min(range(len(spots)), key=lambda i: abs(spots[i] - spot))
    gross_at_spot = dollarize(call_sum[at_idx] + put_sum[at_idx], spots[at_idx])
    net_at_spot = {a_key: curves[a_key][at_idx] for a_key in curves}

    return {
        "spots": [round(s, 2) for s in spots],
        "curves": {k: [round(v, 0) for v in v_list] for k, v_list in curves.items()},
        "crossings": {k: [round(x, 2) for x in v] for k, v in crossings.items()},
        "gross_at_spot": round(gross_at_spot, 0),
        "net_at_spot": {k: round(v, 0) for k, v in net_at_spot.items()},
        "n_contracts_used": len(usable),
        "skipped": {"count": skipped, "oi": skipped_oi},
        "units": "$ gamma per 1% move",
    }


def find_zero_crossings(xs, ys):
    """Spot levels where the curve crosses zero (linear interpolation between
    grid points). Exact zeros on a grid point are reported once."""
    out = []
    for i in range(1, len(xs)):
        y0, y1 = ys[i - 1], ys[i]
        if y0 == 0.0 and (not out or out[-1] != xs[i - 1]):
            out.append(xs[i - 1])
        elif (y0 < 0 < y1) or (y0 > 0 > y1):
            frac = abs(y0) / (abs(y0) + abs(y1))
            out.append(xs[i - 1] + frac * (xs[i] - xs[i - 1]))
    if ys and ys[-1] == 0.0 and (not out or out[-1] != xs[-1]):
        out.append(xs[-1])
    return out
