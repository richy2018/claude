"""Positioning metrics — hygiene filters, ΔOI, P/C, tops, percentiles.

Hard rules encoded here (spec §2/§4):
  - Hygiene filters run BEFORE any aggregate; exclusions are counted and
    reported, never silently dropped.
  - The stale filter (volume/OI < 0.10) exists so dead LEAPS OI is never read
    as live positioning.
  - ΔOI is the object of interest; OI level is never emitted without its Δ
    alongside once history exists. With no prior session, Δ fields are
    PENDING — never fabricated.
  - Volume is reported in its own table, never mixed into OI claims.
  - No holder-type attribution, no motive language, in any label produced here.
"""

import datetime as dt

from .config import BAND_PCT, STALE_VOL_OI, BUCKETS, PERCENTILE_MIN_SESSIONS


# ── hygiene ──────────────────────────────────────────────────────────────────
def apply_hygiene(rows, spot: float, avg_vol=None):
    """Split a day's contract rows into kept / excluded sets.

    The stale test is volume/OI < 0.10. With `avg_vol` ({ticker: trailing avg
    volume}) supplied it uses a 5-session average volume (B3) so a single quiet
    day doesn't flag a live strike; otherwise it falls back to today's 1-day
    volume. The basis used is reported.

    Returns (kept, report) where report = {
      band:   {count, oi}   strikes outside ±20% of spot
      stale:  {count, oi}   volume/OI below threshold (dead/legacy OI)
      missing_oi: {count}   rows the API returned without OI at all
      stale_basis: str      which volume basis the stale test used
    }
    """
    kept = []
    band = {"count": 0, "oi": 0}
    stale = {"count": 0, "oi": 0}
    missing = {"count": 0}
    lo, hi = spot * (1 - BAND_PCT), spot * (1 + BAND_PCT)
    for r in rows:
        oi = r.get("oi")
        if oi is None:
            missing["count"] += 1
            continue
        if not (lo <= r["strike"] <= hi):
            band["count"] += 1
            band["oi"] += oi
            continue
        vol = avg_vol.get(r["ticker"]) if avg_vol is not None else (r.get("volume") or 0)
        vol = vol or 0
        ratio = (vol / oi) if oi > 0 else (float("inf") if vol > 0 else 0.0)
        if ratio < STALE_VOL_OI:
            stale["count"] += 1
            stale["oi"] += oi
            continue
        kept.append(r)
    basis = "5-session avg volume/OI" if avg_vol is not None else "1-session volume/OI"
    return kept, {"band": band, "stale": stale, "missing_oi": missing,
                  "band_pct": BAND_PCT, "stale_threshold": STALE_VOL_OI,
                  "stale_basis": basis}


def band_in_contracts(rows, spot: float):
    """Rows within the ±band with OI present, INCLUDING stale strikes — the set
    for the UNFILTERED gamma view (B1). A contract that didn't trade today is
    still open and still hedged, so gamma (exposure that exists) uses all in-band
    OI, unlike positioning (what traded)."""
    lo, hi = spot * (1 - BAND_PCT), spot * (1 + BAND_PCT)
    return [r for r in rows if r.get("oi") is not None and lo <= r["strike"] <= hi]


def bucket_of(days_to_expiry: int) -> str:
    for name, lo, hi in BUCKETS:
        if lo <= days_to_expiry <= hi:
            return name
    return BUCKETS[-1][0]


def _days(expiry: str, asof: str) -> int:
    return (dt.date.fromisoformat(expiry) - dt.date.fromisoformat(asof)).days


# ── ΔOI + aggregates ─────────────────────────────────────────────────────────
def delta_oi_rows(kept, prior_oi: dict | None, prior5_oi: dict | None, asof: str):
    """Attach d1/d5 ΔOI per contract. A contract absent from a prior session
    counts from 0 (it IS new OI). If the prior *session* doesn't exist at all,
    the delta is None (PENDING), never fabricated."""
    out = []
    for r in kept:
        d1 = (r["oi"] - prior_oi.get(r["ticker"], 0)) if prior_oi is not None else None
        d5 = (r["oi"] - prior5_oi.get(r["ticker"], 0)) if prior5_oi is not None else None
        rr = dict(r)
        rr["doi_1d"] = d1
        rr["doi_5d"] = d5
        rr["days"] = _days(r["expiry"], asof)
        rr["bucket"] = bucket_of(rr["days"])
        out.append(rr)
    return out


