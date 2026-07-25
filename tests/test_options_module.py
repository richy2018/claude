"""Options module unit tests (spec §5).

Covers: the stale filter, bucket assignment, the Black-Scholes gamma function
against known textbook values, the spot-sweep crossing finder on a synthetic
chain where the crossing location is known, percentile PENDING semantics, the
ATM linear-in-variance interpolation, and an end-to-end ΔOI compute through a
temp SQLite store.
"""

import datetime as dt

import pytest

from backend.options import metrics, gamma, surface, reconstruct
from backend.options.gamma import bs_gamma, find_zero_crossings, run_sweep
from backend.options.metrics import apply_hygiene, bucket_of, percentile_of
from backend.options.iv_inversion import bs_price, bs_delta, implied_vol
from backend.options.occ import parse_occ_ticker, is_spx_index


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
    # sweep widened to ±25% (§5)
    assert spots[0] == pytest.approx(75.0) and spots[-1] == pytest.approx(125.0)
    assert result["sweep_range_pct"] == 25


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
    assert r["skipped"]["count"] == 1 and r["skipped"]["oi"] == 300
    # skip-reason breakdown (§5): the put failed on missing IV, not zero OI
    assert r["skipped"]["missing_iv"] == 1 and r["skipped"]["zero_oi"] == 0


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


# ── spot fallback (chain-only plans carry no underlying price) ───────────────
def _chain_no_spot():
    """Two hygiene-passing contracts as iter_chain_snapshot would slim them on
    a plan without an indices entitlement: spot is None on every row."""
    expiry = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    return [
        {"ticker": "O:SPXW1C05000000", "strike": 5000.0, "expiry": expiry,
         "ctype": "call", "oi": 1000, "volume": 500, "iv": 0.2,
         "delta": 0.5, "gamma": 0.001, "spot": None},
        {"ticker": "O:SPXW1P05000000", "strike": 5000.0, "expiry": expiry,
         "ctype": "put", "oi": 800, "volume": 400, "iv": 0.22,
         "delta": -0.5, "gamma": 0.001, "spot": None},
    ]


def test_snapshot_uses_spot_fallback_when_chain_has_none(tmp_path, monkeypatch):
    from backend.options import db as odb, client, snapshot as snap
    monkeypatch.setattr(odb, "db_path", lambda: tmp_path / "opt.db")
    monkeypatch.setattr(client, "iter_chain_snapshot", lambda u: iter(_chain_no_spot()))
    monkeypatch.setattr(snap, "fetch_spot_fallback", lambda: (5000.0, "yahoo:^GSPC"))
    monkeypatch.setattr(snap, "capabilities", lambda: {"reachable": True, "open_interest": True})
    monkeypatch.setattr(snap, "fetch_underlying_history", lambda period="5y": [])
    monkeypatch.setattr(snap, "trade_date", lambda: "2026-07-22")   # a Wednesday

    result = snap.run_daily_snapshot()
    assert result["status"] == "ok"
    assert result["spot"] == 5000.0
    assert result["spot_source"] == "yahoo:^GSPC"
    assert result["metrics_status"] == "ok"

    _, payload = odb.latest_metrics()
    assert payload["status"] == "ok"
    assert payload["spot"] == 5000.0
    assert payload["spot_source"] == "yahoo:^GSPC"


def test_snapshot_stays_empty_when_no_spot_source(tmp_path, monkeypatch):
    """Fallback also failing must yield an honest empty day, never a number."""
    from backend.options import db as odb, client, snapshot as snap
    monkeypatch.setattr(odb, "db_path", lambda: tmp_path / "opt.db")
    monkeypatch.setattr(client, "iter_chain_snapshot", lambda u: iter(_chain_no_spot()))
    monkeypatch.setattr(snap, "fetch_spot_fallback", lambda: (None, None))
    monkeypatch.setattr(snap, "capabilities", lambda: {"reachable": True, "open_interest": True})
    monkeypatch.setattr(snap, "fetch_underlying_history", lambda period="5y": [])
    monkeypatch.setattr(snap, "trade_date", lambda: "2026-07-22")   # a Wednesday

    result = snap.run_daily_snapshot()
    assert result["status"] == "ok"          # chain rows are stored either way
    assert result["spot"] is None
    assert result["metrics_status"] == "empty"

    _, payload = odb.latest_metrics()
    assert payload["status"] == "empty"
    assert payload["reason"] == "no underlying spot recorded"


