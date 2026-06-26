#!/usr/bin/env python
"""Weekly incremental COT update — driven by the Render cron (§9).

CFTC releases Fri 15:30 ET. Memory-safe: loads only the recent year(s) needed
for the incremental window (not full history), retains only our contracts'
rows, upserts with a few weeks of overlap so CFTC's revisions to prior weeks are
captured, runs the validation gates, and records run health for /api/cot/health.

    python -m backend.scripts.cot_weekly_update

Cron: primary `0 22 * * 5`, retry `0 14 * * 6` (UTC).
"""

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.cot import alerts, db, validate, fetcher  # noqa: E402
from backend.cot.config import CONTRACTS  # noqa: E402

# Re-pull this many weeks of overlap so CFTC's revisions to recent weeks upsert.
OVERLAP_WEEKS = 6


def main():
    alerts.start_run()
    db.init_db()

    cur = fetcher.current_year()
    report_syms = fetcher.reports_for_symbols(list(CONTRACTS))
    total = 0
    failures = 0

    for rk, syms in report_syms.items():
        try:
            name_map = fetcher.resolve_names_for(rk, syms)
        except Exception as e:
            failures += 1
            alerts.emit_alert("cron", f"name resolution failed for {rk}: {e}", level="error", report=rk)
            continue

        # Incremental window: oldest 'latest stored' across this report's symbols
        latests = [d for d in (db.latest_report_date(s, rk) for s in syms) if d]
        since = (min(latests) - timedelta(weeks=OVERLAP_WEEKS)) if latests else None
        start_year = since.year if since else cur

        for _yr, rows in fetcher.iter_report_year_rows(rk, syms, name_map, start_year, cur, since=since):
            if not rows:
                continue
            db.upsert_observations(rows)
            validate.check_sum_to_zero(rows)
            validate.check_tie_out(rows)
            total += len(rows)
        print(f"[WEEKLY] {rk}: upserted through {cur}, since={since}")

    newest = db.latest_report_date()
    fresh_ok = validate.check_freshness(newest)

    status = "ok" if (failures == 0 and fresh_ok) else (
        "degraded" if failures < len(report_syms) else "failed")
    alerts.finish_run(status)
    print(f"[WEEKLY] done: {total} rows, newest report_date={newest}, "
          f"{failures} failures, status={status}")
    return 0 if status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
