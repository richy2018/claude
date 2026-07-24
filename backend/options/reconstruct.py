"""Reconstruct one day's constant-maturity surface from historical closes.

Pure functions (no I/O) so they are unit-testable and reused by
scripts/backfill_surface.py. For a single trade date, given the underlying
close and the SPX contracts in the RECON_DTE band with their daily close
prices, this:

  1. inverts Black-Scholes on each close -> IV (junk discarded by iv_inversion),
  2. computes, per expiry: ATM IV, 25Δ put IV, 25Δ call IV (delta from the
     inverted IV), then
  3. interpolates each to the 30d constant maturity LINEAR IN TOTAL VARIANCE
     (sigma^2 * T) across the two bracketing expiries — the same method the live
     surface uses, stated in a UI tooltip.

Output matches the live surface row shape so both feed one percentile pool:
  {atm_iv_30d (vol %), rr_25d_norm, term (list), n_ivs}
"""

import math

from .config import (RISK_FREE, DIV_YIELD, RECON_DTE_LO, RECON_DTE_HI,
                     RECON_TARGET_DTE)
from .iv_inversion import implied_vol, bs_delta


def _interp_variance(d1, m1, d2, m2, target):
    """Linear-in-total-variance interpolation of a vol metric between two DTEs.
    m* are vols (decimal). Returns the vol at `target` DTE."""
    if d1 == d2:
        return m1
    t1, t2, tt = d1 / 365.0, d2 / 365.0, target / 365.0
    v1, v2 = m1 * m1 * t1, m2 * m2 * t2
    vt = v1 + (v2 - v1) * (tt - t1) / (t2 - t1)
    if vt <= 0 or tt <= 0:
        return None
    return math.sqrt(vt / tt)


def _expiry_points(contracts, spot, asof, r, q):
    """Per-expiry {days, atm, put25, call25} from inverted IVs, for expiries in
    the DTE band. `contracts`: dicts with strike, expiry, ctype, close, days."""
    from datetime import date
    by_exp = {}
    for c in contracts:
        d = c["days"]
        if not (RECON_DTE_LO <= d <= RECON_DTE_HI):
            continue
        T = d / 365.0
        iv = implied_vol(c.get("close"), spot, c["strike"], T, c["ctype"], r, q)
        if iv is None:
            continue
        delta = bs_delta(spot, c["strike"], T, iv, c["ctype"], r, q)
        by_exp.setdefault(d, []).append(
            {"strike": c["strike"], "ctype": c["ctype"], "iv": iv, "delta": delta})
    points = []
    for d, rows in by_exp.items():
        atm = _atm(rows, spot)
        put25 = _nearest_delta([x for x in rows if x["ctype"] == "put"], -0.25)
        call25 = _nearest_delta([x for x in rows if x["ctype"] == "call"], 0.25)
        if atm is None:
            continue
        points.append({"days": d, "atm": atm, "put25": put25, "call25": call25})
    points.sort(key=lambda p: p["days"])
    return points


def _atm(rows, spot):
    if not rows:
        return None
    nearest = min(rows, key=lambda r: abs(r["strike"] - spot))
    at = [r["iv"] for r in rows if r["strike"] == nearest["strike"] and r["iv"]]
    return sum(at) / len(at) if at else None


def _nearest_delta(rows, target):
    rows = [r for r in rows if r.get("delta") is not None]
    if not rows:
        return None
    return min(rows, key=lambda r: abs(r["delta"] - target))["iv"]


def _bracket(points, target):
    lower = [p for p in points if p["days"] <= target]
    upper = [p for p in points if p["days"] >= target]
    if lower and upper:
        return lower[-1], upper[0]
    picks = sorted(points, key=lambda p: abs(p["days"] - target))[:2]
    if len(picks) < 2:
        return (picks[0], picks[0]) if picks else (None, None)
    return tuple(sorted(picks, key=lambda p: p["days"]))


def reconstruct_day(contracts, spot, asof, r=RISK_FREE, q=DIV_YIELD,
                    target=RECON_TARGET_DTE):
    """Return the constant-maturity surface row for one day, or None if the DTE
    band yields too little to interpolate."""
    points = _expiry_points(contracts, spot, asof, r, q)
    if not points:
        return None
    lo, hi = _bracket(points, target)
    if lo is None:
        return None

    atm30 = _interp_variance(lo["days"], lo["atm"], hi["days"], hi["atm"], target)
    if atm30 is None:
        return None

    rr = None
    if lo.get("put25") and lo.get("call25") and hi.get("put25") and hi.get("call25"):
        put30 = _interp_variance(lo["days"], lo["put25"], hi["days"], hi["put25"], target)
        call30 = _interp_variance(lo["days"], lo["call25"], hi["days"], hi["call25"], target)
        if put30 and call30 and atm30 > 0:
            rr = round((put30 - call30) / atm30, 4)

    n_ivs = sum(1 for _ in points)
    return {
        "atm_iv_30d": round(atm30 * 100, 2),
        "rr_25d_norm": rr,
        "term": [{"days": p["days"], "atm_iv": round(p["atm"] * 100, 2)} for p in points],
        "n_expiries": n_ivs,
    }


def validation_mad(reconstructed, live):
    """Mean absolute difference (vol points) of reconstructed vs live ATM IV over
    shared dates. Returns (mad, n_overlap). n_overlap 0 -> mad None."""
    shared = [d for d in reconstructed if d in live
              and reconstructed[d] is not None and live[d] is not None]
    if not shared:
        return None, 0
    diffs = [abs(reconstructed[d] - live[d]) for d in shared]
    return sum(diffs) / len(diffs), len(diffs)