def test_chain_embedded_spot_labeled_as_chain(tmp_path, monkeypatch):
    from backend.options import db as odb, client, snapshot as snap
    monkeypatch.setattr(odb, "db_path", lambda: tmp_path / "opt.db")
    rows = _chain_no_spot()
    for r in rows:
        r["spot"] = 5100.0
    monkeypatch.setattr(client, "iter_chain_snapshot", lambda u: iter(rows))
    # fallback may be consulted for the stale-session guard, but chain-embedded
    # spot must win for storage + labelling — return a distinct value to prove it
    monkeypatch.setattr(snap, "fetch_spot_fallback", lambda: (1.0, "yahoo:^GSPC"))
    monkeypatch.setattr(snap, "capabilities", lambda: {"reachable": True, "open_interest": True})
    monkeypatch.setattr(snap, "fetch_underlying_history", lambda period="5y": [])
    monkeypatch.setattr(snap, "trade_date", lambda: "2026-07-22")   # a Wednesday

    result = snap.run_daily_snapshot()
    assert result["status"] == "ok"
    assert result["spot"] == 5100.0
    assert result["spot_source"] == "massive:chain"
    _, payload = odb.latest_metrics()
    assert payload["spot_source"] == "massive:chain"


# ── trading-day guard + non-trading-day dedup (weekend/holiday re-serve) ─────
def test_snapshot_skips_weekend(tmp_path, monkeypatch):
    from backend.options import db as odb, client, snapshot as snap
    monkeypatch.setattr(odb, "db_path", lambda: tmp_path / "w.db")
    odb.init_db()
    monkeypatch.setattr(snap, "trade_date", lambda: "2026-07-25")   # a Saturday
    monkeypatch.setattr(snap, "capabilities", lambda: {"reachable": True, "open_interest": True})
    called = {"chain": False}

    def _boom(*a, **k):
        called["chain"] = True
        return iter([])
    monkeypatch.setattr(client, "iter_chain_snapshot", _boom)

    r = snap.run_daily_snapshot()
    assert r["status"] == "skipped" and "weekend" in r["reason"]
    assert called["chain"] is False           # bailed before any pull
    assert odb.snapshot_dates() == []         # nothing written


def test_snapshot_skips_stale_holiday(tmp_path, monkeypatch):
    from backend.options import db as odb, client, snapshot as snap
    monkeypatch.setattr(odb, "db_path", lambda: tmp_path / "h.db")
    odb.init_db()
    odb.store_underlying_close("2026-05-22", 5900.00)   # prior real session (Fri)
    monkeypatch.setattr(snap, "trade_date", lambda: "2026-05-25")   # Memorial Day (Mon holiday)
    monkeypatch.setattr(snap, "capabilities", lambda: {"reachable": True, "open_interest": True})
    monkeypatch.setattr(snap, "fetch_spot_fallback", lambda: (5900.00, "yahoo:^GSPC"))  # same close
    called = {"chain": False}

    def _boom(*a, **k):
        called["chain"] = True
        return iter([])
    monkeypatch.setattr(client, "iter_chain_snapshot", _boom)

    r = snap.run_daily_snapshot()
    assert r["status"] == "skipped" and "identical" in r["reason"]
    assert called["chain"] is False
    assert "2026-05-25" not in odb.snapshot_dates()


def test_dedup_closes_removes_consecutive_duplicate():
    base = [(f"2026-01-{i+1:02d}", 5000.0 + i * 10) for i in range(40)]  # strictly rising
    dup = base[:20] + [base[19]] + base[20:]                            # weekend re-serve
    assert surface.dedup_closes(dup) == base
    # realised vol is unbiased by the injected zero-return day
    assert surface.realised_vols(dup) == surface.realised_vols(base)


def test_prune_duplicate_sessions(tmp_path, monkeypatch):
    from backend.options import db as odb
    monkeypatch.setattr(odb, "db_path", lambda: tmp_path / "p.db")
    odb.init_db()
    for d, oi in (("2026-07-24", 100), ("2026-07-25", 100)):   # 07-25 = same-close dup
        odb.upsert_contracts([{"snap_date": d, "ticker": "O:SPXW260821C07400000",
            "strike": 7400.0, "expiry": "2026-08-21", "ctype": "call", "oi": oi,
            "volume": 5, "iv": 0.2, "delta": 0.5, "gamma": 0.001, "spot": 7411.98}])
        odb.store_underlying_close(d, 7411.98)
        odb.store_daily_metrics(d, {"snap_date": d, "status": "ok"})
        odb.upsert_surface_row(d, 15.0, 0.4, None, "live")

    removed = odb.prune_duplicate_sessions()
    assert removed == ["2026-07-25"]
    assert odb.snapshot_dates() == ["2026-07-24"]
    assert dict(odb.underlying_closes()) == {"2026-07-24": 7411.98}
    assert [d for d, _ in odb.surface_history()] == ["2026-07-24"]
    assert odb.prune_duplicate_sessions() == []          # idempotent, no-op when clean


