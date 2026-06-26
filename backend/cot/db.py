"""Persistence for COT observations.

Schema is the PostgreSQL DDL from the brief (§6), implemented with SQLAlchemy
Core so it runs unchanged on Postgres (production, via DATABASE_URL) and on
SQLite (local/dev and the Render persistent disk when no Postgres is wired).
COT index / z-score are computed on read (transform.py), never stored
denormalised — exactly as specified.

Incremental loads use an upsert keyed on the unique tuple
(report_date, symbol, report_type, cohort) because CFTC revises prior weeks.
"""

import os
from pathlib import Path

from sqlalchemy import (
    create_engine, MetaData, Table, Column, BigInteger, Integer, Text, Date,
    DateTime, UniqueConstraint, Index, func, select,
)
from sqlalchemy.engine import Engine

_metadata = MetaData()

# BIGSERIAL on Postgres; on SQLite a plain INTEGER PK aliases rowid so it
# autoincrements (a BigInteger PK does not trigger SQLite's rowid autoincrement).
_PK_TYPE = BigInteger().with_variant(Integer, "sqlite")

# Mirrors the §6 DDL. BIGSERIAL -> autoincrement BigInteger PK.
cot_observation = Table(
    "cot_observation", _metadata,
    Column("id", _PK_TYPE, primary_key=True, autoincrement=True),
    Column("report_date", Date, nullable=False),
    Column("symbol", Text, nullable=False),            # friendly key from CONTRACTS
    Column("contract_name", Text, nullable=False),     # raw CFTC name, verbatim
    Column("report_type", Text, nullable=False),       # legacy_fut|tff_fut|disaggregated_fut
    Column("cohort", Text, nullable=False),            # lev_funds, managed_money, non_comm, ...
    Column("longs", BigInteger),
    Column("shorts", BigInteger),
    Column("net", BigInteger),
    Column("open_interest", BigInteger),
    Column("ingested_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("report_date", "symbol", "report_type", "cohort",
                     name="uq_cot_observation"),
    Index("ix_cot", "symbol", "report_type", "report_date"),
)

_engine: Engine | None = None


def _database_url() -> str:
    """Resolve the DB URL. Postgres in prod via DATABASE_URL; otherwise SQLite
    on the Render persistent disk if present, else alongside the cache file."""
    url = os.environ.get("DATABASE_URL")
    if url:
        # Render/Heroku style postgres:// -> postgresql:// for SQLAlchemy.
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url
    render_disk = Path("/opt/render/data")
    base = render_disk if render_disk.exists() else Path(__file__).resolve().parent.parent / "data"
    base.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{base / 'cot.db'}"


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = _database_url()
        kwargs = {"future": True, "pool_pre_ping": True} if url.startswith("postgresql") else {"future": True}
        _engine = create_engine(url, **kwargs)
        print(f"[COT-DB] engine: {url.split('@')[-1] if '@' in url else url}")
    return _engine


def init_db():
    """Create the table + indexes if absent. Idempotent — safe migration."""
    _metadata.create_all(get_engine())


def upsert_observations(rows: list[dict]) -> int:
    """Insert-or-update by the unique key. CFTC revises prior weeks, so on
    conflict we overwrite longs/shorts/net/open_interest and contract_name.
    Returns the number of rows processed. Dialect-aware (Postgres / SQLite)."""
    if not rows:
        return 0
    init_db()
    engine = get_engine()
    dialect = engine.dialect.name

    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        stmt = pg_insert(cot_observation)
        update_cols = {
            "contract_name": stmt.excluded.contract_name,
            "longs": stmt.excluded.longs,
            "shorts": stmt.excluded.shorts,
            "net": stmt.excluded.net,
            "open_interest": stmt.excluded.open_interest,
            "ingested_at": func.now(),
        }
        stmt = stmt.on_conflict_do_update(
            constraint="uq_cot_observation", set_=update_cols)
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        stmt = sqlite_insert(cot_observation)
        update_cols = {
            "contract_name": stmt.excluded.contract_name,
            "longs": stmt.excluded.longs,
            "shorts": stmt.excluded.shorts,
            "net": stmt.excluded.net,
            "open_interest": stmt.excluded.open_interest,
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["report_date", "symbol", "report_type", "cohort"],
            set_=update_cols)
    else:  # generic fallback: delete-then-insert per key (rare)
        with engine.begin() as conn:
            for r in rows:
                conn.execute(
                    cot_observation.delete().where(
                        (cot_observation.c.report_date == r["report_date"]) &
                        (cot_observation.c.symbol == r["symbol"]) &
                        (cot_observation.c.report_type == r["report_type"]) &
                        (cot_observation.c.cohort == r["cohort"])
                    )
                )
                conn.execute(cot_observation.insert().values(**r))
        return len(rows)

    with engine.begin() as conn:
        # executemany in chunks to stay well under driver param limits
        CHUNK = 500
        for i in range(0, len(rows), CHUNK):
            conn.execute(stmt, rows[i:i + CHUNK])
    return len(rows)


def latest_report_date(symbol: str | None = None, report_type: str | None = None):
    """Most recent stored report_date (overall, or for a symbol/report)."""
    engine = get_engine()
    if not _table_exists(engine):
        return None
    q = select(func.max(cot_observation.c.report_date))
    if symbol:
        q = q.where(cot_observation.c.symbol == symbol)
    if report_type:
        q = q.where(cot_observation.c.report_type == report_type)
    with engine.connect() as conn:
        return conn.execute(q).scalar()


def _table_exists(engine: Engine) -> bool:
    from sqlalchemy import inspect
    return "cot_observation" in inspect(engine).get_table_names()


def fetch_series(symbol: str, report_type: str):
    """All observations for a symbol+report, ordered by date. Returns list of
    dict rows (read model — the transform layer turns these into series)."""
    engine = get_engine()
    if not _table_exists(engine):
        return []
    q = (select(cot_observation)
         .where((cot_observation.c.symbol == symbol) &
                (cot_observation.c.report_type == report_type))
         .order_by(cot_observation.c.report_date.asc()))
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(q)]


def stored_symbols() -> list[str]:
    engine = get_engine()
    if not _table_exists(engine):
        return []
    q = select(cot_observation.c.symbol).distinct()
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(q)]
