"""CFTC fetch wrappers — name resolution, incremental pull, historical backfill.

Both packages are pre-alpha and pull live from the CFTC site, so EVERY fetch is
wrapped in try/except and routed to the alert sink (alerts.emit_alert). A
documented direct-CFTC fallback (`fetch_raw_direct`) downloads the same public
ZIP archives if both packages break.

  - pycot (`pycot-reports`)  -> primary weekly/incremental pull (.get_reports
    returns the RAW combined frame with verbatim CFTC columns, which we
    normalise ourselves so all cohorts + sum-to-zero integrity survive).
  - cftc-cot                 -> robust ZIP downloader for the one-time backfill.

`list_available_contracts()` in the brief maps to the distinct values of the raw
`Market_and_Exchange_Names` column — that IS the available-contract list. We
resolve each friendly symbol's candidate substrings against it (case-insensitive,
first match wins), exactly how NQ was resolved in the reference build.
"""

import io
import gc
import zipfile
import datetime as _dt
from functools import lru_cache

import pandas as pd
import requests

from . import alerts
from .config import (
    CONTRACTS, REPORT_TYPES, REPORT_IDENTITY_TOKENS, MARKET_NAME_COLUMNS,
)

# Direct-CFTC fallback archive URLs (public domain). Yearly "current" files plus
# the deep historical bundle. Used only if the pip packages fail.
_DIRECT_BASE = {
    "legacy_fut": "https://www.cftc.gov/files/dea/history/deacot{year}.zip",
    "disaggregated_fut": "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip",
    "tff_fut": "https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip",
}
_REQUEST_TIMEOUT = 60


BACKFILL_START_YEAR = 2010


def current_year() -> int:
    return _dt.date.today().year


# ── raw report loading ───────────────────────────────────────────────────────
# IMPORTANT: pycot's `.get_reports` loads the ENTIRE combined history (the
# 1986-2016 legacy bulk file + every yearly file) into one frame — hundreds of
# MB, enough to OOM a small instance, especially with several reports resident.
# So the hot paths load ONE YEAR at a time (load_report_year) and we only ever
# retain the rows for our ~24 contracts. load_raw_report (full history) remains
# for completeness but is not used by resolve / backfill / weekly.
def load_report_year(report_key: str, year: int):
    """Load a SINGLE year of a report (memory-light). pycot first, then the
    direct-CFTC yearly fallback. Returns a DataFrame or None (missing year)."""
    pycot_type = REPORT_TYPES[report_key]
    try:
        from pycot.reports import CommitmentsOfTraders
        df = CommitmentsOfTraders(pycot_type).get_reports_by_year(year)
        if df is not None and len(df) > 0:
            return df
    except Exception as e:
        alerts.emit_alert("fetch", f"pycot year {year} {report_key}: {e}",
                          level="warning", report=report_key, year=year)
    try:
        return fetch_raw_direct(report_key, years=range(year, year + 1))
    except Exception as e:
        alerts.emit_alert("fetch", f"direct year {year} {report_key}: {e}",
                          level="warning", report=report_key, year=year)
        return None


@lru_cache(maxsize=4)
def load_raw_report(report_key: str) -> pd.DataFrame:
    """Full combined history for a report (memory-heavy — avoid on small hosts;
    prefer load_report_year). Tries pycot, then the direct-CFTC fallback."""
    pycot_type = REPORT_TYPES[report_key]
    try:
        from pycot.reports import CommitmentsOfTraders
        df = CommitmentsOfTraders(pycot_type).get_reports
        if df is None or len(df) == 0:
            raise ValueError("pycot returned empty frame")
        _assert_report_identity(df, report_key)
        return df
    except Exception as e:
        alerts.emit_alert("fetch", f"pycot load failed for {report_key}: {e}",
                          level="warning", report=report_key)
    try:
        df = fetch_raw_direct(report_key)
        _assert_report_identity(df, report_key)
        return df
    except Exception as e:
        alerts.emit_alert("fetch", f"direct CFTC fallback failed for {report_key}: {e}",
                          level="error", report=report_key)
        raise


def _assert_report_identity(df: pd.DataFrame, report_key: str):
    """Sanity check (§2): TFF must show Leveraged/Asset Manager, disagg must
    show Producer/Swap Dealer. If the identity tokens are absent we loaded the
    wrong report — alert loudly rather than silently mis-mapping cohorts."""
    norm = " ".join(str(c).lower().replace("_", " ") for c in df.columns)
    tokens = REPORT_IDENTITY_TOKENS.get(report_key, [])
    missing = [t for t in tokens if t not in norm]
    if missing:
        raise ValueError(
            f"report identity check failed for {report_key}: missing {missing} "
            f"in columns (wrong report loaded?)")


def fetch_raw_direct(report_key: str, years: range | None = None) -> pd.DataFrame:
    """Documented direct-CFTC fallback: download + unzip the public archives
    with plain requests, no third-party package. Concatenates yearly files."""
    import datetime as _dt
    if years is None:
        years = range(2010, _dt.date.today().year + 1)
    frames = []
    tmpl = _DIRECT_BASE[report_key]
    for y in years:
        url = tmpl.format(year=y)
        try:
            resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                name = z.namelist()[0]
                frames.append(pd.read_csv(z.open(name), low_memory=False))
        except Exception as e:
            alerts.emit_alert("fetch", f"direct {report_key} {y}: {e}",
                              level="warning", report=report_key, year=y)
    if not frames:
        raise ValueError(f"direct fallback got no data for {report_key}")
    return pd.concat(frames, ignore_index=True)


