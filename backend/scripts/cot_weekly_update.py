#!/usr/bin/env python
"""Weekly incremental COT update — driven by the Render cron (§9).

CFTC releases Fri 15:30 ET. This pulls the latest report frames, upserts the
most recent weeks for every symbol (incremental: only rows newer than what we
already store, minus a small overlap so CFTC's revisions to prior weeks are
captured), runs the validation gates, and records run health for
/api/cot/health.

    python -m backend.scripts.cot_weekly_update

Cron: primary `0 22 * * 5`, retry `0 14 * * 6` (UTC).
"""

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.cot import alerts, db, validate  # noqa: E402
from backend.cot.config import CONTRACTS  # noqa: E402
from backend.cot.fetcher import fetch_symbol_rows  # noqa: E402

# Re-pull this many weeks of overlap so CFTC's revisions to recent weeks upsert.
OVERLAP_WEEKS = 6


def main():
    alerts.start_run()
    db.init_db()

    total = 0
    failures = 0
    for sym in CONTRACTS:
        latest = db.latest_report_date(sym)
        since = (latest - timedelta(weeks=OVERLAP_WEEKS)) if latest else None
        rows = fetch_symbol_rows(sym, since=since)
        if not rows:
            failures += 1
            continue
        n = db.upsert_observations(rows)
        total += n
        validate.check_sum_to_zero(rows, sym)
        validate.check_tie_out(rows)
        print(f"[WEEKLY] {sym}: {n} rows since {since}")

    newest = db.latest_report_date()
    fresh_ok = validate.check_freshness(newest)

    status = "ok" if (failures == 0 and fresh_ok) else (
        "degraded" if failures < len(CONTRACTS) else "failed")
    alerts.finish_run(status)
    print(f"[WEEKLY] done: {total} rows, newest report_date={newest}, "
          f"{failures} failures, status={status}")
    return 0 if status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
