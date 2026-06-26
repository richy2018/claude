#!/usr/bin/env python
"""Pandas-free streaming COT backfill (~2010 -> present).

Runs in ~35 MB (no pandas) so it fits ALONGSIDE the live dashboard in 512 MB —
no cold start, RAM upgrade, or Postgres needed. Streams each yearly CFTC zip as
a CSV, keeps only our contracts' rows, and upserts in batches. Idempotent.

    python -m backend.scripts.cot_backfill_stream
    python -m backend.scripts.cot_backfill_stream --symbols NQ,ES,GC --start-year 2015

Import chain is deliberately pandas-free (streaming/columns/config/db/alerts),
so validation here is inline pure-Python rather than the pandas validate module.
"""

import argparse
import gc
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.cot import alerts, db, streaming, columns  # noqa: E402
from backend.cot.config import CONTRACTS, BACKFILL_START_YEAR  # noqa: E402

UPSERT_BATCH = 2000
LEGACY_COHORTS = ("non_comm", "commercial", "non_rept")
# Verified anchor (ties to CFTC COT<GO>): NQ legacy 2026-06-16.
TIE_OUT = {"symbol": "NQ", "report": "legacy_fut", "date": "2026-06-16",
           "nets": {"non_comm": -8908, "commercial": 4087, "non_rept": 4821}}


def _validate(symbol_check="NQ"):
    """Pure-Python sum-to-zero + tie-out on stored legacy rows (no pandas)."""
    rows = db.fetch_series(symbol_check, "legacy_fut")
    by_date = {}
    for r in rows:
        by_date.setdefault(str(r["report_date"]), {})[r["cohort"]] = r["net"]
    bad = 0
    checked = 0
    for d, c in by_date.items():
        if set(LEGACY_COHORTS) <= set(c):
            checked += 1
            if sum(c[k] for k in LEGACY_COHORTS) != 0:
                bad += 1
    alerts.record_validation("sum_to_zero", bad == 0,
                             f"{symbol_check} legacy: {checked - bad}/{checked} weeks balance")
    print(f"[VALIDATE] {symbol_check} legacy sum-to-zero: {checked - bad}/{checked} weeks balance")

    anchor = by_date.get(TIE_OUT["date"])
    if TIE_OUT["symbol"] == symbol_check and anchor:
        ok = all(anchor.get(k) == v for k, v in TIE_OUT["nets"].items())
        alerts.record_validation("tie_out", ok, f"{symbol_check} {TIE_OUT['date']}: {anchor}")
        print(f"[VALIDATE] {symbol_check} {TIE_OUT['date']} tie-out: "
              f"{'PASS' if ok else 'FAIL'} (nets {{nc,cm,nr}} = "
              f"{anchor.get('non_comm')},{anchor.get('commercial')},{anchor.get('non_rept')})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", help="comma list (default: all)")
    ap.add_argument("--start-year", type=int, default=BACKFILL_START_YEAR)
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else list(CONTRACTS)
    end_year = streaming.current_year()
    alerts.start_run()
    db.init_db()

    report_syms = streaming.reports_for_symbols(symbols)
    total = 0
    failures = 0

    for rk, syms in report_syms.items():
        try:
            available = streaming.list_available_contracts(rk)
        except Exception as e:
            failures += 1
            alerts.emit_alert("backfill", f"name list failed for {rk}: {e}", level="error", report=rk)
            continue
        name_map = {s: columns.resolve_contract_name(s, available) for s in syms}
        name_to_symbol = {n: s for s, n in name_map.items() if n}
        unresolved = [s for s in syms if not name_map.get(s)]
        if unresolved:
            alerts.emit_alert("backfill", f"{rk}: unresolved {unresolved}", level="warning", report=rk)

        rk_rows = 0
        for yr in range(args.start_year, end_year + 1):
            batch = []
            try:
                for row in streaming.stream_report_year(rk, yr, name_to_symbol):
                    batch.append(row)
                    if len(batch) >= UPSERT_BATCH:
                        db.upsert_observations(batch)
                        rk_rows += len(batch)
                        batch = []
                if batch:
                    db.upsert_observations(batch)
                    rk_rows += len(batch)
            except Exception as e:
                alerts.emit_alert("backfill", f"{rk} {yr}: {e}", level="warning", report=rk, year=yr)
            gc.collect()
            print(f"[STREAM-BACKFILL] {rk} {yr}: cumulative {rk_rows} rows")
        total += rk_rows
        print(f"[STREAM-BACKFILL] {rk}: {rk_rows} rows "
              f"({sum(1 for s in syms if name_map.get(s))}/{len(syms)} symbols resolved)")

    _validate("NQ")
    status = "ok" if failures == 0 else ("degraded" if failures < len(report_syms) else "failed")
    alerts.finish_run(status)
    print(f"\n[STREAM-BACKFILL] done: {total} rows upserted, {failures} report failures, status={status}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
