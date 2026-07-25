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
from .config import CAPABILITIES_PATH, UNDERLYING, GAMMA_ASSUMPTION_TEXT
from .spot import fetch_spot_fallback, fetch_underlying_history, SOURCE_CHAIN

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

    # Trading-day guard: no US session on Sat/Sun. Guards BOTH the manual button
    # and the scheduler at the source, so a weekend "Run snapshot now" can't
    # photograph the prior session under a new date.
    if dt.date.fromisoformat(snap_date).weekday() >= 5:
        return {"status": "skipped",
                "reason": f"{snap_date} is a weekend — US markets closed, no snapshot taken"}

    # Stale-session guard (holidays): the vendor re-serves the PRIOR session's
    # chain on non-trading weekdays. If this is a NEW date whose spot equals the
    # last stored close, no new session has occurred — record nothing rather than
    # duplicate the previous session under today's date. (Re-running an existing
    # date is an intentional idempotent upsert and is allowed.)
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

    # Spot: chain-embedded underlying price when the plan provides it; else the
    # ^GSPC index level (same underlying, different vendor — see spot.py). If
    # neither exists the day computes as an honest "empty", never an estimate.
    spot_source = SOURCE_CHAIN if spot else None
    if spot is None:                       # reuse the spot already fetched for the guard
        spot, spot_source = prelim_spot, prelim_source
    if spot:
        db.store_underlying_close(snap_date, float(spot))

    # Seed ^GSPC daily-close history on early runs so realised vol / VRP are
    # live from day one (see spot.py: underlying level is not a forbidden
    # third-party backfill). Idempotent; skipped once enough history exists.
    if db.underlying_close_count() < _UNDERLYING_SEED_BELOW:
        seeded = db.store_underlying_closes(fetch_underlying_history("5y"))
        if seeded:
            print(f"[OPTIONS] seeded {seeded} ^GSPC daily closes")

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

    kept, hygiene = metrics.apply_hygiene(rows, spot)
    delta_rows = metrics.delta_oi_rows(kept, prior_oi, prior5_oi, snap_date)

    # spot changes from our own stored closes (forward-only store). Dedup a
    # weekend/holiday re-serve so 1d/5d changes never read a fake 0% and the
    # realised-vol series never eats a zero return.
    closes = surface.dedup_closes(db.underlying_closes())
    spot_chg_1d = _pct_change(closes, 1)
    spot_chg_5d = _pct_change(closes, 5)

    # surface metrics on the band-filtered set (stale filter applies to
    # POSITIONING aggregates; pricing uses live quotes' IVs on kept set too —
    # stale strikes have unreliable IV marks, so kept set is right for both)
    surf = {
        "atm_iv_30d": surface.atm_iv_30d(kept, spot, snap_date),
        "rr_25d": surface.risk_reversal_25d(kept, spot, snap_date),
        "term_structure": surface.term_structure(kept, spot, snap_date),
        "realised": surface.realised_vols(closes),
        "realised_days": len(closes),
        "methods": {"atm": surface.ATM_METHOD, "vrp": surface.VRP_LABEL,
                    "rv": surface.RV_METHOD},
    }
    rv30 = surf["realised"].get("30")
    surf["vrp"] = (round(surf["atm_iv_30d"] - rv30, 2)
                   if surf["atm_iv_30d"] is not None and rv30 is not None else None)

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
        "gamma": {**gamma.run_sweep(delta_rows, spot, snap_date),
                  "model": True,
                  "assumption": GAMMA_ASSUMPTION_TEXT},
        "surface": surf,
    }
    return payload


def _pct_change(closes, n):
    if len(closes) <= n:
        return None
    a, b = closes[-1][1], closes[-1 - n][1]
    if not a or not b:
        return None
    return round((a / b - 1) * 100, 2)
