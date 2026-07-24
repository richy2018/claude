"""Options module unit tests (spec §5).

Covers: the stale filter, bucket assignment, the Black-Scholes gamma function
against known textbook values, the spot-sweep crossing finder on a synthetic
chain where the crossing location is known, percentile PENDING semantics, the
ATM linear-in-variance interpolation, and an end-to-end ΔOI compute through a
temp SQLite store.
"""

import datetime as dt

import pytest

from backend.options import metrics, gamma, surface
from backend.options.gamma import bs_gamma, find_zero_crossings, run_sweep
from backend.options.metrics import apply_hygiene, bucket_of, percentile_of


# ── Black-Scholes gamma vs known values ──────────────────────────────────────
def test_bs_gamma_textbook_atm():
    # S=100, K=100, T=1y, sigma=0.2, r=5%, q=0 -> gamma = 0.018762 (Hull)
    g = bs_gamma(100, 100, 1.0, 0.2, r=0.05, q=0.0)
    assert abs(g - 0.018762) < 1e-4


def test_bs_gamma_textbook_hull_example():
    # Hull ch.19 example: S=49, K=50, T=0.3846, sigma=0.2, r=5% -> gamma ~0.0655
    g = bs_gamma(49, 50, 0.3846, 0.2, r=0.05, q=0.0)
    assert abs(g - 0.0655) < 5e-3


def test_bs_gamma_degenerate_inputs():
    assert bs_gamma(0, 100, 1, 0.2) == 0.0
    assert bs_gamma(100, 100, 1, 0) == 0.0
    # 0DTE is floored, not exploded to inf
    assert bs_gamma(100, 100, 0.0, 0.2) > 0


# ── crossing finder ──────────────────────────────────────────────────────────
def test_find_zero_crossings_linear():
    xs = [0.0, 1.0, 2.0, 3.0]
    ys = [-2.0, -1.0, 1.0, 3.0]
    cross = find_zero_crossings(xs, ys)
    assert len(cross) == 1
    assert abs(cross[0] - 1.5) < 1e-9


def test_find_zero_crossings_none():
    assert find_zero_crossings([0, 1, 2], [1.0, 2.0, 3.0]) == []


def test_sweep_synthetic_chain_known_crossing():
    """Call OI concentrated above spot, put OI below, equal size/IV/expiry:
    net gamma (a=1) must be negative below spot, positive above, with exactly
    one crossing near the geometric midpoint of the two strikes (~99.5)."""
    asof = "2026-01-02"
    expiry = "2026-02-02"
    chain = [
        {"strike": 110.0, "expiry": expiry, "ctype": "call", "oi": 1000, "iv": 0.2},
        {"strike": 90.0, "expiry": expiry, "ctype": "put", "oi": 1000, "iv": 0.2},
    ]
    result = run_sweep(chain, spot=100.0, asof=asof, a_scenarios=(1.0,))
    curve = result["curves"]["1.00"]
    spots = result["spots"]
    crossings = result["crossings"]["1.00"]
    assert len(crossings) == 1
    assert 95.0 < crossings[0] < 105.0
    # sign structure: put-dominated (negative) at the low end, call-dominated at the top
    assert curve[0] < 0 and curve[-1] > 0
    # gross is positive and exceeds |net| at spot
    assert result["gross_at_spot"] > abs(result["net_at_spot"]["1.00"])
    assert spots[0] == pytest.approx(85.0) and spots[-1] == pytest.approx(115.0)


def test_sweep_a_scenarios_move_crossing():
    """Reducing dealer-long-call share must shift net gamma downward
    (a=0.25 curve strictly below a=1.00 curve wherever calls have gamma)."""
    asof, expiry = "2026-01-02", "2026-02-02"
    chain = [
        {"strike": 105.0, "expiry": expiry, "ctype": "call", "oi": 2000, "iv": 0.25},
        {"strike": 95.0, "expiry": expiry, "ctype": "put", "oi": 1000, "iv": 0.25},
    ]
    r = run_sweep(chain, spot=100.0, asof=asof)
    hi = r["curves"]["1.00"]
    lo = r["curves"]["0.25"]
    assert all(l <= h for l, h in zip(lo, hi))


def test_sweep_skips_missing_iv_and_reports():
    asof, expiry = "2026-01-02", "2026-02-02"
    chain = [
        {"strike": 100.0, "expiry": expiry, "ctype": "call", "oi": 500, "iv": 0.2},
        {"strike": 100.0, "expiry": expiry, "ctype": "put", "oi": 300, "iv": None},
    ]
    r = run_sweep(chain, spot=100.0, asof=asof)
    assert r["n_contracts_used"] == 1
    assert r["skipped"] == {"count": 1, "oi": 300}


# ── hygiene filters ──────────────────────────────────────────────────────────
def _row(strike, oi, volume, ctype="call", expiry="2026-03-20"):
    return {"ticker": f"O:X{strike}{ctype}", "strike": strike, "expiry": expiry,
            "ctype": ctype, "oi": oi, "volume": volume, "iv": 0.2,
            "delta": 0.5, "gamma": 0.01, "spot": 100.0}


