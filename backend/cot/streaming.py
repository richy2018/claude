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
from .config import (
    CONTRACTS, COHORT_COLUMN_TOKENS, LONG_TOKENS, SHORT_TOKENS,
    REPORT_IDENTITY_TOKENS, DIRECT_CFTC_URLS, BACKFILL_START_YEAR,
)

_TIMEOUT = 60


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
