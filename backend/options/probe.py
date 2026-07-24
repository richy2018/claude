"""Massive.com capability probe — snapshot tier AND historical/flat-file reach.

This is the gate the whole module keys on. Two halves:

  probe_snapshot()  what today's chain snapshot returns per field (OI, IV,
                    greeks, quotes, trades, recency) — decides live features.
  probe_history()   what the plan exposes HISTORICALLY (expired-contract daily
                    aggregates, as-of contract listings, and — decisively —
                    whether ANY historical source carries per-contract-per-day
                    open interest). This decides whether ΔOI can be backfilled
                    (§4) or must stay forward-only, and whether surface IV can
                    be reconstructed from historical closes (§3).

Every historical check reports the endpoint it hit, the HTTP status, and a
short response snippet, so a wrong candidate path is legible as data ("404 on
this path") rather than a silent false. Booleans are set True only on positive
evidence — never assumed. The report is written to config.CAPABILITIES_PATH
(the persistent disk on Render, so it survives deploys) and read by the API to
gate features and by the frontend footer/banner.
"""

import json
import time
import datetime as dt

import requests

from .config import (
    MASSIVE_BASE_URL, UNDERLYING, CAPABILITIES_PATH, RECON_DTE_LO, RECON_DTE_HI,
)

TIMEOUT = 30


