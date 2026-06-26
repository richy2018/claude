"""Failure alerting for the COT module.

Every CFTC fetch is fragile (pre-alpha packages pulling from a live gov site),
so every fetch and every validation gate routes failures here. This mirrors the
dashboard's existing `_refresh_health` pattern in main.py: loud prints plus an
in-memory health record surfaced via `GET /api/cot/health` so the frontend can
warn on silent staleness, exactly like the GLI HealthBanner.

`emit_alert()` is the single sink. To wire a real channel (email / Slack /
PagerDuty), set the COT_ALERT_WEBHOOK env var or replace `_external_sink`.
"""

import os
import json
from datetime import datetime, timezone

# Ring buffer of recent alerts + last-known status, read by /api/cot/health.
_cot_health = {
    "last_run_at": None,
    "last_run_status": "unknown",      # ok | degraded | failed | unknown
    "last_success_at": None,
    "consecutive_failures": 0,
    "alerts": [],                       # most-recent-last, capped
    "validation": {},                   # gate_name -> {ok, detail, at}
}

_MAX_ALERTS = 200


def _iso_now():
    return datetime.now(timezone.utc).isoformat()


def _external_sink(payload: dict):
    """Best-effort external delivery. No-op unless COT_ALERT_WEBHOOK is set.

    Kept deliberately simple and failure-tolerant — alerting must never raise
    into the fetch path. Documented fallback if this is never wired: the alert
    is still printed to stdout (captured by Render logs) and exposed via
    /api/cot/health.
    """
    url = os.environ.get("COT_ALERT_WEBHOOK")
    if not url:
        return
    try:
        import requests
        requests.post(url, json=payload, timeout=8)
    except Exception as e:  # pragma: no cover - network best-effort
        print(f"[COT-ALERT] external sink failed: {e}")


def emit_alert(stage: str, message: str, level: str = "error", **context):
    """Record and surface a failure. `stage` e.g. 'fetch', 'validation', 'cron'."""
    entry = {
        "at": _iso_now(),
        "level": level,
        "stage": stage,
        "message": str(message),
        "context": {k: str(v) for k, v in context.items()},
    }
    _cot_health["alerts"].append(entry)
    _cot_health["alerts"] = _cot_health["alerts"][-_MAX_ALERTS:]
    prefix = "[COT-ALERT]" if level == "error" else "[COT-WARN]"
    print(f"{prefix} {stage}: {message}" + (f" | {json.dumps(entry['context'])}" if context else ""))
    _external_sink(entry)
    return entry


def record_validation(gate: str, ok: bool, detail: str = ""):
    """Record the outcome of a validation gate (§5). Alerts on failure."""
    _cot_health["validation"][gate] = {"ok": bool(ok), "detail": detail, "at": _iso_now()}
    if not ok:
        emit_alert("validation", f"{gate}: {detail}", level="error", gate=gate)
    return ok


def start_run():
    _cot_health["last_run_at"] = _iso_now()


def finish_run(status: str):
    """status in {ok, degraded, failed}."""
    _cot_health["last_run_status"] = status
    if status == "ok":
        _cot_health["last_success_at"] = _iso_now()
        _cot_health["consecutive_failures"] = 0
    elif status == "failed":
        _cot_health["consecutive_failures"] += 1


def health_snapshot() -> dict:
    """Snapshot for GET /api/cot/health (in-memory only, fast)."""
    h = dict(_cot_health)
    h["alerts"] = _cot_health["alerts"][-25:]  # last 25 for the UI
    h["alert_count"] = len(_cot_health["alerts"])
    return h