# ── §3 OCC ticker parsing (flat-file rows) ───────────────────────────────────
def test_parse_occ_ticker_spxw():
    p = parse_occ_ticker("O:SPXW260724C02600000")
    assert p == {"root": "SPXW", "expiry": "2026-07-24", "ctype": "call", "strike": 2600.0}


def test_parse_occ_ticker_put_and_strike_scale():
    p = parse_occ_ticker("O:SPX260821P05450000")
    assert p["root"] == "SPX" and p["ctype"] == "put" and p["strike"] == 5450.0
    assert p["expiry"] == "2026-08-21"


def test_is_spx_index_excludes_lookalikes():
    # SPXL (leveraged ETF) shares the 'O:SPX' prefix but is NOT the index
    assert is_spx_index("O:SPXW260724C02600000")
    assert is_spx_index("O:SPX260821C05450000")
    assert not is_spx_index("O:SPXL260821C00130000")
    assert not is_spx_index("O:A260821C00130000")
    assert not is_spx_index("O:SPY260821C00500000")


def test_parse_occ_ticker_rejects_junk():
    for bad in ("", "SPXW260724C02600000", "O:", "O:SPXW260724X02600000",
                "O:SPXW261324C02600000"):   # bad prefix / bad type / bad month
        assert parse_occ_ticker(bad) is None


# ── §3 Black-Scholes IV inversion ────────────────────────────────────────────
@pytest.mark.parametrize("ctype,sigma", [("call", 0.20), ("put", 0.35), ("call", 0.80)])
def test_iv_inversion_round_trip(ctype, sigma):
    S, K, T = 5000.0, 5050.0, 30 / 365.0
    price = bs_price(S, K, T, sigma, ctype)
    iv = implied_vol(price, S, K, T, ctype)
    assert iv == pytest.approx(sigma, abs=1e-3)


def test_iv_inversion_discards_below_intrinsic():
    # deep-ITM call marked far below intrinsic -> junk, not a vol
    assert implied_vol(1.0, 6000.0, 5000.0, 30 / 365.0, "call") is None


def test_iv_inversion_discards_out_of_range():
    S, K, T = 5000.0, 5000.0, 30 / 365.0
    below = bs_price(S, K, T, 0.01, "call")   # implies < 3% floor
    above = bs_price(S, K, T, 2.0, "call")    # implies > 150% ceiling
    assert implied_vol(below, S, K, T, "call") is None
    assert implied_vol(above, S, K, T, "call") is None


def test_bs_delta_signs():
    assert 0 < bs_delta(5000, 5000, 0.1, 0.2, "call") < 1
    assert -1 < bs_delta(5000, 5000, 0.1, 0.2, "put") < 0


# ── §3 surface reconstruction (invert priced chain -> constant-maturity IV) ──
def _priced_chain(spot, asof, sigma=0.25):
    rows = []
    for days in (25, 40):                       # bracket 30d
        expiry = (dt.date.fromisoformat(asof) + dt.timedelta(days=days)).isoformat()
        for k in range(4200, 5800, 100):
            for ct in ("call", "put"):
                price = bs_price(spot, float(k), days / 365.0, sigma, ct)
                rows.append({"strike": float(k), "expiry": expiry, "ctype": ct,
                             "close": price, "days": days})
    return rows


def test_reconstruct_day_recovers_flat_vol():
    asof, spot = "2026-01-05", 5000.0
    row = reconstruct.reconstruct_day(_priced_chain(spot, asof, 0.25), spot, asof)
    assert row is not None
    assert row["atm_iv_30d"] == pytest.approx(25.0, abs=0.3)
    # flat surface -> ~zero 25d risk reversal
    assert abs(row["rr_25d_norm"]) < 0.05


def test_reconstruct_day_none_when_band_empty():
    # all contracts far outside the 20-45 DTE band -> nothing to interpolate
    rows = _priced_chain(5000.0, "2026-01-05")
    for r in rows:
        r["days"] = 5
    assert reconstruct.reconstruct_day(rows, 5000.0, "2026-01-05") is None


