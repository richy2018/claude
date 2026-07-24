"""Daily snapshot scheduler — a single daemon thread, no new dependencies.

Consistent with how this dashboard already refreshes (in-process jobs + manual
trigger endpoints; the repo's render.yaml cron entries require a Blueprint
deploy this service doesn't use). Sleeps until the configured UTC time
(default 19:30 UTC ≈ 22:30 Riga in summer; override OPTIONS_SNAPSHOT_UTC,
disable with OPTIONS_SCHEDULER=off), runs the snapshot, repeats. Weekends are
skipped (no US session); a snapshot on a US holiday just re-records the prior
session's chain and upserts idempotently.
"""

import datetime as dt
import threading
import time

from .config import snapshot_utc, scheduler_enabled


def _seconds_until_next(now: dt.datetime, hhmm: str) -> float:
    hh, mm = (int(x) for x in hhmm.split(":"))
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return (target - now).total_seconds()


def _loop():
    from .api import _run_snapshot_job   # reuse the locked job runner
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        wait = _seconds_until_next(now, snapshot_utc())
        time.sleep(wait)
        if dt.datetime.now(dt.timezone.utc).weekday() < 5:  # Mon-Fri only
            print("[OPTIONS] scheduled snapshot starting")
            _run_snapshot_job()
        else:
            print("[OPTIONS] scheduled snapshot skipped (weekend)")


def start():
    """Start the scheduler thread (no-op if disabled via env)."""
    if not scheduler_enabled():
        print("[OPTIONS] scheduler disabled via OPTIONS_SCHEDULER")
        return None
    t = threading.Thread(target=_loop, name="options-snapshot-scheduler", daemon=True)
    t.start()
    print(f"[OPTIONS] scheduler started (daily {snapshot_utc()} UTC, Mon-Fri)")
    return t
