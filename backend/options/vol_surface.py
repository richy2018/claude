"""Volatility surface (delta x tenor grid + per-expiry smiles) from stored chain rows.

Tier-1 surface: every input here is ALREADY in contract_day (vendor `iv` and
`delta` per contract per snapshot date) — no new API access, no backfill.

Reads RAW rows, not the hygiene-filtered positioning set. The ±20% band and the
vol/OI stale filter are correct for OI aggregates but would delete the wings,
and the wings are the surface. An IV-QUALITY filter is applied instead, and
every exclusion is counted and reported.

Two products:
  smiles  IV vs strike/delta for the expiries nearest SURFACE_SMILE_TENORS
  grid    constant-maturity delta x tenor grid, interpolated LINEAR IN TOTAL
          VARIANCE (sigma^2 * T) between bracketing expiries — the same method
          and the same ATM definition as surface.atm_iv_30d, so the grid's
          ATM/30d cell equals the "ATM IV 30D" card exactly.

Honesty rules (same as the rest of the module):
  - No quotes on this plan: IV is vendor-computed from last prints, not mids.
    Stated in the payload's `limits`, never implied to be mid-market.
  - r/q are constants (RISK_FREE/DIV_YIELD); that degrades with tenor, so
    expiries past SURFACE_MAX_DTE are EXCLUDED and counted, not shown as
    reliable numbers.
  - A raw grid can violate no-arbitrage. Calendar (total variance
    non-decreasing) and butterfly (price convexity) checks RUN and their
    violations are REPORTED — never smoothed away, never silently dropped.
  - A cell with no bracketing data is None (renders as blank/PENDING), never
    extrapolated.
"""

import datetime as dt

from .config import (
    RISK_FREE, DIV_YIELD, IV_INVERT_LO, IV_INVERT_HI, SURFACE_TENORS,
    SURFACE_DELTAS, SURFACE_SMILE_TENORS, SURFACE_MAX_DTE, SURFACE_MIN_PER_SIDE,
    SURFACE_BUTTERFLY_TOL,
)
from .iv_inversion import bs_price
# Reuse the live-surface helpers so the grid's ATM row is the SAME definition
# as the ATM IV 30d card (strike nearest spot, mean of call+put IV).
from .surface import _atm_iv, _days

METHOD_TENOR = ("Constant-maturity interpolation between bracketing expiries, "
                "linear in total variance (sigma^2*T).")
METHOD_DELTA = ("Per-expiry IV interpolated linearly in |delta| using the chain's "
                "own delta; no extrapolation beyond the observed delta range.")
METHOD_ATM = "ATM = mean IV of the call+put at the strike nearest spot (same as the ATM IV card)."


def _quality(rows, spot):
    """Split raw chain rows into surface-usable / excluded, with reasons counted."""
    keep = []
    excl = {"no_iv": 0, "no_delta": 0, "iv_out_of_range": 0,
            "expired_or_0dte": 0, "beyond_max_dte": 0}
    for r in rows:
        iv = r.get("iv")
        if iv is None:
            excl["no_iv"] += 1
            continue
        if not (IV_INVERT_LO <= iv <= IV_INVERT_HI):
            excl["iv_out_of_range"] += 1
            continue
        if r.get("delta") is None:
            excl["no_delta"] += 1
            continue
        keep.append(r)
    return keep, excl


def _slice_by_expiry(rows, asof):
    """{expiry: rows} for expiries with a positive DTE inside SURFACE_MAX_DTE.
    Returns (slices, counts) where counts records the tenor-based exclusions."""
    slices = {}
    counts = {"expired_or_0dte": 0, "beyond_max_dte": 0}
    for r in rows:
        d = _days(r["expiry"], asof)
        if d <= 0:
            counts["expired_or_0dte"] += 1
            continue
        if d > SURFACE_MAX_DTE:
            counts["beyond_max_dte"] += 1
            continue
        slices.setdefault(r["expiry"], []).append(r)
    return slices, counts