def test_validation_mad():
    recon = {"d1": 20.0, "d2": 21.0, "d3": 19.0}
    live = {"d2": 21.4, "d3": 19.2, "dX": 10.0}
    mad, n = reconstruct.validation_mad(recon, live)
    assert n == 2 and mad == pytest.approx((0.4 + 0.2) / 2, abs=1e-9)
    assert reconstruct.validation_mad({"d": 1.0}, {}) == (None, 0)


# ── §2 realised vol goes live from seeded ^GSPC closes (no forward-only gate) ─
def test_realised_live_from_seeded_closes(tmp_path, monkeypatch):
    from backend.options import db as odb
    monkeypatch.setattr(odb, "db_path", lambda: tmp_path / "rv.db")
    odb.init_db()
    base = dt.date(2025, 1, 1)
    rows = [((base + dt.timedelta(days=i)).isoformat(), 5000.0 + (i % 2) * 7) for i in range(120)]
    assert odb.store_underlying_closes(rows) == 120
    assert odb.underlying_close_count() == 120
    rv = surface.realised_vols(odb.underlying_closes(limit=5000))
    assert rv["10"] is not None and rv["20"] is not None and rv["30"] is not None


def test_rv30_by_date_populates():
    closes = [(f"2025-03-{i+1:02d}", 5000.0 + (i % 3)) for i in range(40)]
    m = surface.rv30_by_date(closes)
    assert len(m) > 0 and all(v >= 0 for v in m.values())


# ── §3 surface_history union: live supersedes reconstructed for a date ───────
def test_surface_history_union_and_counts(tmp_path, monkeypatch):
    from backend.options import db as odb
    monkeypatch.setattr(odb, "db_path", lambda: tmp_path / "sh.db")
    odb.init_db()
    odb.upsert_surface_row("2025-01-01", 20.0, 0.01, None, "reconstructed")
    odb.upsert_surface_row("2025-01-02", 21.0, 0.02, None, "reconstructed")
    odb.upsert_surface_row("2025-01-02", 21.5, 0.03, None, "live")  # supersedes
    hist = dict(odb.surface_history())
    assert list(hist.keys()) == ["2025-01-01", "2025-01-02"]
    assert hist["2025-01-02"]["source"] == "live" and hist["2025-01-02"]["atm_iv_30d"] == 21.5
    counts = odb.surface_source_counts()
    assert counts["reconstructed"] == 1 and counts["live"] == 1
    assert counts["first_reconstructed"] == "2025-01-01"


def test_pooled_percentiles_go_live_from_reconstruction(tmp_path, monkeypatch):
    """The pooled surface percentiles (reconstructed + live) clear the 60-session
    gate immediately instead of PENDING — the core of §3's UI change."""
    from backend.options import db as odb
    monkeypatch.setattr(odb, "db_path", lambda: tmp_path / "sum.db")
    odb.init_db()
    base = dt.date(2024, 1, 1)
    for i in range(70):                            # 70 reconstructed sessions ~20 vol
        odb.upsert_surface_row((base + dt.timedelta(days=i)).isoformat(),
                               20.0 + (i % 5), 0.01 * (i % 3), None, "reconstructed")
    odb.upsert_surface_row("2026-07-24", 25.0, 0.05, None, "live")  # current, high

    surf_hist = odb.surface_history()
    pct = metrics.surface_percentiles(
        surf_hist, rv30={},
        current={"atm_iv_30d": 25.0, "rr_25d": 0.05, "vrp": None})
    assert pct["atm_iv_30d"]["status"] == "ok"          # not PENDING
    assert pct["atm_iv_30d"]["percentile"] is not None
    assert pct["atm_iv_30d"]["sessions"] >= 60
    # VRP has no rv30 history here -> honestly PENDING, never a bare number
    assert pct["vrp"]["status"] == "PENDING"

    counts = odb.surface_source_counts()
    assert counts["reconstructed"] == 70 and counts["live"] == 1


# ── volatility surface (delta x tenor grid, from stored chain rows) ──────────
def _surface_chain(spot, asof, sigma=0.20, tenors=(20, 35, 80)):
    rows = []
    for dd in tenors:
        expiry = (dt.date.fromisoformat(asof) + dt.timedelta(days=dd)).isoformat()
        T = dd / 365.0
        for k in range(int(spot * 0.70), int(spot * 1.30), 25):
            for ct in ("call", "put"):
                rows.append({"strike": float(k), "expiry": expiry, "ctype": ct,
                             "iv": sigma, "delta": bs_delta(spot, float(k), T, sigma, ct),
                             "spot": spot, "oi": 10, "volume": 5})
    return rows