def bucket_aggregates(rows):
    """Per (bucket) put/call sums of OI, ΔOI 1d/5d, volume + P/C OI ratio."""
    agg = {name: {"call": _zero(), "put": _zero()} for name, _, _ in BUCKETS}
    for r in rows:
        cell = agg[r["bucket"]][r["ctype"]]
        cell["oi"] += r["oi"]
        cell["volume"] += r.get("volume") or 0
        if r["doi_1d"] is not None:
            cell["doi_1d"] = (cell["doi_1d"] or 0) + r["doi_1d"]
        if r["doi_5d"] is not None:
            cell["doi_5d"] = (cell["doi_5d"] or 0) + r["doi_5d"]
    for name in agg:
        c, p = agg[name]["call"], agg[name]["put"]
        agg[name]["pc_oi_ratio"] = round(p["oi"] / c["oi"], 3) if c["oi"] else None
    return agg


def _zero():
    return {"oi": 0, "volume": 0, "doi_1d": None, "doi_5d": None}


def top_delta_strikes(rows, spot: float, n: int = 15):
    """Top |ΔOI 5d| contracts with % from spot, expiry, vol/OI."""
    scored = [r for r in rows if r["doi_5d"] is not None]
    scored.sort(key=lambda r: abs(r["doi_5d"]), reverse=True)
    out = []
    for r in scored[:n]:
        out.append({
            "ticker": r["ticker"],
            "strike": r["strike"],
            "pct_from_spot": round((r["strike"] / spot - 1) * 100, 2),
            "expiry": r["expiry"],
            "ctype": r["ctype"],
            "oi": r["oi"],
            "doi_5d": r["doi_5d"],
            "doi_1d": r["doi_1d"],
            "vol_oi": round((r.get("volume") or 0) / r["oi"], 3) if r["oi"] else None,
        })
    return out


def top_volume_strikes(rows, spot: float, n: int = 10):
    """Top strikes by total day volume — a separate table, never mixed into OI
    claims (volume is activity, not positioning)."""
    by_strike = {}
    for r in rows:
        key = r["strike"]
        cell = by_strike.setdefault(key, {"strike": key, "volume": 0,
                                          "call_volume": 0, "put_volume": 0})
        v = r.get("volume") or 0
        cell["volume"] += v
        cell[f"{r['ctype']}_volume"] += v
    ranked = sorted(by_strike.values(), key=lambda c: c["volume"], reverse=True)[:n]
    for c in ranked:
        c["pct_from_spot"] = round((c["strike"] / spot - 1) * 100, 2)
    return ranked


# ── percentile helper (PENDING until enough sessions) ────────────────────────
def percentile_of(value, history):
    """Percentile of `value` within `history` (list of floats, may be short).

    Returns {value, percentile, sessions, status} — status is 'ok' once
    PERCENTILE_MIN_SESSIONS sessions exist, else 'PENDING' with percentile
    None. Never a bare number from thin history."""
    hist = [h for h in history if h is not None]
    sessions = len(hist)
    if value is None:
        return {"value": None, "percentile": None, "sessions": sessions, "status": "PENDING"}
    if sessions < PERCENTILE_MIN_SESSIONS:
        return {"value": value, "percentile": None, "sessions": sessions, "status": "PENDING"}
    below = sum(1 for h in hist if h <= value)
    return {"value": value, "percentile": round(100.0 * below / sessions, 1),
            "sessions": sessions, "status": "ok"}


def surface_percentiles(surf_hist, rv30, current):
    """Pooled (reconstructed + live) pricing percentiles (§3).

    surf_hist : [(date, {atm_iv_30d, rr_25d_norm, source})] ascending
    rv30      : {date: 30d RV %} — to build the historical VRP series
    current   : {atm_iv_30d, rr_25d, vrp} latest live values
    Returns {atm_iv_30d, rr_25d, vrp}: percentile_of results. The current live
    value already sits at the end of surf_hist, so it is excluded once from its
    own comparison history."""
    atm = [(d, v["atm_iv_30d"]) for d, v in surf_hist if v["atm_iv_30d"] is not None]
    rr = [(d, v["rr_25d_norm"]) for d, v in surf_hist if v["rr_25d_norm"] is not None]
    vrp = [(d, round(v["atm_iv_30d"] - rv30[d], 2)) for d, v in surf_hist
           if v["atm_iv_30d"] is not None and d in rv30]
    out = {}
    for label, series, cur in (("atm_iv_30d", atm, current.get("atm_iv_30d")),
                               ("rr_25d", rr, current.get("rr_25d")),
                               ("vrp", vrp, current.get("vrp"))):
        vals = [v for _, v in series]
        hist = vals[:-1] if vals and cur is not None and vals[-1] == cur else vals
        out[label] = percentile_of(cur, hist)
    return out