def _iv_at_abs_delta(rows, ctype, target):
    """IV at |delta| = target for one expiry/side, linear in |delta|.

    Returns None when the target sits outside the observed delta range — the
    wings are not extrapolated.
    """
    pts = {}
    for r in rows:
        if r["ctype"] != ctype:
            continue
        d, iv = r.get("delta"), r.get("iv")
        if d is None or iv is None:
            continue
        ad = round(abs(d), 6)
        pts.setdefault(ad, []).append(iv)
    if len(pts) < 2:
        return None
    xs = sorted(pts)
    ys = [sum(pts[x]) / len(pts[x]) for x in xs]
    if target < xs[0] or target > xs[-1]:
        return None
    for i in range(1, len(xs)):
        if xs[i] >= target:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (target - x0) / (x1 - x0)
    return ys[-1]


def _interp_variance(d1, v1, d2, v2, target):
    """Interpolate a vol (decimal) to `target` DTE, linear in total variance."""
    if v1 is None or v2 is None:
        return None
    if d1 == d2:
        return v1
    t1, t2, tt = d1 / 365.0, d2 / 365.0, target / 365.0
    tv1, tv2 = v1 * v1 * t1, v2 * v2 * t2
    tv = tv1 + (tv2 - tv1) * (tt - t1) / (t2 - t1)
    if tv <= 0 or tt <= 0:
        return None
    return (tv / tt) ** 0.5


def _column_labels():
    puts = [f"{int(d * 100)}dP" for d in sorted(SURFACE_DELTAS, reverse=True)]
    calls = [f"{int(d * 100)}dC" for d in sorted(SURFACE_DELTAS, reverse=True)]
    return puts + ["ATM"] + list(reversed(calls))


def _slice_points(expiry, rows, spot, asof):
    """Per-expiry column values (the raw slice the grid interpolates between)."""
    calls = [r for r in rows if r["ctype"] == "call"]
    puts = [r for r in rows if r["ctype"] == "put"]
    if len(calls) < SURFACE_MIN_PER_SIDE or len(puts) < SURFACE_MIN_PER_SIDE:
        return None
    vals = {"ATM": _atm_iv(rows, spot)}
    for d in SURFACE_DELTAS:
        vals[f"{int(d * 100)}dP"] = _iv_at_abs_delta(puts, "put", d)
        vals[f"{int(d * 100)}dC"] = _iv_at_abs_delta(calls, "call", d)
    if vals["ATM"] is None:
        return None
    return {"expiry": expiry, "days": _days(expiry, asof), "values": vals,
            "n_calls": len(calls), "n_puts": len(puts)}


def _build_grid(slices_pts, labels):
    """Constant-maturity grid rows: one per SURFACE_TENORS target."""
    pts = sorted(slices_pts, key=lambda p: p["days"])
    out = []
    for tenor in SURFACE_TENORS:
        lower = [p for p in pts if p["days"] <= tenor]
        upper = [p for p in pts if p["days"] >= tenor]
        if not (lower and upper):
            out.append({"tenor": tenor, "cells": {c: None for c in labels},
                        "status": "no bracketing expiry"})
            continue
        lo, hi = lower[-1], upper[0]
        cells = {}
        for c in labels:
            v = _interp_variance(lo["days"], lo["values"].get(c),
                                 hi["days"], hi["values"].get(c), tenor)
            cells[c] = round(v * 100, 2) if v is not None else None
        out.append({"tenor": tenor, "cells": cells, "status": "ok",
                    "between": [lo["expiry"], hi["expiry"]]})
    return out


def _calendar_violations(slices_pts):
    """ATM total variance must be non-decreasing in tenor. Report where it isn't."""
    pts = sorted([p for p in slices_pts if p["values"].get("ATM")],
                 key=lambda p: p["days"])
    out = []
    for i in range(1, len(pts)):
        a, b = pts[i - 1], pts[i]
        tv_a = a["values"]["ATM"] ** 2 * a["days"] / 365.0
        tv_b = b["values"]["ATM"] ** 2 * b["days"] / 365.0
        if tv_b < tv_a:
            out.append({"from": a["expiry"], "to": b["expiry"],
                        "atm_iv_from": round(a["values"]["ATM"] * 100, 2),
                        "atm_iv_to": round(b["values"]["ATM"] * 100, 2)})
    return out


