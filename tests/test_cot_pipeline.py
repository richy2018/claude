"""COT pipeline tests — normalisation, DB upsert, validation gates, alert path.

Covers §11.7 ("confirm the alert path actually fires"): a deliberate
sum-to-zero break must route to alerts.emit_alert and surface on the health
snapshot, and a wrong-report frame must raise from the identity check.
"""

import os
import importlib
from pathlib import Path

import pandas as pd
import pytest

CSV = Path(__file__).resolve().parent.parent / "backend" / "data" / "cot_nq_processed.csv"


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """A clean SQLite DB per test (DATABASE_URL points at a temp file)."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cot.db'}")
    import backend.cot.db as db
    importlib.reload(db)
    db.init_db()
    return db


def _legacy_frame():
    ref = pd.read_csv(CSV, parse_dates=["date"])
    return ref, pd.DataFrame({
        "As of Date in Form YYYY-MM-DD": ref["date"],
        "Market and Exchange Names": "NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE",
        "Noncommercial Positions-Long (All)": ref["noncomm_net"].clip(lower=0) + 1000,
        "Noncommercial Positions-Short (All)": (-ref["noncomm_net"]).clip(lower=0) + 1000,
        "Commercial Positions-Long (All)": ref["comm_net"].clip(lower=0) + 2000,
        "Commercial Positions-Short (All)": (-ref["comm_net"]).clip(lower=0) + 2000,
        "Nonreportable Positions-Long (All)": ref["nonrept_net"].clip(lower=0) + 500,
        "Nonreportable Positions-Short (All)": (-ref["nonrept_net"]).clip(lower=0) + 500,
        "Open Interest (All)": 250000,
    })


def test_normalize_legacy_ties_out():
    from backend.cot.transform import normalize_report_frame
    _, frame = _legacy_frame()
    rows = normalize_report_frame(frame, "legacy_fut", "NQ", "NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE")
    last = {r["cohort"]: r for r in rows if str(r["report_date"]) == "2026-06-16"}
    assert last["non_comm"]["net"] == -8908
    assert last["commercial"]["net"] == 4087
    assert last["non_rept"]["net"] == 4821


def test_upsert_is_idempotent(fresh_db):
    from backend.cot.transform import normalize_report_frame
    db = fresh_db
    _, frame = _legacy_frame()
    rows = normalize_report_frame(frame, "legacy_fut", "NQ", "NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE")
    db.upsert_observations(rows)
    db.upsert_observations(rows)  # re-run must not duplicate
    stored = db.fetch_series("NQ", "legacy_fut")
    assert len(stored) == len(rows)


def test_revision_overwrites(fresh_db):
    from backend.cot.transform import normalize_report_frame
    db = fresh_db
    _, frame = _legacy_frame()
    rows = normalize_report_frame(frame, "legacy_fut", "NQ", "NQ NAME")
    db.upsert_observations(rows)
    # CFTC revises the latest week's non_comm net
    rev = [dict(r) for r in rows if str(r["report_date"]) == "2026-06-16" and r["cohort"] == "non_comm"]
    rev[0]["net"] = -9999
    db.upsert_observations(rev)
    stored = db.fetch_series("NQ", "legacy_fut")
    got = [r for r in stored if str(r["report_date"]) == "2026-06-16" and r["cohort"] == "non_comm"][0]
    assert got["net"] == -9999


def test_sum_to_zero_alert_fires():
    """Break the legacy balance and assert the alert path records a failure."""
    from backend.cot import alerts, validate
    before = len(alerts._cot_health["alerts"])
    bad_rows = [
        {"report_date": "2026-06-16", "symbol": "NQ", "report_type": "legacy_fut", "cohort": "non_comm", "net": -8908},
        {"report_date": "2026-06-16", "symbol": "NQ", "report_type": "legacy_fut", "cohort": "commercial", "net": 4087},
        {"report_date": "2026-06-16", "symbol": "NQ", "report_type": "legacy_fut", "cohort": "non_rept", "net": 9999},  # broken
    ]
    ok = validate.check_sum_to_zero(bad_rows, "NQ")
    assert ok is False
    assert len(alerts._cot_health["alerts"]) > before          # an alert was emitted
    snap = alerts.health_snapshot()
    assert snap["validation"]["sum_to_zero"]["ok"] is False     # surfaced on health


def test_tie_out_anchor_passes():
    from backend.cot import validate
    rows = [
        {"report_date": "2026-06-16", "symbol": "NQ", "report_type": "legacy_fut", "cohort": "non_comm", "net": -8908},
        {"report_date": "2026-06-16", "symbol": "NQ", "report_type": "legacy_fut", "cohort": "commercial", "net": 4087},
        {"report_date": "2026-06-16", "symbol": "NQ", "report_type": "legacy_fut", "cohort": "non_rept", "net": 4821},
    ]
    assert validate.check_tie_out(rows) is True


def test_wrong_report_identity_raises():
    """A frame missing the report's identity tokens must be rejected (§2)."""
    from backend.cot.fetcher import _assert_report_identity
    # A legacy-shaped frame passed as TFF has no 'lev money'/'asset mgr' columns.
    legacy_cols = pd.DataFrame(columns=[
        "Market and Exchange Names", "Noncommercial Positions-Long (All)",
        "Commercial Positions-Long (All)"])
    with pytest.raises(ValueError):
        _assert_report_identity(legacy_cols, "tff_fut")
