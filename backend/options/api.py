"""Options API — one summary endpoint + manual snapshot trigger.

  GET  /api/options/summary   -> latest stored metrics + percentile/sparkline
                                 histories + capability/tier report + history depth
  POST /api/options/snapshot  -> trigger a snapshot now (background, locked)
  GET  /api/options/health    -> light status (last snapshot, sessions, tier)

Mirrors the COT module's refresh pattern: BackgroundTasks + a threading.Lock
so a double-trigger can't overlap, and the snapshot itself is pandas-free so
it runs safely in-process on the 512 MB instance.
"""

import threading

from fastapi import APIRouter, BackgroundTasks

from . import db, snapshot
from .metrics import percentile_of
from .config import UNDERLYING, PERCENTILE_MIN_SESSIONS

router = APIRouter(prefix="/api/options", tags=["options"])

_snapshot_lock = threading.Lock()
_last_manual = {"status": None, "detail": None}

# History keys pulled from stored daily aggregates for percentiles/sparklines.
_HISTORY_KEYS = [
    "surface.atm_iv_30d",
    "surface.rr_25d.value",
    "surface.vrp",
    "positioning.buckets.0-7d.pc_oi_ratio",
    "positioning.buckets.8-30d.pc_oi_ratio",
    "positioning.buckets.31d+.pc_oi_ratio",
]


def _tier_state(caps):
    if caps is None:
        return {"state": "unprobed",
                "message": "Run scripts/probe_massive.py to detect the API plan's capabilities."}
    err = (caps.get("error") or "")
    # 401/403 (or an entitlement message) = the API answered but the plan lacks
    # access — surface the clean upgrade banner, not a raw error.
    if caps.get("http_status") in (401, 403) or "not entitled" in err.lower():
        return {"state": "insufficient_plan",
                "message": err or "API key is not entitled to SPX options chain data — "
                                  "requires an options plan (massive.com/pricing)."}
    if not caps.get("reachable"):
        return {"state": "unreachable", "message": err or "API not reachable at last probe."}
    if not caps.get("open_interest"):
        return {"state": "insufficient_plan",
                "message": "requires Options Starter plan — the current key returns no open interest."}
    return {"state": "ok", "message": caps.get("detected_tier", "ok")}


@router.get("/summary")
async def summary():
    db.init_db()
    caps = snapshot.capabilities()
    tier = _tier_state(caps)
    snap_date, latest = db.latest_metrics()

    hist_rows = db.metrics_history(_HISTORY_KEYS)
    histories = {k: [(d, vals.get(k)) for d, vals in hist_rows] for k in _HISTORY_KEYS}

    percentiles = {}
    if latest and latest.get("status") == "ok":
        for key, label in (("surface.atm_iv_30d", "atm_iv_30d"),
                           ("surface.rr_25d.value", "rr_25d"),
                           ("surface.vrp", "vrp")):
            series = [v for _, v in histories.get(key, [])]
            current = series[-1] if series else None
            percentiles[label] = percentile_of(current, series[:-1] if series else [])

    # Flow panel: only available when the probe found BOTH trades and quotes.
    # No approximation with a tick test on lesser plans — hard rule.
    flow_available = bool(caps and caps.get("last_quote") and caps.get("last_trade"))

    return {
        "underlying": UNDERLYING,
        "tier": tier,
        "capabilities": caps,
        "snap_date": snap_date,
        "metrics": latest,
        "percentiles": percentiles,
        "histories": histories,
        "history_depth": len(db.snapshot_dates()),
        "percentile_min_sessions": PERCENTILE_MIN_SESSIONS,
        "flow": {"available": flow_available,
                 "message": None if flow_available else "unavailable on current plan"},
    }


def _run_snapshot_job():
    if not _snapshot_lock.acquire(blocking=False):
        return
    try:
        _last_manual["status"] = "running"
        result = snapshot.run_daily_snapshot()
        _last_manual["status"] = result.get("status")
        _last_manual["detail"] = result
        print(f"[OPTIONS] snapshot finished: {result.get('status')} "
              f"({result.get('rows_written', 0)} rows)")
    except Exception as e:
        _last_manual["status"] = "failed"
        _last_manual["detail"] = {"reason": str(e)}
        print(f"[OPTIONS] snapshot crashed: {e}")
    finally:
        _snapshot_lock.release()


@router.post("/snapshot")
async def trigger_snapshot(background_tasks: BackgroundTasks):
    """Manual snapshot trigger (also how the first-ever snapshot is taken).
    Returns immediately; poll /health for the outcome."""
    if _snapshot_lock.locked():
        return {"status": "already_running"}
    background_tasks.add_task(_run_snapshot_job)
    return {"status": "started"}


@router.get("/health")
async def health():
    db.init_db()
    dates = db.snapshot_dates()
    return {
        "sessions": len(dates),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "tier": _tier_state(snapshot.capabilities()),
        "last_manual_run": _last_manual,
        "snapshot_running": _snapshot_lock.locked(),
    }