# ── HTTP helper ──────────────────────────────────────────────────────────────
def _get(url, params=None, api_key=None, max_retries=4, method="GET"):
    params = dict(params or {})
    if api_key:
        params["apiKey"] = api_key
    last = None
    for attempt in range(max_retries):
        try:
            last = requests.request(method, url, params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            return None, str(e)
        if last.status_code == 429:
            time.sleep(2 ** (attempt + 1))
            continue
        return last, None
    return last, None


def _snippet(resp):
    if resp is None:
        return None
    try:
        return json.dumps(resp.json())[:240]
    except Exception:
        return (resp.text or "")[:240]


def _ts_to_recency(ts_ns):
    if not ts_ns:
        return None
    ts = float(ts_ns)
    while ts > 1e12:
        ts /= 1000.0
    age_min = (time.time() - ts) / 60.0
    if age_min < 2:
        label = "real-time"
    elif age_min < 20:
        label = "~15-min delayed"
    elif age_min < 60 * 20:
        label = "intraday-stale or EOD"
    else:
        label = "EOD / previous session"
    return {"age_minutes": round(age_min, 1), "classification": label}


# ── snapshot tier probe ──────────────────────────────────────────────────────
def probe_snapshot(api_key: str) -> dict:
    resp, err = _get(f"{MASSIVE_BASE_URL}/v3/snapshot/options/{UNDERLYING}",
                     params={"limit": 10}, api_key=api_key)
    status = resp.status_code if resp is not None else None
    report = {
        "http_status": status,
        "reachable": status == 200,
        "open_interest": False, "day_volume": False, "implied_volatility": False,
        "greeks": False, "last_quote": False, "last_trade": False,
        "underlying_price": False, "recency": None, "n_contracts_sampled": 0,
        "detected_tier": "unknown", "error": None,
    }
    if resp is None:
        report["error"] = err or "no response"
        return report
    if status != 200:
        try:
            report["error"] = resp.json().get("message") or resp.text[:200]
        except Exception:
            report["error"] = resp.text[:200]
        if status in (401, 403):
            report["reachable"] = True
            report["detected_tier"] = (
                "insufficient plan — key valid but not entitled to SPX options "
                "chain data (requires an options plan; see massive.com/pricing)")
        return report

    results = resp.json().get("results", []) or []
    report["n_contracts_sampled"] = len(results)
    recencies = []
    for c in results:
        if c.get("open_interest") is not None:
            report["open_interest"] = True
        day = c.get("day") or {}
        if day.get("volume") is not None:
            report["day_volume"] = True
        if c.get("implied_volatility") is not None:
            report["implied_volatility"] = True
        if (c.get("greeks") or {}).get("gamma") is not None:
            report["greeks"] = True
        lq = c.get("last_quote") or {}
        if lq.get("bid") is not None or lq.get("ask") is not None:
            report["last_quote"] = True
            if lq.get("last_updated"):
                recencies.append(lq["last_updated"])
        lt = c.get("last_trade") or {}
        if lt.get("price") is not None:
            report["last_trade"] = True
            if lt.get("sip_timestamp") or lt.get("timestamp"):
                recencies.append(lt.get("sip_timestamp") or lt.get("timestamp"))
        ua = c.get("underlying_asset") or {}
        if ua.get("price") is not None or ua.get("value") is not None:
            report["underlying_price"] = True
        if day.get("last_updated"):
            recencies.append(day["last_updated"])
    if recencies:
        report["recency"] = _ts_to_recency(max(recencies))
    # Recency must never be UNKNOWN once we have data: on a delayed/EOD tier with
    # no intraday timestamps, label it from what the tier IS rather than None.
    if report["recency"] is None and report["open_interest"]:
        report["recency"] = {"age_minutes": None,
                             "classification": "EOD daily aggregate (no intraday timestamp on this tier)"}

    if not report["open_interest"]:
        report["detected_tier"] = "free (no OI — module requires Options Starter plan)"
    elif report["last_quote"] and report["last_trade"]:
        report["detected_tier"] = "developer/advanced (quotes + trades available)"
    else:
        report["detected_tier"] = "starter (OI/greeks, no quotes/trades)"
    return report


# ── historical / flat-file probe (§1) ────────────────────────────────────────
# Endpoints below are CONFIRMED empirically (see the discovery log): the options
# reference/aggregates API is Polygon-compatible and keyed by underlying_ticker
# "SPX" (NOT "I:SPX" — the I: prefix returns zero rows). REST daily aggregates
# are entitled only within a recent rolling window; ~2Y-back returns 403
# "plan doesn't include this data timeframe". aggs bars are OHLCV with NO
# open_interest, so ΔOI cannot be backfilled from REST. The full 2Y needs the
# S3 flat files (separate credentials from the dashboard).
_REF_UNDERLYING = "SPX"


def probe_history(api_key: str) -> dict:
    from . import db as _db

    checks = {}
    hist = {
        "contract_listing": False,        # can we enumerate active SPX contracts?
        "expired_listing": False,         # can we enumerate expired contracts?
        "historical_aggregates": False,   # daily OHLCV bars for a real contract?
        "rest_history_recent_ok": False,  # recent expired within the REST window?
        "rest_history_2y_ok": False,      # ~2Y-back within the REST window?
        "rest_history_note": None,
        "oi_in_history": False,           # per-contract-per-day OI anywhere?
        "oi_source": None,
        "flat_files_accessible": False,   # S3 flat files (need dashboard creds)
        "checks": checks,
        "notes": [],
    }

    def record(name, resp, err=None, method="GET", **extra):
        checks[name] = {
            "http_status": (resp.status_code if resp is not None else None),
            "ok": bool(resp is not None and resp.status_code == 200),
            "error": err, "snippet": _snippet(resp), **extra,
        }
        return checks[name]

    today = dt.date.today()
    closes = _db.underlying_closes(limit=1)
    spot = closes[-1][1] if closes else None

    def _strike_band(center):
        if not center:
            return {}
        return {"strike_price.gte": round(center * 0.97),
                "strike_price.lte": round(center * 1.03)}

    def _list(params):
        r, e = _get(f"{MASSIVE_BASE_URL}/v3/reference/options/contracts",
                    api_key=api_key, params={"underlying_ticker": _REF_UNDERLYING,
                                             "contract_type": "call", "limit": 10,
                                             "sort": "strike_price", **params})
        rows = []
        if r is not None and r.status_code == 200:
            try:
                rows = r.json().get("results", []) or []
            except Exception:
                pass
        return r, e, rows

    def _aggs(ticker, frm, to):
        return _get(f"{MASSIVE_BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day/{frm}/{to}",
                    api_key=api_key, params={"sort": "asc", "limit": 50000})

    # 1. Enumerate ACTIVE ~30 DTE ATM contracts.
    r, e, active = _list({"expiration_date.gte": (today + dt.timedelta(days=25)).isoformat(),
                          "expiration_date.lte": (today + dt.timedelta(days=40)).isoformat(),
                          **_strike_band(spot)})
    record("reference_active", r, e, n=len(active))
    hist["contract_listing"] = bool(active)

    # 2. Recent daily aggregates for a live ATM contract (does aggs serve bars?).
    if active:
        t = active[0]["ticker"]
        ar, ae = _aggs(t, (today - dt.timedelta(days=40)).isoformat(), today.isoformat())
        bars = []
        if ar is not None and ar.status_code == 200:
            try:
                bars = ar.json().get("results", []) or []
            except Exception:
                pass
        record("aggs_active", ar, ae, ticker=t, count=len(bars))
        if bars:
            hist["historical_aggregates"] = True
            if any(b.get("open_interest") is not None for b in bars):
                hist["oi_in_history"] = True
                hist["oi_source"] = "v2/aggs daily bars"

    # 3. REST history window: probe a recently-expired and a ~2Y-back expired
    #    contract to find the entitlement boundary.
    for label, center_days, spot_guess in (("recent", 40, spot), ("two_year", 730, None)):
        exp_hi = (today - dt.timedelta(days=center_days - 20)).isoformat()
        exp_lo = (today - dt.timedelta(days=center_days + 20)).isoformat()
        band = _strike_band(spot_guess) if spot_guess else {}
        r, e, rows = _list({"expired": "true", "as_of": exp_hi,
                            "expiration_date.gte": exp_lo, "expiration_date.lte": exp_hi, **band})
        record(f"reference_expired_{label}", r, e, n=len(rows))
        if rows:
            hist["expired_listing"] = True
            t = rows[0]["ticker"]
            exp = rows[0].get("expiration_date")
            ar, ae = _aggs(t, (dt.date.fromisoformat(exp) - dt.timedelta(days=25)).isoformat(), exp)
            status = ar.status_code if ar is not None else None
            cnt = 0
            if status == 200:
                try:
                    cnt = len(ar.json().get("results", []) or [])
                except Exception:
                    pass
            record(f"aggs_expired_{label}", ar, ae, ticker=t, count=cnt)
            ok = status == 200 and cnt > 0
            hist[f"rest_history_{'recent' if label == 'recent' else '2y'}_ok"] = ok
            if status == 403:
                hist["rest_history_note"] = (
                    f"{label}: 403 — plan's REST aggregates do not cover this timeframe "
                    "(full 2Y needs flat files).")

    # 4. Flat files (S3). Candidate REST-host paths only — the real access is an
    #    S3-compatible endpoint with separate dashboard credentials, which this
    #    key-based probe cannot reach. Reported as a candidate, not a verdict.
    ff, err = _get(f"{MASSIVE_BASE_URL}/v1/flatfiles/options", api_key=api_key)
    record("flat_files_rest_candidate", ff, err)
    hist["notes"].append(
        "Flat files are an S3-compatible endpoint with SEPARATE dashboard "
        "credentials (not the REST apiKey). This probe can't reach them; get the "
        "endpoint/bucket/access-key from the Massive dashboard to enable the 2Y "
        "backfill and to answer the OI question from the flat-file schema.")
    if not hist["oi_in_history"]:
        hist["notes"].append(
            "No per-contract-per-day OI in REST aggregates (OHLCV only). ΔOI stays "
            "forward-only unless the flat-file day-aggregate schema has an "
            "open_interest column — never approximated from volume.")
    return hist


# ── orchestration + persistence ──────────────────────────────────────────────
def run_full_probe(api_key: str) -> dict:
    snap = probe_snapshot(api_key)
    report = {
        "probed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "underlying": UNDERLYING,
        **snap,
    }
    # Only probe history if the key is at least entitled to the chain — no point
    # hammering historical endpoints when the base snapshot is 401/403.
    if snap.get("reachable") and snap.get("http_status") == 200:
        report["history"] = probe_history(api_key)
    else:
        report["history"] = {"skipped": "snapshot not entitled; historical probe skipped"}
    write_report(report)
    return report


def write_report(report: dict):
    CAPABILITIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CAPABILITIES_PATH.write_text(json.dumps(report, indent=2))


def load_report():
    try:
        return json.loads(CAPABILITIES_PATH.read_text())
    except Exception:
        return None


def refresh_if_stale(api_key: str, max_age_hours: float = 20.0) -> bool:
    """Best-effort: (re)run the probe if the persisted report is missing or
    older than max_age_hours. Safe to call on startup in a background thread;
    swallows all errors (a probe failure must never break boot)."""
    if not api_key:
        return False
    existing = load_report()
    if existing:
        try:
            probed = dt.datetime.fromisoformat(existing["probed_at"])
            age_h = (dt.datetime.now(dt.timezone.utc) - probed).total_seconds() / 3600.0
            if age_h < max_age_hours:
                return False
        except Exception:
            pass
    try:
        run_full_probe(api_key)
        print("[OPTIONS] capability probe refreshed on startup")
        return True
    except Exception as e:  # pragma: no cover
        print(f"[OPTIONS] startup probe failed (non-fatal): {e}")
        return False
