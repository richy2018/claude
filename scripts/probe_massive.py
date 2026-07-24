#!/usr/bin/env python
"""Massive.com options API capability probe.

Run this BEFORE relying on any options feature. It pulls a small slice of the
I:SPX option chain snapshot and reports, field by field, what the current API
key's plan actually returns:

  - open_interest present?          (required for ALL positioning metrics)
  - day volume present?             (required for the stale filter + volume table)
  - implied_volatility + greeks?    (required for surface metrics + gamma model)
  - last_quote present?             (gates the trade-flow classification panel)
  - last_trade present?             (gates the trade-flow classification panel)
  - timestamp recency               (real-time vs 15-min delayed vs EOD)

The report is printed AND written to backend/data/massive_capabilities.json,
which the backend reads to gate features and the frontend surfaces in the
options-section footer. If OI is missing entirely (free tier), the dashboard
renders a "requires Options Starter plan" state rather than empty charts —
that gating starts from this file.

Usage:
    MASSIVE_API_KEY=... python scripts/probe_massive.py

The key comes ONLY from the environment. Never hardcode it, never commit it.
"""

import json
import os
import sys
import time
import datetime as dt
from pathlib import Path

import requests

BASE = "https://api.massive.com"
UNDERLYING = "I:SPX"
OUT_PATH = Path(__file__).resolve().parent.parent / "backend" / "data" / "massive_capabilities.json"
TIMEOUT = 30


def _get(url, params=None, api_key=None, max_retries=4):
    params = dict(params or {})
    params["apiKey"] = api_key
    for attempt in range(max_retries):
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        if resp.status_code == 429:
            wait = 2 ** (attempt + 1)
            print(f"  rate-limited (429), backing off {wait}s...")
            time.sleep(wait)
            continue
        return resp
    return resp


def _ts_to_recency(ts_ns):
    """Classify a nanosecond (or ms) epoch timestamp as realtime/delayed/eod."""
    if not ts_ns:
        return None
    ts = float(ts_ns)
    # normalise ns / us / ms / s to seconds
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


def main():
    api_key = os.environ.get("MASSIVE_API_KEY")
    if not api_key:
        print("ERROR: set MASSIVE_API_KEY in the environment (do not hardcode it).")
        return 2

    print(f"Probing {BASE}/v3/snapshot/options/{UNDERLYING} ...")
    resp = _get(f"{BASE}/v3/snapshot/options/{UNDERLYING}", params={"limit": 10}, api_key=api_key)
    print(f"HTTP {resp.status_code}")

    report = {
        "probed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "underlying": UNDERLYING,
        "http_status": resp.status_code,
        "reachable": resp.status_code == 200,
        "open_interest": False,
        "day_volume": False,
        "implied_volatility": False,
        "greeks": False,
        "last_quote": False,
        "last_trade": False,
        "underlying_price": False,
        "recency": None,
        "n_contracts_sampled": 0,
        "detected_tier": "unknown",
        "error": None,
    }

    if resp.status_code == 200:
        payload = resp.json()
        results = payload.get("results", []) or []
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

        # Tier inference (heuristic, from what actually came back)
        if not report["open_interest"]:
            report["detected_tier"] = "free (no OI — module requires Options Starter plan)"
        elif report["last_quote"] and report["last_trade"]:
            report["detected_tier"] = "developer/advanced (quotes + trades available)"
        else:
            report["detected_tier"] = "starter (OI/greeks, no quotes/trades)"
    else:
        try:
            report["error"] = resp.json().get("message") or resp.text[:200]
        except Exception:
            report["error"] = resp.text[:200]
        # 401/403 mean the API answered but the key/plan lacks entitlement —
        # that's "insufficient plan", not "unreachable". The dashboard shows
        # the upgrade banner for this state.
        if resp.status_code in (401, 403):
            report["reachable"] = True
            report["detected_tier"] = (
                "insufficient plan — key valid but not entitled to SPX options "
                "chain data (requires an options plan; see massive.com/pricing)")

    # ── print the capability report ──────────────────────────────────────
    print("\n===== MASSIVE API CAPABILITY REPORT =====")
    for k in ("reachable", "open_interest", "day_volume", "implied_volatility",
              "greeks", "last_quote", "last_trade", "underlying_price"):
        print(f"  {k:<20} {'YES' if report[k] else 'no'}")
    print(f"  recency              {report['recency']}")
    print(f"  detected tier        {report['detected_tier']}")
    if report["error"]:
        print(f"  error                {report['error']}")
    print("=========================================")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {OUT_PATH}")
    print("The backend gates snapshot/metrics features on this file; re-run the "
          "probe after any plan change.")
    return 0 if report["reachable"] else 1


if __name__ == "__main__":
    sys.exit(main())
