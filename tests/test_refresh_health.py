"""Regression tests for the refresh-health tracking exposed via
/api/health/refresh. Specifically guards against the silent-failure
mode that commit 8434e9c introduced: if the 5F compute raises, the
dashboard must NOT continue reporting "success" based on stale cached
data.

These are intentionally lightweight — they exercise the pure
_update_refresh_health_from_cache() and _classify_staleness() helpers
by mutating _cache / _refresh_health directly, without spinning up the
FastAPI app or touching any external data. The point is that a future
developer who breaks the refresh pipeline sees a failing test.

Run:
    python -m pytest tests/test_refresh_health.py -v
"""
import os
import sys
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)


@pytest.fixture
def main_module():
    from backend import main as m
    # Reset tracking state to a clean slate at the start of each test.
    m._refresh_health["last_successful_refresh"] = None
    m._refresh_health["last_attempted_refresh"] = None
    m._refresh_health["last_refresh_status"] = "unknown"
    m._refresh_health["last_error"] = None
    m._refresh_health["consecutive_failures"] = 0
    m._refresh_health["last_5f_compute_at"] = None
    m._refresh_health["last_5f_data_current_as_of"] = None
    for key in ("5f", "3fa_eq", "3fa", "4f", "2f"):
        m._refresh_health["per_model_status"][key] = {
            "last_success": None, "last_error": None, "status": "unknown",
        }
        m._cache[f"gli_prod_{key}"] = None
    yield m


def test_refresh_failure_is_visible(main_module):
    """If 5F compute fails, /api/health/refresh must report failure.

    Prevents silent cache-serving regressions like commit 8434e9c where
    compute_production_signal raised but the dashboard continued serving
    pre-regression cached output with no visible indication.
    """
    m = main_module
    # Simulate the failure mode: compute returned an error dict, cache
    # stored it instead of a valid 'current' payload.
    m._cache["gli_prod_5f"] = {"error": "Missing components: ['dollar_stress_signal']"}
    for other in ("3fa_eq", "3fa", "4f", "2f"):
        m._cache[f"gli_prod_{other}"] = {"error": "cascade"}

    m._update_refresh_health_from_cache()

    assert m._refresh_health["last_refresh_status"] == "failed"
    assert m._refresh_health["per_model_status"]["5f"]["status"] == "failed"
    assert m._refresh_health["consecutive_failures"] >= 1
    # The specific error string must propagate so an operator can diagnose.
    assert "Missing components" in m._refresh_health["per_model_status"]["5f"]["last_error"]


def test_partial_failure_distinguished_from_full_failure(main_module):
    """If primary 5F works but a secondary variant fails, status is
    'partial' — the trading signal is still trustworthy. Dashboard
    should not block, only show a minor warning.
    """
    m = main_module
    # Valid 5F payload (the shape the backend actually produces — only
    # the presence of 'current' and absence of 'error' matter).
    m._cache["gli_prod_5f"] = {
        "current": {"level_quintile": 2, "mom_quintile": 3, "date": "2026-04-01",
                    "data_current_as_of": "2026-04-15"},
        "chart": [],
    }
    # 3FA crashed this refresh.
    m._cache["gli_prod_3fa"] = {"error": "oops"}
    for other in ("3fa_eq", "4f", "2f"):
        m._cache[f"gli_prod_{other}"] = {"current": {}, "chart": []}

    m._update_refresh_health_from_cache()

    assert m._refresh_health["last_refresh_status"] == "partial"
    assert m._refresh_health["per_model_status"]["5f"]["status"] == "success"
    assert m._refresh_health["per_model_status"]["3fa"]["status"] == "failed"
    # Partial failure does NOT increment consecutive_failures — the
    # primary signal is still trustworthy, so the dashboard must not
    # escalate to a stale/critical banner state.
    assert m._refresh_health["consecutive_failures"] == 0


def test_staleness_classification_thresholds():
    """_classify_staleness must match the spec exactly:
        fresh    < 24h
        aging    24-72h
        stale    >72h OR consecutive_failures >= 2
        critical >7d OR consecutive_failures >= 5
    """
    from backend.main import _classify_staleness

    assert _classify_staleness(0, 0)[0] == "fresh"
    assert _classify_staleness(12, 0)[0] == "fresh"
    assert _classify_staleness(25, 0)[0] == "aging"
    assert _classify_staleness(72.5, 0)[0] == "stale"
    assert _classify_staleness(24 * 7 + 1, 0)[0] == "critical"
    # consecutive_failures escalation
    assert _classify_staleness(1, 2)[0] == "stale"
    assert _classify_staleness(1, 5)[0] == "critical"
    # Missing timestamp → critical (fail-safe)
    assert _classify_staleness(None, 0)[0] == "critical"
