"""SQLite store for daily options snapshots (stdlib sqlite3, pandas-free).

Four tables:
  contract_day    one row per contract per snapshot date (the raw facts)
  daily_metrics   one row per date: the computed aggregate JSON, so percentile
                  history accumulates from day one even if metric code evolves
  underlying_day  one row per date: index close. Sourced from ^GSPC (Yahoo),
                  the same vendor/series used for spot — seeded with history so
                  realised vol computes immediately (see spot.py for why this
                  is not a "third-party backfill" in the forbidden sense).
  surface_history one row per date of constant-maturity surface metrics with a
                  `source` column ('reconstructed' | 'live'). The live snapshot
                  appends its 'live' row here; the 2Y backfill writes
                  'reconstructed' rows. Percentiles read the UNION so pricing
                  percentiles go live without waiting 60 sessions.

OPTIONS-derived positioning (ΔOI) and live vendor IV remain FORWARD ONLY from
our own snapshots — only the underlying index level and reconstructed surface
IV (labelled as such) are historical.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager

from .config import db_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contract_day (
    snap_date   TEXT NOT NULL,          -- YYYY-MM-DD (US-Eastern trade date)
    ticker      TEXT NOT NULL,          -- e.g. O:SPXW230712C04500000
    strike      REAL NOT NULL,
    expiry      TEXT NOT NULL,          -- YYYY-MM-DD
    ctype       TEXT NOT NULL,          -- 'call' | 'put'
    oi          INTEGER,
    volume      INTEGER,
    iv          REAL,
    delta       REAL,
    gamma       REAL,
    spot        REAL,                   -- underlying price from same response
    PRIMARY KEY (snap_date, ticker)
);
CREATE INDEX IF NOT EXISTS ix_cd_date ON contract_day (snap_date);
CREATE INDEX IF NOT EXISTS ix_cd_ticker ON contract_day (ticker, snap_date);

CREATE TABLE IF NOT EXISTS daily_metrics (
    snap_date   TEXT PRIMARY KEY,
    payload     TEXT NOT NULL           -- JSON aggregate row
);

CREATE TABLE IF NOT EXISTS underlying_day (
    snap_date   TEXT PRIMARY KEY,
    close       REAL NOT NULL,
    high        REAL,               -- for Parkinson (high/low) realised vol
    low         REAL
);

CREATE TABLE IF NOT EXISTS surface_history (
    date        TEXT PRIMARY KEY,       -- YYYY-MM-DD trade date
    atm_iv_30d  REAL,                   -- 30d constant-maturity ATM IV, vol %
    rr_25d_norm REAL,                   -- (25d put IV - 25d call IV) / ATM
    term_json   TEXT,                   -- optional term points, JSON or NULL
    source      TEXT NOT NULL           -- 'reconstructed' | 'live'
);
"""

_lock = threading.Lock()


@contextmanager
def conn():
    c = sqlite3.connect(db_path(), timeout=30)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
    with _lock, conn() as c:
        c.executescript(_SCHEMA)
        # Migration: add OHLC columns to a pre-existing underlying_day table
        # (CREATE IF NOT EXISTS won't alter an existing table).
        cols = {r[1] for r in c.execute("PRAGMA table_info(underlying_day)")}
        for col in ("high", "low"):
            if col not in cols:
                c.execute(f"ALTER TABLE underlying_day ADD COLUMN {col} REAL")


def upsert_contracts(rows):
    """rows: iterable of dicts matching contract_day columns. Idempotent."""
    with _lock, conn() as c:
        c.executemany(
            """INSERT INTO contract_day
               (snap_date, ticker, strike, expiry, ctype, oi, volume, iv, delta, gamma, spot)
               VALUES (:snap_date,:ticker,:strike,:expiry,:ctype,:oi,:volume,:iv,:delta,:gamma,:spot)
               ON CONFLICT(snap_date, ticker) DO UPDATE SET
                 oi=excluded.oi, volume=excluded.volume, iv=excluded.iv,
                 delta=excluded.delta, gamma=excluded.gamma, spot=excluded.spot""",
            list(rows))


def store_underlying_close(snap_date: str, close: float, high=None, low=None):
    with _lock, conn() as c:
        c.execute("INSERT INTO underlying_day (snap_date, close, high, low) VALUES (?,?,?,?) "
                  "ON CONFLICT(snap_date) DO UPDATE SET close=excluded.close, "
                  "high=excluded.high, low=excluded.low",
                  (snap_date, float(close), high, low))


