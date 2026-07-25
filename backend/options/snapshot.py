"""Daily snapshot job + per-day metric computation.

Pulls the full I:SPX chain once per day after US close, persists per-contract
rows + one daily aggregate row (so percentile history accumulates from day
one), and computes the metric payload the API serves.

Cold-start rule (hard): with no history, every Δ/percentile is PENDING with
the first-snapshot date stated — never a fabricated or proxied number.
"""

import json
import datetime as dt
from zoneinfo import ZoneInfo

from . import db, metrics, gamma, surface
from .config import CAPABILITIES_PATH, UNDERLYING, GAMMA_ASSUMPTION_TEXT, SURFACE_TENORS
from .spot import fetch_spot_fallback, fetch_underlying_history, fetch_today_ohlc, SOURCE_CHAIN
from .trading_calendar import is_trading_day, calendar_source

# Seed ^GSPC history when the underlying store is this thin (first runs), so
# realised vol / VRP compute immediately instead of accumulating slowly.
_UNDERLYING_SEED_BELOW = 60

_BATCH = 500


def capabilities() -> dict | None:
    """Capability report written by scripts/probe_massive.py, or None if the
    probe has never been run."""
    try:
        return json.loads(CAPABILITIES_PATH.read_text())
    except Exception:
        return None


def trade_date() -> str:
    """US-Eastern trade date (the snapshot runs after the close)."""
    return dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()


# ^GSPC to the cent never repeats on consecutive real sessions, so an identical
# close on a NEW date is a weekend/holiday re-serve, not a flat market.
_SAME_CLOSE_TOL = 0.005


def run_daily_snapshot() -> dict:
    """Pull the chain, persist it, compute + store the day's metrics.

    Returns a summary dict; on a gated tier ({open_interest: false}) returns a
    blocked state instead of writing empty rows.
    """
    from .client import iter_chain_snapshot, MassiveError

    caps = capabilities()
    if caps is not None and caps.get("reachable") and not caps.get("open_interest"):
        return {"status": "blocked",
                "reason": "API key has no open-interest access — requires Options Starter plan",
                "capabilities": caps}

    db.init_db()
    # Self-heal any weekend/holiday duplicate already in the store (idempotent;
    # a no-op once clean, since real ^GSPC closes never repeat consecutively).
    pruned = db.prune_duplicate_sessions()
    if pruned:
        print(f"[OPTIONS] pruned non-trading-day duplicate sessions: {pruned}")

    snap_date = trade_date()

    # Trading-day guard (A1): reject weekends AND NYSE holidays via the XNYS
    # calendar. Guards BOTH the manual button and the scheduler at the source,
    # so a non-trading-day "Run snapshot now" can't photograph the prior session
    # under a new date. Re-running an EXISTING date stays an idempotent upsert.
    if snap_date not in db.snapshot_dates() and not is_trading_day(snap_date):
        return {"status": "skipped",
                "reason": f"{snap_date} is not an NYSE trading day ({calendar_source()}) — "
                          "no snapshot taken"}

    # Stale-session guard: even on a listed trading day the vendor can re-serve
    # the prior session (data delay). If this is a NEW date whose spot equals the
    # last stored close, no new session has occurred — record nothing.
    prelim_spot, prelim_source = fetch_spot_fallback()
    existing = db.snapshot_dates()
    if snap_date not in existing and prelim_spot:
        closes = db.underlying_closes()
        if closes and closes[-1][0] != snap_date and abs(closes[-1][1] - prelim_spot) < _SAME_CLOSE_TOL:
            return {"status": "skipped",
                    "reason": f"{snap_date}: spot {prelim_spot:.2f} identical to the {closes[-1][0]} "
                              "close — market closed (holiday); no new session recorded"}

    batch = []
    n = 0
    spot = None
    try:
        for c in iter_chain_snapshot(UNDERLYING):
            c["snap_date"] = snap_date
            if c.get("spot"):
                spot = c["spot"]
            batch.append(c)
            if len(batch) >= _BATCH:
                db.upsert_contracts(batch)
                n += len(batch)
                batch = []
        if batch:
            db.upsert_contracts(batch)
            n += len(batch)
    except MassiveError as e:
        return {"status": "failed", "reason": str(e), "rows_written": n}

    if n == 0:
        return {"status": "failed", "reason": "chain snapshot returned no contracts"}

    # Duplicate-fingerprint guard (A1): reject a chain re-serve whose total open
    # interest is byte-identical to the prior stored session. Total SPX OI (millions
    # of contracts, opening/closing daily) never repeats exactly across two real
    # sessions, so an exact match is a re-pull the pre-pull close guard can miss
    # (spot ticked but the chain is yesterday's). Roll back and record nothing.
    if snap_date not in existing:
        prev_date = existing[-1] if existing else None
        if prev_date:
            _, prev_oi = db.session_fingerprint(prev_date)
            new_oi = db.session_fingerprint(snap_date)[1]
            if new_oi > 0 and new_oi == prev_oi:
                db.delete_session(snap_date)
                return {"status": "skipped",
                        "reason": f"{snap_date}: total OI {new_oi} identical to {prev_date} — "
                                  "duplicate chain re-serve, rejected"}

    # Spot: chain-embedded underlying price when the plan provides it; else the
    # ^GSPC index level (same underlying, different vendor — see spot.py). If
    # neither exists the day computes as an honest "empty", never an estimate.
    spot_source = SOURCE_CHAIN if spot else None
    if spot is None:                       # reuse the spot already fetched for the guard
        spot, spot_source = prelim_spot, prelim_source
    if spot:
        hi, lo = fetch_today_ohlc()        # today's high/low for Parkinson vol
        db.store_underlying_close(snap_date, float(spot), hi, lo)

    # Seed ^GSPC daily bars on early runs (or once, to backfill OHLC for the
    # Parkinson estimator) so realised vol / VRP are live from day one. Idempotent.
    if db.underlying_close_count() < _UNDERLYING_SEED_BELOW or db.underlying_ohlc_missing():
        seeded = db.store_underlying_closes(fetch_underlying_history("5y"))
        if seeded:
            print(f"[OPTIONS] seeded {seeded} ^GSPC daily bars (OHLC)")

    payload = compute_daily(snap_date)
    if payload.get("status") == "ok" and spot_source:
        payload["spot_source"] = spot_source
    db.store_daily_metrics(snap_date, payload)
    _store_live_surface_row(snap_date, payload)
    return {"status": "ok", "snap_date": snap_date, "rows_written": n,
            "spot": spot, "spot_source": spot_source,
            "metrics_status": payload.get("status"), "metrics_stored": True}