def test_stale_filter_thresholds():
    rows = [
        _row(100, oi=1000, volume=200),   # vol/OI=0.20 -> kept
        _row(101, oi=1000, volume=100),   # vol/OI=0.10 -> kept (< threshold flags, 0.10 passes)
        _row(102, oi=1000, volume=99),    # vol/OI=0.099 -> STALE
        _row(103, oi=0, volume=50),       # new listing, OI 0 + volume -> kept
        _row(104, oi=0, volume=0),        # dead row -> stale
        _row(105, oi=None, volume=10),    # missing OI -> missing bucket
    ]
    kept, report = apply_hygiene(rows, spot=100.0)
    kept_strikes = {r["strike"] for r in kept}
    assert kept_strikes == {100, 101, 103}
    assert report["stale"]["count"] == 2
    assert report["stale"]["oi"] == 1000  # only the 0.099 row carried OI
    assert report["missing_oi"]["count"] == 1


def test_band_filter_and_reporting():
    rows = [
        _row(100, oi=500, volume=100),
        _row(125, oi=700, volume=700),    # +25% -> outside ±20% band
        _row(79, oi=300, volume=300),     # -21% -> outside
        _row(119, oi=400, volume=400),    # +19% -> inside
    ]
    kept, report = apply_hygiene(rows, spot=100.0)
    assert {r["strike"] for r in kept} == {100, 119}
    assert report["band"]["count"] == 2
    assert report["band"]["oi"] == 1000


# ── bucket assignment ────────────────────────────────────────────────────────
@pytest.mark.parametrize("days,expected", [
    (0, "0-7d"), (7, "0-7d"), (8, "8-30d"), (30, "8-30d"), (31, "31d+"), (400, "31d+"),
])
def test_bucket_assignment(days, expected):
    assert bucket_of(days) == expected


# ── percentile PENDING semantics ─────────────────────────────────────────────
def test_percentile_pending_under_min_sessions():
    r = percentile_of(5.0, list(range(59)))
    assert r["status"] == "PENDING" and r["percentile"] is None and r["sessions"] == 59


def test_percentile_live_at_min_sessions():
    r = percentile_of(30.0, list(range(60)))
    assert r["status"] == "ok" and r["percentile"] is not None and r["sessions"] == 60


# ── ATM 30d interpolation (linear in total variance) ─────────────────────────
def test_atm_iv_30d_linear_in_variance():
    asof = "2026-01-02"
    d20 = (dt.date.fromisoformat(asof) + dt.timedelta(days=20)).isoformat()
    d40 = (dt.date.fromisoformat(asof) + dt.timedelta(days=40)).isoformat()
    rows = []
    for exp, iv in ((d20, 0.20), (d40, 0.30)):
        rows.append({"strike": 100.0, "expiry": exp, "ctype": "call", "iv": iv,
                     "oi": 10, "volume": 10, "delta": 0.5})
        rows.append({"strike": 100.0, "expiry": exp, "ctype": "put", "iv": iv,
                     "oi": 10, "volume": 10, "delta": -0.5})
    got = surface.atm_iv_30d(rows, spot=100.0, asof=asof)
    # v1=0.04*(20/365), v2=0.09*(40/365); v30 = v1+(v2-v1)/2; sigma=sqrt(v30/(30/365))
    assert got == pytest.approx(27.08, abs=0.05)


# ── end-to-end ΔOI through a temp store ──────────────────────────────────────
def test_delta_oi_end_to_end(tmp_path, monkeypatch):
    from backend.options import db as odb
    monkeypatch.setattr(odb, "db_path", lambda: tmp_path / "opt.db")
    odb.init_db()

    day1, day2 = "2026-01-05", "2026-01-06"
    for d, oi in ((day1, 1000), (day2, 1400)):
        odb.upsert_contracts([{ "snap_date": d, "ticker": "O:SPXW260320C05000000",
            "strike": 5000.0, "expiry": "2026-03-20", "ctype": "call", "oi": oi,
            "volume": 500, "iv": 0.2, "delta": 0.5, "gamma": 0.001, "spot": 5000.0}])
        odb.store_underlying_close(d, 5000.0)

    from backend.options.snapshot import compute_daily
    p1 = compute_daily(day1)
    p2 = compute_daily(day2)

    # Day 1: no prior session -> PENDING, never fabricated
    assert p1["positioning"]["delta_status"].startswith("PENDING")
    b1 = p1["positioning"]["buckets"]["31d+"]["call"]
    assert b1["doi_1d"] is None and b1["oi"] == 1000

    # Day 2: ΔOI 1d = +400 against day 1; 5-session delta still PENDING
    assert p2["positioning"]["delta_status"] == "ok"
    b2 = p2["positioning"]["buckets"]["31d+"]["call"]
    assert b2["doi_1d"] == 400
    assert p2["positioning"]["delta5_status"].startswith("PENDING")
    assert p2["history"]["sessions"] == 2
