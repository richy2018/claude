"""Pandas-free streaming backfill.

Reads each yearly CFTC zip as a CSV stream (stdlib `csv`), keeps only the rows
for our ~24 contracts, and yields canonical cot_observation dicts — never
building a DataFrame. Its import chain (stdlib + requests + columns/config/db/
alerts, none of which import pandas) keeps the process footprint to ~35 MB, so
the full ~2010→present backfill runs ALONGSIDE the live 512 MB dashboard without
a cold start, a RAM upgrade, or Postgres.

Cohort/column/name resolution is shared with the pandas path via columns.py, so
the streaming output ties out to the same validated numbers (see
tests/test_cot_streaming.py: NQ 2026-06-16 legacy nets -8,908 / +4,087 / +4,821).
"""

import csv
import io
import gc
import zipfile
import datetime as _dt

import requests

from . import alerts
from . import columns
from . import db
from .config import (
    CONTRACTS, COHORT_COLUMN_TOKENS, LONG_TOKENS, SHORT_TOKENS,
    REPORT_IDENTITY_TOKENS, DIRECT_CFTC_URLS, BACKFILL_START_YEAR,
)

_TIMEOUT = 60
_UPSERT_BATCH = 2000
_OVERLAP_WEEKS = 6  # re-pull this many weeks so CFTC's revisions to recent weeks upsert

LEGACY_COHORTS = ("non_comm", "commercial", "non_rept")
# Verified anchor (ties to CFTC COT<GO>): NQ legacy 2026-06-16.
_TIE_OUT = {"symbol": "NQ", "report": "legacy_fut", "date": "2026-06-16",
            "nets": {"non_comm": -8908, "commercial": 4087, "non_rept": 4821}}


def current_year() -> int:
    return _dt.date.today().year


def reports_for_symbols(symbols) -> dict:
    """report_key -> sorted symbols needing it (asset report + legacy, §2)."""
    out = {}
    for s in symbols:
        cfg = CONTRACTS[s]
        for rk in {cfg["report"], "legacy_fut"}:
            out.setdefault(rk, set()).add(s)
    return {rk: sorted(syms) for rk, syms in out.items()}


# ── CSV streaming ────────────────────────────────────────────────────────────
def _download_year(report_key: str, year: int):
    url = DIRECT_CFTC_URLS[report_key].format(year=year)
    resp = requests.get(url, timeout=_TIMEOUT)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.content


def _open_year_csv(report_key: str, year: int):
    """Return (header_list, csv_reader) streaming the year's CSV, or None."""
    content = _download_year(report_key, year)
    if content is None:
        return None
    z = zipfile.ZipFile(io.BytesIO(content))
    fn = z.namelist()[0]
    fh = io.TextIOWrapper(z.open(fn), encoding="utf-8", errors="replace")
    reader = csv.reader(fh)
    try:
        header = next(reader)
    except StopIteration:
        return None
    return header, reader


def _assert_identity(header, report_key):
    norm = " ".join(columns.norm(c) for c in header)
    missing = [t for t in REPORT_IDENTITY_TOKENS.get(report_key, []) if t not in norm]
    if missing:
        raise ValueError(f"{report_key}: identity tokens missing {missing} (wrong report?)")


def list_available_contracts(report_key: str, year: int | None = None) -> list:
    """Distinct verbatim contract names from a recent year (name column only)."""
    for yr in ([year] if year else [current_year(), current_year() - 1]):
        opened = _open_year_csv(report_key, yr)
        if not opened:
            continue
        header, reader = opened
        col = columns.market_name_column(header)
        if col is None or col not in header:
            continue
        ni = header.index(col)
        names = set()
        for row in reader:
            if len(row) > ni and row[ni].strip():
                names.add(row[ni].strip())
        del reader
        gc.collect()
        return sorted(names)
    return []


def resolve_names_for(report_key: str, symbols, available=None) -> dict:
    if available is None:
        available = list_available_contracts(report_key)
    return {s: columns.resolve_contract_name(s, available) for s in symbols}


def _resolve_indices(header, report_key):
    """Map the header to column indices: name, date, OI, and per-cohort
    (long, short). Returns (idx_dict, {cohort: (long_i, short_i)})."""
    def index_of(colname):
        return header.index(colname) if (colname and colname in header) else None

    idx = {
        "name": index_of(columns.market_name_column(header)),
        "date": index_of(columns.resolve_date_column_name(header)),
        "oi": index_of(columns.find_oi_column(header)),
    }
    cohorts = {}
    for cohort, groups in COHORT_COLUMN_TOKENS[report_key].items():
        lc = columns.find_position_column(header, groups, LONG_TOKENS)
        sc = columns.find_position_column(header, groups, SHORT_TOKENS)
        li, si = index_of(lc), index_of(sc)
        if li is not None and si is not None and li != si:
            cohorts[cohort] = (li, si)
    return idx, cohorts