def _butterfly_violations(slices, spot, asof, max_report=8):
    """Price-space convexity check on equally-spaced strike triples.

    For K1<K2<K3 equally spaced, a call butterfly C1 - 2*C2 + C3 must be >= 0.
    Prices are re-struck from each contract's own IV at constant r/q, so this
    tests the SURFACE's internal consistency (what we display), not the vendor's
    quotes. Violations are reported, never smoothed.
    """
    found = []
    checked = 0
    for expiry, rows in slices.items():
        calls = sorted([r for r in rows if r["ctype"] == "call" and r.get("iv")],
                       key=lambda r: r["strike"])
        T = _days(expiry, asof) / 365.0
        if T <= 0 or len(calls) < 3:
            continue
        for i in range(2, len(calls)):
            a, b, c = calls[i - 2], calls[i - 1], calls[i]
            g1, g2 = b["strike"] - a["strike"], c["strike"] - b["strike"]
            if g1 <= 0 or abs(g1 - g2) > 1e-6:
                continue                      # only equally-spaced triples
            checked += 1
            p = [bs_price(spot, r["strike"], T, r["iv"], "call", RISK_FREE, DIV_YIELD)
                 for r in (a, b, c)]
            fly = p[0] - 2 * p[1] + p[2]
            if fly < SURFACE_BUTTERFLY_TOL:
                if len(found) < max_report:
                    found.append({"expiry": expiry,
                                  "strikes": [a["strike"], b["strike"], c["strike"]],
                                  "butterfly": round(fly, 4)})
                else:
                    found.append(None)        # counted, not detailed
    detailed = [f for f in found if f]
    return {"checked_triples": checked, "violations": len(found),
            "examples": detailed}


def build_surface(rows, spot, asof):
    """Full surface payload from raw contract_day rows for one snapshot date."""
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    base = {"asof": asof, "spot": spot, "generated_at": generated_at,
            "methods": {"tenor": METHOD_TENOR, "delta": METHOD_DELTA, "atm": METHOD_ATM}}
    if not rows or not spot:
        return {**base, "status": "empty",
                "reason": "no stored contracts or no spot for this date"}

    quality, excl = _quality(rows, spot)
    slices, tenor_excl = _slice_by_expiry(quality, asof)
    excl.update(tenor_excl)

    slice_pts = []
    thin = 0
    for expiry, srows in slices.items():
        p = _slice_points(expiry, srows, spot, asof)
        if p:
            slice_pts.append(p)
        else:
            thin += 1

    if not slice_pts:
        return {**base, "status": "empty",
                "reason": "no expiry had enough quality contracts on both sides",
                "coverage": {"input_rows": len(rows), "quality_rows": len(quality),
                             "excluded": excl, "thin_expiries": thin}}

    labels = _column_labels()
    grid = _build_grid(slice_pts, labels)

    # smiles for the expiries nearest the display tenors (raw observations)
    smiles = []
    for target in SURFACE_SMILE_TENORS:
        cands = [p for p in slice_pts]
        if not cands:
            continue
        pick = min(cands, key=lambda p: abs(p["days"] - target))
        if any(s["expiry"] == pick["expiry"] for s in smiles):
            continue
        pts = []
        for r in sorted(slices[pick["expiry"]], key=lambda r: r["strike"]):
            pts.append({"strike": r["strike"], "ctype": r["ctype"],
                        "iv": round(r["iv"] * 100, 2),
                        "delta": round(r["delta"], 4),
                        "moneyness": round(r["strike"] / spot - 1, 4)})
        smiles.append({"expiry": pick["expiry"], "days": pick["days"],
                       "target_tenor": target, "points": pts})

    return {
        **base,
        "status": "ok",
        "columns": labels,
        "tenors": list(SURFACE_TENORS),
        "grid": grid,
        "slices": [{k: p[k] for k in ("expiry", "days", "n_calls", "n_puts")}
                   for p in sorted(slice_pts, key=lambda p: p["days"])],
        "smiles": smiles,
        "coverage": {
            "input_rows": len(rows),
            "quality_rows": len(quality),
            "expiries_used": len(slice_pts),
            "expiries_thin": thin,
            "excluded": excl,
        },
        "arbitrage": {
            "calendar_violations": _calendar_violations(slice_pts),
            "butterfly": _butterfly_violations(slices, spot, asof),
        },
        "limits": {
            "quotes": "no quotes on this plan — IV is vendor-computed from last "
                      "prints, not bid/ask mids",
            "rates": f"r={RISK_FREE}, q={DIV_YIELD} held constant; expiries beyond "
                     f"{SURFACE_MAX_DTE}d excluded rather than shown as reliable",
            "recency": "one EOD snapshot per session — no intraday surface evolution",
            "arbitrage": "raw grid; calendar/butterfly violations are reported, not smoothed",
        },
    }