def test_surface_flat_vol_recovers_and_no_arb():
    from backend.options import vol_surface
    asof, spot = "2026-01-05", 5000.0
    s = vol_surface.build_surface(_surface_chain(spot, asof, 0.20), spot, asof)
    assert s["status"] == "ok"
    g30 = next(r for r in s["grid"] if r["tenor"] == 30)
    assert g30["status"] == "ok"
    assert g30["cells"]["ATM"] == pytest.approx(20.0, abs=0.3)
    for v in g30["cells"].values():          # flat surface -> every cell ~20
        if v is not None:
            assert abs(v - 20.0) < 0.8
    # flat vol is arbitrage-free
    assert s["arbitrage"]["calendar_violations"] == []
    assert s["arbitrage"]["butterfly"]["violations"] == 0
    # tenors with no bracketing expiry are honest blanks, not extrapolated
    assert next(r for r in s["grid"] if r["tenor"] == 365)["cells"]["ATM"] is None


def test_surface_atm_cell_matches_atm_iv_30d_card():
    from backend.options import vol_surface, surface as surf
    asof, spot = "2026-01-05", 5000.0
    chain = _surface_chain(spot, asof, 0.22)
    s = vol_surface.build_surface(chain, spot, asof)
    g30 = next(r for r in s["grid"] if r["tenor"] == 30)
    assert g30["cells"]["ATM"] == pytest.approx(surf.atm_iv_30d(chain, spot, asof), abs=0.05)


def test_surface_reports_calendar_violation():
    from backend.options import vol_surface
    pts = [{"expiry": "e1", "days": 20, "values": {"ATM": 0.30}},
           {"expiry": "e2", "days": 35, "values": {"ATM": 0.10}}]   # var falls -> bad
    v = vol_surface._calendar_violations(pts)
    assert len(v) == 1 and v[0]["from"] == "e1"
    ok = [{"expiry": "e1", "days": 20, "values": {"ATM": 0.20}},
          {"expiry": "e2", "days": 35, "values": {"ATM": 0.20}}]
    assert vol_surface._calendar_violations(ok) == []


def test_surface_reports_butterfly_violation():
    from backend.options import vol_surface
    asof = "2026-01-05"
    exp = (dt.date.fromisoformat(asof) + dt.timedelta(days=30)).isoformat()
    # middle strike priced with an absurdly high IV -> non-convex call prices
    slices = {exp: [{"strike": 4900.0, "ctype": "call", "iv": 0.20},
                    {"strike": 5000.0, "ctype": "call", "iv": 0.80},
                    {"strike": 5100.0, "ctype": "call", "iv": 0.20}]}
    r = vol_surface._butterfly_violations(slices, 5000.0, asof)
    assert r["checked_triples"] == 1 and r["violations"] >= 1


def test_surface_delta_interp_no_extrapolation():
    from backend.options.vol_surface import _iv_at_abs_delta
    rows = [{"ctype": "call", "delta": 0.20, "iv": 0.25},
            {"ctype": "call", "delta": 0.40, "iv": 0.21}]
    assert _iv_at_abs_delta(rows, "call", 0.30) == pytest.approx(0.23, abs=1e-9)
    assert _iv_at_abs_delta(rows, "call", 0.10) is None    # below observed range
    assert _iv_at_abs_delta(rows, "call", 0.55) is None    # above observed range


def test_surface_empty_when_no_spot():
    from backend.options import vol_surface
    assert vol_surface.build_surface([], None, "2026-01-05")["status"] == "empty"
    rows = _surface_chain(5000.0, "2026-01-05")
    assert vol_surface.build_surface(rows, None, "2026-01-05")["status"] == "empty"


def test_surface_excludes_and_counts_out_of_range_iv():
    from backend.options import vol_surface
    asof, spot = "2026-01-05", 5000.0
    chain = _surface_chain(spot, asof, 0.20)
    for r in chain[:10]:
        r["iv"] = 3.0      # 300% -> outside 3%-150%, must be excluded + counted
    s = vol_surface.build_surface(chain, spot, asof)
    assert s["coverage"]["excluded"]["iv_out_of_range"] == 10


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