def _store_live_surface_row(snap_date: str, payload: dict):
    """Append the day's live vendor surface metrics into surface_history so
    pricing percentiles pool reconstructed + live history. 'live' supersedes a
    'reconstructed' row for the same date."""
    if payload.get("status") != "ok":
        return
    surf = payload.get("surface") or {}
    rr = surf.get("rr_25d") or {}
    term = surf.get("term_structure")
    db.upsert_surface_row(
        snap_date,
        surf.get("atm_iv_30d"),
        rr.get("value") if isinstance(rr, dict) else None,
        json.dumps(term) if term else None,
        "live")


def _prior_sessions(dates, snap_date):
    """(prev session, 5-sessions-back) date strings or None each."""
    before = [d for d in dates if d < snap_date]
    prev = before[-1] if before else None
    back5 = before[-5] if len(before) >= 5 else None
    return prev, back5


def compute_daily(snap_date: str) -> dict:
    """Compute the full metric payload for one stored snapshot date."""
    rows = db.contracts_for(snap_date)
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    if not rows:
        return {"snap_date": snap_date, "generated_at": generated_at,
                "status": "empty", "reason": "no contracts stored for this date"}

    spot = next((r["spot"] for r in rows if r.get("spot")), None)
    spot_source = SOURCE_CHAIN if spot is not None else None
    if spot is None:
        closes = dict(db.underlying_closes())
        spot = closes.get(snap_date)
        if spot is not None:
            spot_source = "stored underlying close"
    if spot is None:
        return {"snap_date": snap_date, "generated_at": generated_at,
                "status": "empty", "reason": "no underlying spot recorded"}

    dates = db.snapshot_dates()
    first_date = dates[0] if dates else snap_date
    prev_d, back5_d = _prior_sessions(dates, snap_date)
    prior_oi = db.oi_map_for(prev_d) if prev_d else None
    prior5_oi = db.oi_map_for(back5_d) if back5_d else None

    # Stale test basis (B3): trailing 5-session avg volume once >5 sessions
    # exist, so a single quiet day doesn't flag a live strike; 1-day until then.
    avg_vol = db.trailing_volume_avg(snap_date, 5) if len(dates) > 5 else None
    kept, hygiene = metrics.apply_hygiene(rows, spot, avg_vol=avg_vol)
    delta_rows = metrics.delta_oi_rows(kept, prior_oi, prior5_oi, snap_date)

    # spot changes from our own stored closes (forward-only store). Dedup a
    # weekend/holiday re-serve so 1d/5d changes never read a fake 0% and the
    # realised-vol series never eats a zero return.
    ohlc = db.underlying_ohlc(limit=5000)
    closes = surface.dedup_closes([(d, c) for d, c, _h, _l in ohlc])
    spot_chg_1d = _pct_change(closes, 1)
    spot_chg_5d = _pct_change(closes, 5)

    # surface metrics on the band-filtered set (stale filter applies to
    # POSITIONING aggregates; pricing uses live quotes' IVs on kept set too —
    # stale strikes have unreliable IV marks, so kept set is right for both).
    # Term structure is constant-maturity (A4) — same interpolation as the CM
    # grid, so the two can't disagree.
    cc_rv = surface.realised_vols(closes)
    pk_rv = surface.parkinson_vols(ohlc)
    atm30 = surface.atm_iv_30d(kept, spot, snap_date)
    surf = {
        "atm_iv_30d": atm30,
        "rr_25d": surface.risk_reversal_25d(kept, spot, snap_date),
        "term_structure": surface.atm_term_cm(kept, spot, snap_date, SURFACE_TENORS),
        "term_method": "constant-maturity",
        "realised": cc_rv,
        "realised_parkinson": pk_rv,
        "realised_days": len(closes),
        "methods": {"atm": surface.ATM_METHOD, "vrp": surface.VRP_LABEL,
                    "rv": surface.RV_METHOD, "parkinson": surface.PARKINSON_METHOD},
    }
    # VRP against all three RV windows (A3), RV30 kept as the labelled headline.
    def _vrp(rv):
        return round(atm30 - rv, 2) if atm30 is not None and rv is not None else None
    surf["vrp"] = _vrp(cc_rv.get("30"))
    surf["vrp_by_window"] = {w: _vrp(cc_rv.get(w)) for w in ("10", "20", "30")}
    rv20, rv30 = cc_rv.get("20"), cc_rv.get("30")
    surf["rv_window_flag"] = bool(rv20 is not None and rv30 is not None and abs(rv30 - rv20) > 1.5)

    payload = {
        "snap_date": snap_date,
        "generated_at": generated_at,
        "status": "ok",
        "spot": spot,
        "spot_source": spot_source,
        "spot_chg_1d_pct": spot_chg_1d,
        "spot_chg_5d_pct": spot_chg_5d,
        "hygiene": {**hygiene, "kept_count": len(kept),
                    "kept_oi": sum(r["oi"] for r in kept)},
        "history": {"sessions": len(dates), "first_date": first_date,
                    "prev_session": prev_d, "session_5_back": back5_d},
        "positioning": {
            "buckets": metrics.bucket_aggregates(delta_rows),
            "top_delta": metrics.top_delta_strikes(delta_rows, spot),
            "top_volume": metrics.top_volume_strikes(delta_rows, spot),
            "delta_status": "ok" if prev_d else f"PENDING — history from {first_date}",
            "delta5_status": "ok" if back5_d else f"PENDING — history from {first_date}",
        },
        "gamma": _gamma_both_ways(rows, kept, spot, snap_date),
        "surface": surf,
    }
    return payload