# ── name resolution ──────────────────────────────────────────────────────────
def _market_name_column(df: pd.DataFrame):
    for c in MARKET_NAME_COLUMNS:
        if c in df.columns:
            return c
    for c in df.columns:
        if "market" in str(c).lower() and "name" in str(c).lower():
            return c
    return None


def _names_from_year_lightweight(report_key: str, year: int):
    """Read ONLY the market-name column from one year's zip — near-zero memory
    (no full DataFrame). Used for name resolution so it runs even inside the
    shared web-service container. Returns a sorted name list or None."""
    url = _DIRECT_BASE[report_key].format(year=year)
    resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        fn = z.namelist()[0]
        with z.open(fn) as fh:
            header = pd.read_csv(fh, nrows=0)
        col = _market_name_column(header)
        if col is None:
            return None
        with z.open(fn) as fh:
            names = pd.read_csv(fh, usecols=[col])[col]
    out = sorted(names.dropna().astype(str).str.strip().unique().tolist())
    del names
    gc.collect()
    return out


def list_available_contracts(report_key: str) -> list[str]:
    """Distinct verbatim contract names available in a report (the brief's
    `list_available_contracts()`). Loads only the most recent year(s) — names are
    stable — and reads just the name column to keep memory near zero. Falls back
    to a pycot single-year load if the lightweight direct read fails."""
    last_err = None
    for yr in (current_year(), current_year() - 1):
        # 1) lightweight: direct zip, name column only
        try:
            names = _names_from_year_lightweight(report_key, yr)
            if names:
                return names
        except Exception as e:
            last_err = e
        # 2) fallback: pycot single-year frame
        df = load_report_year(report_key, yr)
        if df is not None and len(df) > 0:
            col = _market_name_column(df)
            if col is not None:
                names = sorted(df[col].dropna().astype(str).str.strip().unique().tolist())
                del df
                gc.collect()
                return names
    raise ValueError(f"no usable {report_key} data in recent years ({last_err})")


def resolve_contract_name(symbol: str, report_key: str, available: list[str] | None = None):
    """Resolve a friendly symbol's candidate substrings against the available
    contract names for a report. Returns the verbatim CFTC name or None.
    First candidate substring with a match wins (case-insensitive)."""
    cfg = CONTRACTS[symbol]
    if available is None:
        available = list_available_contracts(report_key)
    up = [(name, name.upper()) for name in available]
    for cand in cfg["names"]:
        cu = cand.upper()
        for name, nu in up:
            if cu in nu:
                return name
    return None


def resolve_all_names() -> dict:
    """Resolve every CONTRACTS symbol against BOTH its asset-appropriate report
    and legacy. Returns {symbol: {report_key: name|None, ...}}. This is the
    pre-backfill checkpoint output — review before loading 16y of history.

    Never raises: a report that can't load is recorded as an error string so the
    checkpoint table still renders for the reachable reports.
    """
    # cache the available lists per report we actually need
    needed = {"legacy_fut"}
    for cfg in CONTRACTS.values():
        needed.add(cfg["report"])
    available = {}
    for rk in needed:
        try:
            available[rk] = list_available_contracts(rk)
        except Exception as e:
            available[rk] = e

    out = {}
    for symbol, cfg in CONTRACTS.items():
        entry = {"class": cfg["class"], "primary_report": cfg["report"]}
        for rk in (cfg["report"], "legacy_fut"):
            avail = available.get(rk)
            if isinstance(avail, Exception):
                entry[rk] = f"<report load failed: {avail}>"
            else:
                entry[rk] = resolve_contract_name(symbol, rk, avail)
        out[symbol] = entry
    return out


# ── per-report, per-year fetch -> normalised rows (memory-safe) ──────────────
def reports_for_symbols(symbols) -> dict:
    """Map report_key -> sorted symbols that need it. Every symbol needs its
    asset-appropriate report AND legacy (§2)."""
    out = {}
    for s in symbols:
        cfg = CONTRACTS[s]
        for rk in {cfg["report"], "legacy_fut"}:
            out.setdefault(rk, set()).add(s)
    return {rk: sorted(syms) for rk, syms in out.items()}


def resolve_names_for(report_key: str, symbols) -> dict:
    """{symbol: verbatim name|None} for one report (single recent-year load)."""
    avail = list_available_contracts(report_key)
    return {s: resolve_contract_name(s, report_key, avail) for s in symbols}


def iter_report_year_rows(report_key: str, symbols, name_map: dict,
                          start_year: int, end_year: int, since=None):
    """Yield (year, rows) for one report, ONE YEAR AT A TIME — only the rows for
    `symbols` are retained, the full year frame is freed before the next year.
    This caps peak memory at a single year's frame. `since` (date) filters rows.
    """
    from .transform import normalize_report_frame
    for yr in range(start_year, end_year + 1):
        if since is not None and yr < since.year - 1:
            continue  # skip years entirely before the incremental window
        df = load_report_year(report_key, yr)
        if df is None or len(df) == 0:
            continue
        col = _market_name_column(df)
        year_rows = []
        for s in symbols:
            name = name_map.get(s)
            if not name:
                continue
            sub = df[df[col].astype(str).str.strip() == name]
            if len(sub) == 0:
                continue
            try:
                rows = normalize_report_frame(sub, report_key, s, name)
            except Exception as e:
                alerts.emit_alert("fetch", f"{s}/{report_key} {yr} normalise: {e}",
                                  level="warning", symbol=s, report=report_key, year=yr)
                continue
            if since is not None:
                rows = [r for r in rows if r["report_date"] >= since]
            year_rows.extend(rows)
        del df
        gc.collect()
        yield yr, year_rows
