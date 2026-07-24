#!/usr/bin/env python
"""Reconstruct ~2Y of SPX constant-maturity IV surface history from flat files.

Source (confirmed): Massive's S3 flat files, options day aggregates at
  us_options_opra/day_aggs_v1/YYYY/MM/YYYY-MM-DD.csv.gz
one gzipped CSV per trading day, all OPRA options. Columns:
  ticker,volume,open,close,high,low,window_start,transactions   (NO open_interest)

For each trading day this streams that file, keeps SPX-index rows (roots SPX/SPXW)
within the DTE band and a ±12% strike band, inverts Black-Scholes on each CLOSE to
an IV (backend/options/iv_inversion.py), and interpolates to a 30d constant
maturity (backend/options/reconstruct.py) — both unit-tested. Rows are written to
surface_history(source='reconstructed'); a later live snapshot supersedes them.

  python scripts/backfill_surface.py [--dry-run] [--max-days N]

Credentials (S3, SEPARATE from the REST apiKey) come from the environment:
  MASSIVE_S3_KEY_ID, MASSIVE_S3_SECRET   (endpoint/bucket default to Massive's)

DISCIPLINE:
  * Refuses to run without S3 access — it will not invent history.
  * Reconstructed rows are labelled 'reconstructed'; never blended with live IV
    unlabelled.
  * Validation gate: reconstructed vs live ATM IV over overlapping dates; MAD >
    RECON_MAX_MAD_VOLPTS aborts with a report rather than blending.
  * ΔOI is NOT here and never will be from this source — day aggregates carry no
    open interest, and it is never approximated from volume.
"""

import argparse
import csv
import datetime as dt
import gzip
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.options import db, reconstruct
from backend.options.occ import parse_occ_ticker, SPX_ROOTS
from backend.options.config import (
    MASSIVE_S3_ENDPOINT, MASSIVE_S3_BUCKET, FLATFILE_DAY_AGGS_PREFIX,
    s3_credentials, RECON_DTE_LO, RECON_DTE_HI, RECON_LOOKBACK_YEARS,
    RECON_MAX_MAD_VOLPTS,
)

_STRIKE_BAND = 0.12   # keep strikes within ±12% of spot (ATM + wings suffice)


def _s3_client():
    kid, sec = s3_credentials()
    if not (kid and sec):
        return None
    import boto3
    return boto3.client("s3", endpoint_url=MASSIVE_S3_ENDPOINT,
                        aws_access_key_id=kid, aws_secret_access_key=sec)


def _day_key(date: str) -> str:
    d = dt.date.fromisoformat(date)
    return f"{FLATFILE_DAY_AGGS_PREFIX}/{d.year:04d}/{d.month:02d}/{date}.csv.gz"


def fetch_day_spx_contracts(s3, date: str, spot: float):
    """Stream one day's flat file -> [{strike, expiry, ctype, close, days}] for
    SPX-index contracts in the DTE + strike band. [] if the file is absent
    (holiday) or unreadable — the day is skipped, never fabricated."""
    key = _day_key(date)
    try:
        obj = s3.get_object(Bucket=MASSIVE_S3_BUCKET, Key=key)
    except Exception:
        return []   # NoSuchKey (holiday) / access error -> skip this day
    try:
        raw = gzip.GzipFile(fileobj=io.BytesIO(obj["Body"].read()))
        reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8"))
    except Exception:
        return []
    header = next(reader, None)  # ticker,volume,open,close,high,low,window_start,transactions
    lo, hi = spot * (1 - _STRIKE_BAND), spot * (1 + _STRIKE_BAND)
    d0 = dt.date.fromisoformat(date)
    out = []
    for row in reader:
        if not row or not row[0].startswith("O:SPX"):
            continue
        p = parse_occ_ticker(row[0])
        if not p or p["root"] not in SPX_ROOTS:
            continue
        if not (lo <= p["strike"] <= hi):
            continue
        days = (dt.date.fromisoformat(p["expiry"]) - d0).days
        if not (RECON_DTE_LO <= days <= RECON_DTE_HI):
            continue
        try:
            close = float(row[3])
        except (ValueError, IndexError):
            continue
        if close <= 0:
            continue
        out.append({"strike": p["strike"], "expiry": p["expiry"],
                    "ctype": p["ctype"], "close": close, "days": days})
    return out


def _trading_days(closes_dates, years):
    cutoff = (dt.date.today() - dt.timedelta(days=365 * years)).isoformat()
    return [d for d in closes_dates if d >= cutoff]


def run(dry_run=False, max_days=None):
    s3 = _s3_client()
    if s3 is None:
        print("REFUSING TO RUN: set MASSIVE_S3_KEY_ID and MASSIVE_S3_SECRET (the S3 "
              "flat-file credentials from the Massive dashboard — separate from the "
              "REST apiKey). Without them there is no honest 2Y source.")
        return 2
    try:
        import boto3  # noqa: F401
    except ImportError:
        print("REFUSING TO RUN: boto3 not installed (pip install boto3).")
        return 2

    db.init_db()
    closes = dict(db.underlying_closes(limit=5000))
    if len(closes) < 200:
        print(f"Only {len(closes)} underlying closes stored — take one snapshot first "
              "to seed ^GSPC history, then re-run.")
        return 1

    days = _trading_days(sorted(closes.keys()), RECON_LOOKBACK_YEARS)
    already = {d for d, v in db.surface_history() if v["source"] == "reconstructed"}
    todo = [d for d in days if d not in already]
    if max_days:
        todo = todo[-max_days:]
    print(f"{len(days)} trading days in {RECON_LOOKBACK_YEARS}Y window; "
          f"{len(already)} already reconstructed; {len(todo)} to do"
          + (" (dry-run)" if dry_run else ""))

    recon_atm = {}
    done = missing = 0
    for date in todo:
        spot = closes.get(date)
        if not spot:
            continue
        contracts = fetch_day_spx_contracts(s3, date, spot)
        if not contracts:
            missing += 1
            continue
        row = reconstruct.reconstruct_day(contracts, spot, date)
        if not row:
            missing += 1
            continue
        recon_atm[date] = row["atm_iv_30d"]
        if not dry_run:
            db.upsert_surface_row(date, row["atm_iv_30d"], row["rr_25d_norm"],
                                  json.dumps(row["term"]), "reconstructed")
        done += 1
        if done % 25 == 0:
            print(f"  ...{done}/{len(todo)} ({date} ATM {row['atm_iv_30d']}%)")

    print(f"Reconstructed {done} days ({missing} days had no file / no usable contracts).")

    # ── validation gate: reconstructed vs live ATM IV over overlapping dates ──
    live = {d: v["atm_iv_30d"] for d, v in db.surface_history() if v["source"] == "live"}
    stored = {d: v["atm_iv_30d"] for d, v in db.surface_history() if v["source"] == "reconstructed"}
    stored.update(recon_atm)
    mad, n = reconstruct.validation_mad(stored, live)
    if n == 0:
        print("Validation gate: no overlapping live dates yet — applies as live "
              "history accumulates. Reconstructed series stored.")
    elif mad is not None and mad > RECON_MAX_MAD_VOLPTS:
        print(f"VALIDATION GATE FAILED: reconstructed vs live ATM IV MAD={mad:.2f} vol "
              f"pts over {n} dates (> {RECON_MAX_MAD_VOLPTS}). Series stored but "
              "INCONSISTENT — investigate (r/q, close vs settle, DTE band) before "
              "trusting percentiles rather than blending.")
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
