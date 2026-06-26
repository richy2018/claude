#!/usr/bin/env python
"""One-time COT historical backfill (~2010 -> present).

Loads each report once, resolves names, normalises all cohorts for every
CONTRACTS symbol (asset-appropriate report + legacy), upserts into
cot_observation, then runs the validation gates (§5). Idempotent — safe to
re-run; the unique key upserts revised weeks.

    python -m backend.scripts.cot_backfill
    python -m backend.scripts.cot_backfill --symbols NQ,ES,GC

Run cot_resolve_names.py first and review the resolved names.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.cot import alerts, db, validate  # noqa: E402
from backend.cot.config import CONTRACTS  # noqa: E402
from backend.cot.fetcher import fetch_symbol_rows  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", help="comma list (default: all)")
    args = ap.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else list(CONTRACTS)
    alerts.start_run()
    db.init_db()

    total = 0
    failures = 0
    for sym in symbols:
        rows = fetch_symbol_rows(sym)
        if not rows:
            failures += 1
            print(f"[BACKFILL] {sym}: 0 rows (see alerts)")
            continue
        n = db.upsert_observations(rows)
        total += n
        # per-symbol integrity gates
        validate.check_sum_to_zero(rows, sym)
        validate.check_tie_out(rows)
        dates = sorted({r["report_date"] for r in rows})
        print(f"[BACKFILL] {sym}: {n} rows, {len(dates)} weeks "
              f"({dates[0]} -> {dates[-1]})")

    # global freshness + warmup (use the deepest stored history as the gauge)
    validate.check_freshness(db.latest_report_date())
    deepest = max((len(db.fetch_series(s, CONTRACTS[s]["report"])) for s in symbols), default=0)
    validate.warmup_ok(deepest)

    status = "ok" if failures == 0 else ("degraded" if failures < len(symbols) else "failed")
    alerts.finish_run(status)
    print(f"\n[BACKFILL] done: {total} rows upserted across {len(symbols)} symbols, "
          f"{failures} symbol failures, status={status}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
