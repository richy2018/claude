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
    close       REAL NOT NULL
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


def store_underlying_close(snap_date: str, close: float):
    with _lock, conn() as c:
        c.execute("INSERT OR REPLACE INTO underlying_day VALUES (?,?)", (snap_date, close))


def store_underlying_closes(rows):
    """Bulk upsert [(date, close)] — used to seed ^GSPC history. Idempotent."""
    rows = [(d, float(v)) for d, v in rows if v is not None]
    if not rows:
        return 0
    with _lock, conn() as c:
        c.executemany("INSERT OR REPLACE INTO underlying_day VALUES (?,?)", rows)
    return len(rows)


def underlying_close_count() -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM underlying_day").fetchone()[0]


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


def latest_metrics():
    with conn() as c:
        row = c.execute(
            "SELECT snap_date, payload FROM daily_metrics ORDER BY snap_date DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None, None
    return row[0], json.loads(row[1])