def store_underlying_closes(rows):
    """Bulk upsert of ^GSPC history. Rows are (date, close) or (date, close, high, low)."""
    norm = []
    for r in rows:
        if r[1] is None:
            continue
        d, c = r[0], float(r[1])
        h = float(r[2]) if len(r) > 2 and r[2] is not None else None
        lo = float(r[3]) if len(r) > 3 and r[3] is not None else None
        norm.append((d, c, h, lo))
    if not norm:
        return 0
    with _lock, conn() as c:
        c.executemany("INSERT INTO underlying_day (snap_date, close, high, low) VALUES (?,?,?,?) "
                      "ON CONFLICT(snap_date) DO UPDATE SET close=excluded.close, "
                      "high=excluded.high, low=excluded.low", norm)
    return len(norm)


def underlying_close_count() -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM underlying_day").fetchone()[0]


def underlying_ohlc_missing() -> bool:
    """True if any stored close lacks high/low — triggers a one-time OHLC re-seed
    so Parkinson realised vol has its high/low inputs."""
    with conn() as c:
        n = c.execute("SELECT COUNT(*) FROM underlying_day WHERE high IS NULL").fetchone()[0]
    return n > 0


def underlying_ohlc(limit: int = 400):
    """[(date, close, high, low)] ascending, most recent `limit`."""
    with conn() as c:
        rows = list(c.execute(
            "SELECT snap_date, close, high, low FROM underlying_day "
            "ORDER BY snap_date DESC LIMIT ?", (limit,)))
    return [(r[0], r[1], r[2], r[3]) for r in reversed(rows)]


# ── surface_history (reconstructed + live union for pricing percentiles) ─────
def upsert_surface_row(date, atm_iv_30d, rr_25d_norm, term_json, source):
    """One constant-maturity surface row. `source` is 'reconstructed' | 'live'.
    A 'live' write overwrites a 'reconstructed' row for the same date (the live
    vendor value supersedes our reconstruction once we have it)."""
    with _lock, conn() as c:
        c.execute(
            """INSERT INTO surface_history (date, atm_iv_30d, rr_25d_norm, term_json, source)
               VALUES (?,?,?,?,?)
               ON CONFLICT(date) DO UPDATE SET
                 atm_iv_30d=excluded.atm_iv_30d, rr_25d_norm=excluded.rr_25d_norm,
                 term_json=excluded.term_json, source=excluded.source""",
            (date, atm_iv_30d, rr_25d_norm, term_json, source))


def surface_history(limit: int = 1200):
    """[(date, {atm_iv_30d, rr_25d_norm, source})] ascending — reconstructed + live."""
    with conn() as c:
        rows = list(c.execute(
            "SELECT date, atm_iv_30d, rr_25d_norm, source FROM surface_history "
            "ORDER BY date DESC LIMIT ?", (limit,)))
    return [(r[0], {"atm_iv_30d": r[1], "rr_25d_norm": r[2], "source": r[3]})
            for r in reversed(rows)]


def surface_source_counts():
    """{'reconstructed': n, 'live': n, 'first_reconstructed': date|None,
        'first_live': date|None} — for the UI 'history' note."""
    out = {"reconstructed": 0, "live": 0, "first_reconstructed": None, "first_live": None}
    with conn() as c:
        for source, n, first in c.execute(
            "SELECT source, COUNT(*), MIN(date) FROM surface_history GROUP BY source"):
            if source in out:
                out[source] = n
                out[f"first_{source}"] = first
    return out


def store_daily_metrics(snap_date: str, payload: dict):
    with _lock, conn() as c:
        c.execute("INSERT OR REPLACE INTO daily_metrics VALUES (?,?)",
                  (snap_date, json.dumps(payload)))


def snapshot_dates():
    """All snapshot dates, ascending."""
    with conn() as c:
        return [r[0] for r in c.execute(
            "SELECT DISTINCT snap_date FROM contract_day ORDER BY snap_date")]


def contracts_for(snap_date: str):
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM contract_day WHERE snap_date=?", (snap_date,))]


