#!/usr/bin/env python
"""Reconstruct ~2Y of SPX constant-maturity IV surface history (spec §3).

Runs ONCE on the server after the probe confirms historical reach. Resumable and
idempotent: each finished day is written to surface_history(source=reconstructed)
and skipped on re-run. Reuses the seeded ^GSPC daily closes as the underlying —
no extra spot fetch. Pure math (IV inversion, 30d interpolation) lives in
backend/options/reconstruct.py and is unit-tested; this script is the data-source
+ orchestration + validation-gate layer.

  MASSIVE_API_KEY=... python scripts/backfill_surface.py [--dry-run] [--max-days N]

DISCIPLINE:
  * Refuses to run unless the persisted probe confirms historical_aggregates —
    it will not invent history from an unconfirmed source.
  * Reconstructed rows are labelled source='reconstructed'; a later live snapshot
    for the same date supersedes them. Percentiles pool both, never blended
    unlabelled.
  * Validation gate: before trusting the series, reconstructed vs live ATM IV is
    compared over overlapping dates; MAD > RECON_MAX_MAD_VOLPTS aborts with a
    report rather than blending inconsistent series.

DATA SOURCE: REST, Polygon-compatible (same shape as the live client). For each
trade date it lists the as-of contracts in the 20-45 DTE band and pulls each
contract's daily close. If the probe reports flat_files_accessible with an
open_interest/close schema, switch fetch_day_contracts() to read the day-aggregate
flat file instead (one file per day) — far fewer calls; wire it once the probe
confirms the real flat-file path.
"""

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from backend.options import db, reconstruct
from backend.options.config import (
    MASSIVE_BASE_URL, UNDERLYING, RECON_DTE_LO, RECON_DTE_HI,
    RECON_LOOKBACK_YEARS, RECON_MAX_MAD_VOLPTS,
)
from backend.options.probe import load_report

_TIMEOUT = 45
_MAX_RETRIES = 5


def _get(session, url, params, api_key):
    params = dict(params)
    params["apiKey"] = api_key
    for attempt in range(_MAX_RETRIES):
        r = session.get(url, params=params, timeout=_TIMEOUT)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        return r
    return r


def _trading_days(closes_dates, years):
    """Use the seeded ^GSPC close dates as the trading calendar."""
    cutoff = (dt.date.today() - dt.timedelta(days=365 * years)).isoformat()
    return [d for d in closes_dates if d >= cutoff]


def fetch_day_contracts(session, date, api_key, spot=None):
    """[{strike, expiry, ctype, close, days}] for as-of `date` in the DTE band.

    Confirmed REST path: reference is keyed by underlying_ticker "SPX" (NOT the
    "I:SPX" snapshot ticker), and the strike band is narrowed to ±12% of that
    day's spot so we pull the liquid near-the-money strikes the surface needs,
    not the whole chain. Returns [] on any failure for that day — the day is
    simply skipped, never fabricated. NOTE: REST aggregates are entitled only
    within a recent rolling window; days beyond it 403 and are skipped, so the
    full 2Y needs flat files instead.
    """
    lo = (dt.date.fromisoformat(date) + dt.timedelta(days=RECON_DTE_LO)).isoformat()
    hi = (dt.date.fromisoformat(date) + dt.timedelta(days=RECON_DTE_HI)).isoformat()
    contracts = []
    url = f"{MASSIVE_BASE_URL}/v3/reference/options/contracts"
    params = {"underlying_ticker": "SPX", "as_of": date,
              "expiration_date.gte": lo, "expiration_date.lte": hi, "limit": 1000}
    if spot:
        params["strike_price.gte"] = round(spot * 0.88)
        params["strike_price.lte"] = round(spot * 1.12)
    while url:
        r = _get(session, url, params, api_key)
        if r.status_code != 200:
            return []
        body = r.json()
        for c in body.get("results", []) or []:
            contracts.append({"ticker": c.get("ticker"),
                              "strike": c.get("strike_price"),
                              "expiry": c.get("expiration_date"),
                              "ctype": c.get("contract_type")})
        url = body.get("next_url")
        params = {}

    out = []
    for c in contracts:
        if not (c["ticker"] and c["strike"] and c["expiry"] and c["ctype"]):
            continue
        close = _contract_close(session, c["ticker"], date, api_key)
        if close is None:
            continue
        days = (dt.date.fromisoformat(c["expiry"]) - dt.date.fromisoformat(date)).days
        out.append({"strike": float(c["strike"]), "expiry": c["expiry"],
                    "ctype": str(c["ctype"]).lower(), "close": close, "days": days})
    return out


