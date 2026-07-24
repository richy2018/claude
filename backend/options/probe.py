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
# Candidate endpoints follow the Polygon-compatible shape the live client already
# relies on. Where a path is a guess it is labelled; the probe reports the actual
# status so a wrong path shows up as data, not a silent False.
def probe_history(api_key: str) -> dict:
    checks = {}
    hist = {
        "historical_aggregates": False,   # expired-contract daily OHLCV bars?
        "history_earliest": None,
        "asof_contract_listing": False,   # can we list the chain as of a past date?
        "oi_in_history": False,           # per-contract-per-day OI anywhere historical?
        "oi_source": None,
        "flat_files_accessible": False,
        "day_aggregate_file_bytes": None,
        "checks": checks,
        "notes": [],
    }

    def record(name, resp, err=None, method="GET"):
        checks[name] = {
            "http_status": (resp.status_code if resp is not None else None),
            "ok": bool(resp is not None and resp.status_code == 200),
            "error": err,
            "snippet": _snippet(resp),
        }
        return checks[name]

    # 1. As-of contract listing (expired contracts included).
    asof = (dt.date.today() - dt.timedelta(days=90)).isoformat()
    sample_ticker = None
    resp, err = _get(f"{MASSIVE_BASE_URL}/v3/reference/options/contracts", api_key=api_key,
                     params={"underlying_ticker": UNDERLYING, "as_of": asof,
                             "expired": "true", "limit": 5})
    record("reference_contracts_asof", resp, err)
    if resp is not None and resp.status_code == 200:
        try:
            rows = resp.json().get("results", []) or []
            if rows:
                hist["asof_contract_listing"] = True
                sample_ticker = rows[0].get("ticker")
                # OI on the reference row? (some vendors attach it)
                if any(r.get("open_interest") is not None for r in rows):
                    hist["oi_in_history"] = True
                    hist["oi_source"] = "reference/options/contracts (as_of)"
        except Exception as e:
            hist["notes"].append(f"reference parse: {e}")

    # 2. Historical daily aggregates for one expired contract + how far back.
    if sample_ticker:
        frm = (dt.date.today() - dt.timedelta(days=365 * 2 + 30)).isoformat()
        to = dt.date.today().isoformat()
        resp, err = _get(f"{MASSIVE_BASE_URL}/v2/aggs/ticker/{sample_ticker}/range/1/day/{frm}/{to}",
                         api_key=api_key, params={"limit": 50000, "sort": "asc"})
        chk = record("contract_daily_aggs", resp, err)
        chk["sample_ticker"] = sample_ticker
        if resp is not None and resp.status_code == 200:
            try:
                bars = resp.json().get("results", []) or []
                if bars:
                    hist["historical_aggregates"] = True
                    first = min(b.get("t") for b in bars if b.get("t"))
                    hist["history_earliest"] = dt.datetime.utcfromtimestamp(first / 1000).date().isoformat()
                    # Do the bars carry OI? (Polygon-style OHLCV do NOT.)
                    if any(b.get("open_interest") is not None for b in bars):
                        hist["oi_in_history"] = True
                        hist["oi_source"] = "v2/aggs daily bars"
            except Exception as e:
                hist["notes"].append(f"aggs parse: {e}")
    else:
        checks["contract_daily_aggs"] = {"skipped": "no sample expired ticker from listing"}

    # 3. Flat files: listing + one day-aggregate file size. Candidate paths.
    day = _recent_weekday()
    ff_list, err = _get(f"{MASSIVE_BASE_URL}/v1/flatfiles/options", api_key=api_key)
    record("flat_files_list", ff_list, err)
    if ff_list is not None and ff_list.status_code == 200:
        hist["flat_files_accessible"] = True

    ff_head, err = _get(
        f"{MASSIVE_BASE_URL}/v1/flatfiles/options/day_aggs/{day}.csv.gz",
        api_key=api_key, method="HEAD")
    chk = record("day_aggregate_file_head", ff_head, err, method="HEAD")
    if ff_head is not None and ff_head.status_code == 200:
        hist["flat_files_accessible"] = True
        clen = ff_head.headers.get("Content-Length")
        hist["day_aggregate_file_bytes"] = int(clen) if clen else None

    if not hist["oi_in_history"]:
        hist["notes"].append(
            "No per-contract-per-day OI found in any tested historical source. If "
            "the flat-file schema (once its real path is confirmed) carries an "
            "open_interest column, re-run and ΔOI backfill unlocks; otherwise ΔOI "
            "stays forward-only — never approximated from volume.")
    return hist


def _recent_weekday():
    d = dt.date.today() - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d.isoformat()


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