def trailing_volume_avg(snap_date: str, n: int = 5):
    """{ticker: avg volume over the last n sessions up to snap_date} — the
    denominator for the 5-session stale test (B3)."""
    with conn() as c:
        dates = [r[0] for r in c.execute(
            "SELECT DISTINCT snap_date FROM contract_day WHERE snap_date<=? "
            "ORDER BY snap_date DESC LIMIT ?", (snap_date, n))]
        if not dates:
            return {}
        ph = ",".join("?" * len(dates))
        return {r[0]: r[1] for r in c.execute(
            f"SELECT ticker, AVG(COALESCE(volume,0)) FROM contract_day "
            f"WHERE snap_date IN ({ph}) GROUP BY ticker", dates)}


def oi_map_for(snap_date: str):
    """{ticker: oi} for a date — light lookup for ΔOI joins."""
    with conn() as c:
        return {r[0]: r[1] for r in c.execute(
            "SELECT ticker, oi FROM contract_day WHERE snap_date=?", (snap_date,))}


def underlying_closes(limit: int = 400):
    """[(date, close)] ascending, most recent `limit`."""
    with conn() as c:
        rows = list(c.execute(
            "SELECT snap_date, close FROM underlying_day ORDER BY snap_date DESC LIMIT ?",
            (limit,)))
    return [(r[0], r[1]) for r in reversed(rows)]


def metrics_history(keys, limit: int = 400):
    """For percentile/sparkline series: [(date, {key: value})] ascending.
    Pulls only the requested keys out of each stored aggregate row."""
    with conn() as c:
        rows = list(c.execute(
            "SELECT snap_date, payload FROM daily_metrics ORDER BY snap_date DESC LIMIT ?",
            (limit,)))
    out = []
    for d, payload in reversed(rows):
        try:
            full = json.loads(payload)
        except Exception:
            continue
        out.append((d, {k: _dig(full, k) for k in keys}))
    return out


def _dig(d, dotted):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def delete_session(date: str):
    """Remove one snapshot session from all tables (live surface row only —
    reconstructed rows are keyed by date but belong to the backfill)."""
    with _lock, conn() as c:
        c.execute("DELETE FROM contract_day WHERE snap_date=?", (date,))
        c.execute("DELETE FROM daily_metrics WHERE snap_date=?", (date,))
        c.execute("DELETE FROM underlying_day WHERE snap_date=?", (date,))
        c.execute("DELETE FROM surface_history WHERE date=? AND source='live'", (date,))


def session_fingerprint(date: str):
    """(close, total_oi) for a stored session — used to reject a chain re-serve
    whose close AND open-interest exactly match the prior session."""
    with conn() as c:
        close = c.execute("SELECT close FROM underlying_day WHERE snap_date=?", (date,)).fetchone()
        oi = c.execute("SELECT COALESCE(SUM(oi),0) FROM contract_day WHERE snap_date=?", (date,)).fetchone()
    return (close[0] if close else None, oi[0] if oi else 0)


def prune_duplicate_sessions(tol: float = 0.005):
    """Remove snapshot sessions whose underlying close is identical (within tol)
    to the chronologically prior session's — the signature of a non-trading-day
    (weekend/holiday) snapshot that photographed the previous session again.

    Cleans all four tables so the session counter, ΔOI history, realised-vol
    series and surface history reflect only real sessions. ^GSPC to the cent
    never repeats on consecutive real sessions, so this only ever removes the
    artifact. Returns the removed dates."""
    with _lock, conn() as c:
        dates = [r[0] for r in c.execute(
            "SELECT DISTINCT snap_date FROM contract_day ORDER BY snap_date")]
        closes = {r[0]: r[1] for r in c.execute(
            "SELECT snap_date, close FROM underlying_day")}
        removed, prev = [], None
        for d in dates:
            close = closes.get(d)
            if close is None:
                continue
            if prev is not None and abs(close - prev) < tol:
                removed.append(d)          # duplicate: keep prev, drop this one
            else:
                prev = close
        for d in removed:
            c.execute("DELETE FROM contract_day WHERE snap_date=?", (d,))
            c.execute("DELETE FROM daily_metrics WHERE snap_date=?", (d,))
            c.execute("DELETE FROM underlying_day WHERE snap_date=?", (d,))
            c.execute("DELETE FROM surface_history WHERE date=? AND source='live'", (d,))
    return removed


def latest_metrics():
    with conn() as c:
        row = c.execute(
            "SELECT snap_date, payload FROM daily_metrics ORDER BY snap_date DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None, None
    return row[0], json.loads(row[1])