def _parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return _dt.date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%Y%m%d", "%y%m%d"):
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def iter_parsed_rows(header, reader, report_key, name_to_symbol, since=None):
    """Yield canonical cot_observation dicts from a CSV header+reader, keeping
    only rows whose market name is in `name_to_symbol`. Pure stdlib."""
    idx, cohorts = _resolve_indices(header, report_key)
    if idx["name"] is None or idx["date"] is None or not cohorts:
        raise ValueError(f"{report_key}: could not resolve name/date/cohort columns")
    ni, di, oii = idx["name"], idx["date"], idx["oi"]
    need = max([ni, di] + [max(p) for p in cohorts.values()])
    for row in reader:
        if len(row) <= need:
            continue
        sym = name_to_symbol.get(row[ni].strip())
        if sym is None:
            continue
        d = _parse_date(row[di])
        if d is None or (since is not None and d < since):
            continue
        oi = columns.to_int(row[oii]) if oii is not None else None
        for cohort, (li, si) in cohorts.items():
            longs = columns.to_int(row[li])
            shorts = columns.to_int(row[si])
            if longs is None and shorts is None:
                continue
            yield {
                "report_date": d,
                "symbol": sym,
                "contract_name": row[ni].strip(),   # verbatim source string
                "report_type": report_key,
                "cohort": cohort,
                "longs": longs,
                "shorts": shorts,
                "net": (longs or 0) - (shorts or 0),
                "open_interest": oi,
            }


def stream_report_year(report_key, year, name_to_symbol, since=None):
    """Yield canonical rows for target contracts from one report-year."""
    opened = _open_year_csv(report_key, year)
    if not opened:
        return
    header, reader = opened
    _assert_identity(header, report_key)
    yield from iter_parsed_rows(header, reader, report_key, name_to_symbol, since)
    del reader
    gc.collect()


# ── incremental (weekly) refresh ─────────────────────────────────────────────
def run_incremental_update(symbols=None, overlap_weeks=_OVERLAP_WEEKS) -> dict:
    """Pandas-free incremental refresh: for each report, pulls only the years
    covering the window since that report's oldest 'latest stored' date (minus
    overlap so CFTC's revisions to recent weeks upsert), not full history.

    Same memory profile as the streaming backfill (proven to run safely
    alongside the live web server), so this is safe to call in-process — e.g.
    from a FastAPI BackgroundTask triggered by a "Refresh" button — with no
    cold start, RAM upgrade, or separate worker needed.
    """
    syms = symbols or list(CONTRACTS)
    cur = current_year()
    report_syms = reports_for_symbols(syms)
    total = 0
    failures = 0
    by_report = {}

    for rk, rsyms in report_syms.items():
        try:
            available = list_available_contracts(rk)
        except Exception as e:
            failures += 1
            alerts.emit_alert("refresh", f"name list failed for {rk}: {e}", level="error", report=rk)
            continue
        name_map = {s: columns.resolve_contract_name(s, available) for s in rsyms}
        name_to_symbol = {n: s for s, n in name_map.items() if n}
        unresolved = [s for s in rsyms if not name_map.get(s)]
        if unresolved:
            alerts.emit_alert("refresh", f"{rk}: unresolved {unresolved}", level="warning", report=rk)

        latests = [d for d in (db.latest_report_date(s, rk) for s in rsyms) if d]
        since = (min(latests) - _dt.timedelta(weeks=overlap_weeks)) if latests else None
        start_year = since.year if since else BACKFILL_START_YEAR

        rk_rows = 0
        for yr in range(start_year, cur + 1):
            batch = []
            try:
                for row in stream_report_year(rk, yr, name_to_symbol, since=since):
                    batch.append(row)
                    if len(batch) >= _UPSERT_BATCH:
                        db.upsert_observations(batch)
                        rk_rows += len(batch)
                        batch = []
                if batch:
                    db.upsert_observations(batch)
                    rk_rows += len(batch)
            except Exception as e:
                alerts.emit_alert("refresh", f"{rk} {yr}: {e}", level="warning", report=rk, year=yr)
            gc.collect()
        by_report[rk] = rk_rows
        total += rk_rows

    validate_stored("NQ")
    return {"total": total, "by_report": by_report, "failures": failures, "n_reports": len(report_syms)}


def validate_stored(symbol_check: str = "NQ") -> dict:
    """Pure-Python sum-to-zero + tie-out check (§5) on stored legacy rows for one
    reference symbol. Records outcomes via alerts.record_validation, which
    surfaces on /api/cot/health and the dashboard's health strip."""
    rows = db.fetch_series(symbol_check, "legacy_fut")
    by_date = {}
    for r in rows:
        by_date.setdefault(str(r["report_date"]), {})[r["cohort"]] = r["net"]
    bad = 0
    checked = 0
    for d, c in by_date.items():
        if set(LEGACY_COHORTS) <= set(c):
            checked += 1
            if sum(c[k] for k in LEGACY_COHORTS) != 0:
                bad += 1
    ok = bad == 0
    alerts.record_validation("sum_to_zero", ok,
                             f"{symbol_check} legacy: {checked - bad}/{checked} weeks balance")

    anchor = by_date.get(_TIE_OUT["date"])
    if _TIE_OUT["symbol"] == symbol_check and anchor:
        tie_ok = all(anchor.get(k) == v for k, v in _TIE_OUT["nets"].items())
        alerts.record_validation("tie_out", tie_ok, f"{symbol_check} {_TIE_OUT['date']}: {anchor}")

    return {"sum_to_zero_ok": ok, "checked_weeks": checked, "bad_weeks": bad}
