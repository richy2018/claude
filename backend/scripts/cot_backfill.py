#!/usr/bin/env python
"""One-time COT historical backfill (~2010 -> present).

Memory-safe: processes one report at a time, ONE YEAR AT A TIME, retaining only
the rows for our CONTRACTS symbols and upserting each year before loading the
next (pycot's full-history frame would OOM a small instance). Runs the
validation gates (§5) as it goes. Idempotent — the unique key upserts revisions.

    python -m backend.scripts.cot_backfill
    python -m backend.scripts.cot_backfill --symbols NQ,ES,GC --start-year 2015

Run cot_resolve_names.py first and review the resolved names.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.cot import alerts, db, validate, fetcher  # noqa: E402
from backend.cot.config import CONTRACTS  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", help="comma list (default: all)")
    ap.add_argument("--start-year", type=int, default=fetcher.BACKFILL_START_YEAR)
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else list(CONTRACTS)
    end_year = fetcher.current_year()
    alerts.start_run()
    db.init_db()

    report_syms = fetcher.reports_for_symbols(symbols)
    total = 0
    failures = 0

    for rk, syms in report_syms.items():
        try:
            name_map = fetcher.resolve_names_for(rk, syms)
        except Exception as e:
            failures += 1
            alerts.emit_alert("backfill", f"name resolution failed for {rk}: {e}", level="error", report=rk)
            continue

        unresolved = [s for s in syms if not name_map.get(s)]
        if unresolved:
            alerts.emit_alert("backfill", f"{rk}: unresolved {unresolved}", level="warning", report=rk)

        rk_rows = 0
        for yr, rows in fetcher.iter_report_year_rows(rk, syms, name_map, args.start_year, end_year):
            if not rows:
                continue
            db.upsert_observations(rows)
            validate.check_sum_to_zero(rows)   # per-batch integrity (per-week)
            validate.check_tie_out(rows)       # fires if an anchor date is in-batch
            rk_rows += len(rows)
            print(f"[BACKFILL] {rk} {yr}: {len(rows)} rows")
        total += rk_rows
        print(f"[BACKFILL] {rk}: {rk_rows} rows over {len(syms)} symbols "
              f"({sum(1 for s in syms if name_map.get(s))} resolved)")

    # final global gates
    validate.check_freshness(db.latest_report_date())
    deepest = max((len(db.fetch_series(s, CONTRACTS[s]["report"])) for s in symbols), default=0)
    validate.warmup_ok(deepest)

    status = "ok" if failures == 0 else ("degraded" if failures < len(report_syms) else "failed")
    alerts.finish_run(status)
    print(f"\n[BACKFILL] done: {total} rows upserted, {failures} report failures, status={status}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