def _contract_close(session, ticker, date, api_key):
    url = f"{MASSIVE_BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day/{date}/{date}"
    r = _get(session, url, {"adjusted": "false"}, api_key)
    if r.status_code != 200:
        return None
    res = r.json().get("results") or []
    return res[0].get("c") if res and res[0].get("c") else None


def run(dry_run=False, max_days=None):
    api_key = os.environ.get("MASSIVE_API_KEY")
    if not api_key:
        print("ERROR: MASSIVE_API_KEY not set."); return 2

    report = load_report()
    hist = (report or {}).get("history") or {}
    if not hist.get("historical_aggregates"):
        print("REFUSING TO RUN: the probe has not confirmed historical_aggregates.")
        print("Run scripts/probe_massive.py first. If historical aggregates are not")
        print("available on this plan, surface reconstruction is not honest — do not")
        print("force it. (History reach in the report: "
              f"{json.dumps({k: hist.get(k) for k in ('historical_aggregates','asof_contract_listing','flat_files_accessible')})})")
        return 1

    db.init_db()
    closes = dict(db.underlying_closes(limit=5000))
    if len(closes) < 200:
        print(f"Only {len(closes)} underlying closes stored — take one snapshot first "
              "to seed ^GSPC history, then re-run."); return 1

    days = _trading_days(sorted(closes.keys()), RECON_LOOKBACK_YEARS)
    already = {d for d, v in db.surface_history() if v["source"] == "reconstructed"}
    todo = [d for d in days if d not in already]
    if max_days:
        todo = todo[-max_days:]
    print(f"{len(days)} trading days in {RECON_LOOKBACK_YEARS}Y window; "
          f"{len(already)} already reconstructed; {len(todo)} to do"
          + (" (dry-run)" if dry_run else ""))

    session = requests.Session()
    recon_atm = {}
    done = 0
    for date in todo:
        spot = closes.get(date)
        if not spot:
            continue
        contracts = fetch_day_contracts(session, date, api_key, spot=spot)
        if not contracts:
            continue
        row = reconstruct.reconstruct_day(contracts, spot, date)
        if not row:
            continue
        recon_atm[date] = row["atm_iv_30d"]
        if not dry_run:
            db.upsert_surface_row(date, row["atm_iv_30d"], row["rr_25d_norm"],
                                  json.dumps(row["term"]), "reconstructed")
        done += 1
        if done % 25 == 0:
            print(f"  ...{done}/{len(todo)} days ({date} ATM {row['atm_iv_30d']}%)")

    print(f"Reconstructed {done} days.")

    # ── validation gate: reconstructed vs live ATM IV over overlapping dates ──
    live = {d: v["atm_iv_30d"] for d, v in db.surface_history() if v["source"] == "live"}
    # include this run's values plus anything already stored as reconstructed
    stored_recon = {d: v["atm_iv_30d"] for d, v in db.surface_history()
                    if v["source"] == "reconstructed"}
    stored_recon.update(recon_atm)
    mad, n = reconstruct.validation_mad(stored_recon, live)
    if n == 0:
        print("Validation gate: no overlapping live dates yet — will apply as live "
              "history accumulates. Reconstructed series stored.")
    elif mad is not None and mad > RECON_MAX_MAD_VOLPTS:
        print(f"VALIDATION GATE FAILED: reconstructed vs live ATM IV MAD={mad:.2f} "
              f"vol pts over {n} dates (> {RECON_MAX_MAD_VOLPTS}). Series stored but "
              "INCONSISTENT — investigate before trusting percentiles (check r/q, "
              "close vs settle, DTE band) rather than blending.")
        return 3
    else:
        print(f"Validation gate PASSED: MAD={mad:.2f} vol pts over {n} overlapping dates.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-days", type=int, default=None)
    args = ap.parse_args()
    sys.exit(run(dry_run=args.dry_run, max_days=args.max_days))
