"""Surface (pricing) metrics — kept conceptually separate from positioning.

These are the ONLY metrics allowed to make "pricing" claims. Methods are
stated in the payload so the UI can show them in tooltips:
  - ATM IV 30d: interpolated between the two nearest expiries, LINEAR IN
    TOTAL VARIANCE (σ²·T), not in vol points.
  - 25Δ risk reversal, normalised by ATM: (25Δ put IV − 25Δ call IV) / ATM IV,
    at the expiry nearest 30 days (actual expiry stated).
  - Term structure: ATM IV at monthly (third-Friday) expiries out to ~100d;
    falls back to whatever expiries exist if no monthlies are in range.
  - Realised vol 10/20/30d close-to-close from OUR stored daily closes
    (forward-only store; never backfilled from third parties).
  - VRP = 30d ATM IV − 30d realised. Labelled: trailing realised is a proxy;
    windows non-coincident.
"""

import math
import datetime as dt

from .config import RV_WINDOWS

ATM_METHOD = "Interpolated between the two nearest expiries, linear in total variance (sigma^2*T)."
VRP_LABEL = "trailing realised is a proxy; windows non-coincident."
RV_METHOD = "close-to-close of ^GSPC (Yahoo), annualised x sqrt(252); underlying history seeded 5Y."


def _group_by_expiry(rows):
    by_exp = {}
    for r in rows:
        if r.get("iv"):
            by_exp.setdefault(r["expiry"], []).append(r)
    return by_exp


def _atm_iv(contracts, spot):
    """ATM IV for one expiry: mean IV of the call+put at the strike nearest spot."""
    if not contracts:
        return None
    nearest = min(contracts, key=lambda r: abs(r["strike"] - spot))
    at_strike = [r for r in contracts if r["strike"] == nearest["strike"]]
    ivs = [r["iv"] for r in at_strike if r.get("iv")]
    return sum(ivs) / len(ivs) if ivs else None


def _days(expiry, asof):
    return (dt.date.fromisoformat(expiry) - dt.date.fromisoformat(asof)).days


def atm_iv_30d(rows, spot, asof):
    """30d ATM IV via linear-in-variance interpolation between the two nearest
    expiries bracketing 30d (or the two nearest overall if none bracket)."""
    by_exp = _group_by_expiry(rows)
    pts = []
    for exp, cs in by_exp.items():
        d = _days(exp, asof)
        if d <= 0:
            continue
        iv = _atm_iv(cs, spot)
        if iv:
            pts.append((d, iv, exp))
    if not pts:
        return None
    pts.sort()
    target = 30
    lower = [p for p in pts if p[0] <= target]
    upper = [p for p in pts if p[0] >= target]
    if lower and upper:
        d1, iv1, _ = lower[-1]
        d2, iv2, _ = upper[0]
    else:
        picks = sorted(pts, key=lambda p: abs(p[0] - target))[:2]
        if len(picks) == 1:
            return round(picks[0][1] * 100, 2)
        (d1, iv1, _), (d2, iv2, _) = sorted(picks)
    if d1 == d2:
        return round(iv1 * 100, 2)
    t1, t2, t30 = d1 / 365.0, d2 / 365.0, target / 365.0
    v1, v2 = iv1 * iv1 * t1, iv2 * iv2 * t2          # total variances
    v30 = v1 + (v2 - v1) * (t30 - t1) / (t2 - t1)
    if v30 <= 0:
        return None
    return round(math.sqrt(v30 / t30) * 100, 2)


def risk_reversal_25d(rows, spot, asof):
    """(25Δ put IV − 25Δ call IV) / ATM IV at the expiry nearest 30d."""
    by_exp = _group_by_expiry(rows)
    cands = [(abs(_days(e, asof) - 30), e) for e in by_exp if _days(e, asof) > 0]
    if not cands:
        return None
    _, exp = min(cands)
    cs = by_exp[exp]
    calls = [r for r in cs if r["ctype"] == "call" and r.get("delta") is not None]
    puts = [r for r in cs if r["ctype"] == "put" and r.get("delta") is not None]
    atm = _atm_iv(cs, spot)
    if not calls or not puts or not atm:
        return None
    c25 = min(calls, key=lambda r: abs(r["delta"] - 0.25))
    p25 = min(puts, key=lambda r: abs(r["delta"] + 0.25))
    if not (c25.get("iv") and p25.get("iv")):
        return None
    return {"value": round((p25["iv"] - c25["iv"]) / atm, 4), "expiry": exp,
            "atm_iv": round(atm * 100, 2)}


def _is_third_friday(date_str):
    d = dt.date.fromisoformat(date_str)
    return d.weekday() == 4 and 15 <= d.day <= 21


def term_structure(rows, spot, asof, max_days=100):
    """ATM IV per monthly (third-Friday) expiry out to ~max_days; falls back to
    all available expiries if fewer than two monthlies are in range."""
    by_exp = _group_by_expiry(rows)
    entries = []
    for exp, cs in by_exp.items():
        d = _days(exp, asof)
        if 0 < d <= max_days:
            iv = _atm_iv(cs, spot)
            if iv:
                entries.append({"expiry": exp, "days": d,
                                "atm_iv": round(iv * 100, 2),
                                "monthly": _is_third_friday(exp)})
    entries.sort(key=lambda e: e["days"])
    monthlies = [e for e in entries if e["monthly"]]
    return monthlies if len(monthlies) >= 2 else entries[:8]


def dedup_closes(closes, tol=0.005):
    """Drop a close identical (within tol) to the immediately preceding kept
    close. ^GSPC to the cent never repeats on consecutive real sessions, so this
    only removes a weekend/holiday re-serve — the artifact that would otherwise
    inject a fake zero return and bias realised vol down."""
    out = []
    for d, c in closes:
        if c is None:
            continue
        if out and abs(c - out[-1][1]) < tol:
            continue
        out.append((d, c))
    return out


def rv30_by_date(closes, window=30):
    """{date: annualised 30d close-to-close RV %} for each date with a full
    trailing window. Used to build a historical VRP series (reconstructed IV −
    RV) so VRP percentiles pool with the reconstructed surface history."""
    closes = dedup_closes(closes)
    out = {}
    rets = []   # (date, logret) aligned to the LATER close
    for i in range(1, len(closes)):
        p0, p1 = closes[i - 1][1], closes[i][1]
        if p0 and p1 and p0 > 0:
            rets.append((closes[i][0], math.log(p1 / p0)))
    for i in range(len(rets)):
        if i + 1 < window:
            continue
        w = [r for _, r in rets[i + 1 - window:i + 1]]
        mean = sum(w) / window
        var = sum((r - mean) ** 2 for r in w) / (window - 1)
        out[rets[i][0]] = math.sqrt(var) * math.sqrt(252) * 100
    return out


def realised_vols(closes):
    """{window: annualised close-to-close vol % or None} from [(date, close)].
    None (→ PENDING) whenever the window isn't fully covered by our own store."""
    closes = dedup_closes(closes)
    out = {}
    rets = []
    for i in range(1, len(closes)):
        p0, p1 = closes[i - 1][1], closes[i][1]
        if p0 and p1 and p0 > 0:
            rets.append(math.log(p1 / p0))
    for w in RV_WINDOWS:
        if len(rets) < w:
            out[str(w)] = None
            continue
        window = rets[-w:]
        mean = sum(window) / w
        var = sum((r - mean) ** 2 for r in window) / (w - 1) if w > 1 else 0.0
        out[str(w)] = round(math.sqrt(var) * math.sqrt(252) * 100, 2)
    return out
