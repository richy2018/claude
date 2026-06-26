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
import zipfile
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


# ── raw report loading ───────────────────────────────────────────────────────
@lru_cache(maxsize=8)
def load_raw_report(report_key: str) -> pd.DataFrame:
    """Load the combined raw frame for an internal report key
    ('legacy_fut'|'tff_fut'|'disaggregated_fut'). Tries pycot first, then the
    direct-CFTC fallback. Raises (after alerting) if both fail."""
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
    # Fallback: direct CFTC download
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


def list_available_contracts(report_key: str) -> list[str]:
    """Distinct verbatim contract names available in a report (the brief's
    `list_available_contracts()`)."""
    df = load_raw_report(report_key)
    col = _market_name_column(df)
    if col is None:
        raise ValueError(f"no market-name column in {report_key}")
    return sorted(df[col].dropna().astype(str).str.strip().unique().tolist())


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


# ── per-contract fetch -> normalised rows ────────────────────────────────────
def fetch_contract_rows(symbol: str, report_key: str, since=None) -> list[dict]:
    """Fetch + normalise one contract's rows for a report. `since` (date) keeps
    only rows on/after that report_date for incremental upserts. Returns
    normalised cot_observation dicts; alerts + returns [] on failure."""
    from .transform import normalize_report_frame
    try:
        df = load_raw_report(report_key)
        name = resolve_contract_name(symbol, report_key)
        if name is None:
            alerts.emit_alert("fetch", f"{symbol}/{report_key}: no contract name resolved",
                              level="warning", symbol=symbol, report=report_key)
            return []
        col = _market_name_column(df)
        sub = df[df[col].astype(str).str.strip() == name]
        rows = normalize_report_frame(sub, report_key, symbol, name)
        if since is not None:
            rows = [r for r in rows if r["report_date"] >= since]
        return rows
    except Exception as e:
        alerts.emit_alert("fetch", f"{symbol}/{report_key} fetch failed: {e}",
                          level="error", symbol=symbol, report=report_key)
        return []


def fetch_symbol_rows(symbol: str, since=None) -> list[dict]:
    """All rows for a symbol: its asset-appropriate report AND legacy (§2 — we
    store both for every contract)."""
    cfg = CONTRACTS[symbol]
    reports = [cfg["report"]]
    if "legacy_fut" not in reports:
        reports.append("legacy_fut")
    rows = []
    for rk in reports:
        rows.extend(fetch_contract_rows(symbol, rk, since=since))
    return rows