def _gamma_both_ways(rows, kept, spot, snap_date):
    """Gamma computed on BOTH the stale-filtered and the full in-band OI (B1).

    Positioning asks "what did people do today" (stale filter right); gamma asks
    "what exposure exists" — a contract that didn't trade today is still open and
    still hedged, so gamma should see all in-band OI. We compute both, DEFAULT the
    displayed panel to unfiltered (more defensible), and report the filtered
    numbers + the a=1.00 flip gap so the choice is auditable. If the two flip
    levels differ by <0.5% of spot the filter is immaterial for gamma."""
    filtered = gamma.run_sweep(kept, spot, snap_date)
    unfiltered = gamma.run_sweep(metrics.band_in_contracts(rows, spot), spot, snap_date)

    def _flip1(g):
        xs = g["crossings"].get("1.00", [])
        return xs[0] if xs else None
    ff, fu = _flip1(filtered), _flip1(unfiltered)
    delta_pct = (abs(ff - fu) / spot * 100) if (ff is not None and fu is not None and spot) else None
    immaterial = delta_pct is not None and delta_pct < 0.5

    return {
        **unfiltered,                       # displayed panel = unfiltered (default)
        "model": True,
        "assumption": GAMMA_ASSUMPTION_TEXT,
        "basis": "unfiltered (all in-band OI — includes strikes that did not trade today)",
        "comparison": {
            "filtered": {"gross_at_spot": filtered["gross_at_spot"], "flip_1_00": ff,
                         "n_contracts": filtered["n_contracts_used"]},
            "unfiltered": {"gross_at_spot": unfiltered["gross_at_spot"], "flip_1_00": fu,
                           "n_contracts": unfiltered["n_contracts_used"]},
            "flip_delta_pct": round(delta_pct, 3) if delta_pct is not None else None,
            "immaterial": immaterial,
            "note": ("filter choice immaterial for gamma (<0.5% of spot) — defaulting to unfiltered"
                     if immaterial else
                     "filter choice is material for gamma — both shown, unfiltered displayed"),
        },
    }


def _pct_change(closes, n):
    if len(closes) <= n:
        return None
    a, b = closes[-1][1], closes[-1 - n][1]
    if not a or not b:
        return None
    return round((a / b - 1) * 100, 2)
