"""Pandas-free column resolution + contract-name scoring.

These are the pure-Python helpers that map CFTC's messy, shifting column names
onto canonical cohorts and resolve friendly symbols to verbatim contract names.
They are kept free of pandas so the streaming backfill (streaming.py) can import
them without paying pandas' ~40 MB footprint — letting it run alongside the live
dashboard in 512 MB. transform.py and fetcher.py import the same functions, so
there is a single source of truth (guarded by the test suite).
"""

import re

from .config import (
    COHORT_COLUMN_TOKENS, COHORT_COLUMN_EXCLUDE, COHORT_COLUMN_REQUIRE,
    LONG_TOKENS, SHORT_TOKENS, MARKET_NAME_COLUMNS, CONTRACTS,
    DEMOTE_VARIANT_TOKENS,
)


def norm(s) -> str:
    """Lower-case and flatten _ - ( ) / . , to single spaces so spaced legacy
    names and underscore TFF/disagg codes match the same tokens."""
    t = str(s).lower()
    t = re.sub(r"[_\-()/.,]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def group_match(normalized_col: str, token_groups) -> bool:
    """True if every token in any one group is present. Handles the
    'commercial' vs 'noncommercial' overlap explicitly."""
    for group in token_groups:
        if group == ["commercial"] and "noncommercial" in normalized_col.replace(" ", ""):
            continue
        if all(tok in normalized_col for tok in group):
            return True
    return False


def find_position_column(columns, token_groups, side_tokens):
    """Return the All-period long/short position column for a cohort: contains
    every REQUIRE token ('positions','all'), a side token, no EXCLUDE token, and
    matches any one cohort token-group. Shortest surviving name wins."""
    cands = []
    for col in columns:
        cl = norm(col)
        if any(ex in cl for ex in COHORT_COLUMN_EXCLUDE):
            continue
        if not all(req in cl for req in COHORT_COLUMN_REQUIRE):
            continue
        if not any(st in cl for st in side_tokens):
            continue
        if not group_match(cl, token_groups):
            continue
        cands.append(col)
    if not cands:
        return None
    return sorted(cands, key=lambda c: len(str(c)))[0]


def find_oi_column(columns):
    for col in columns:
        cl = norm(col)
        if "open interest" in cl and not any(
                ex in cl for ex in ("spread", "pct", "percent", "change", "old", "other")):
            return col
    return None


def resolve_date_column_name(columns):
    """Prefer the YYYY-MM-DD form over the 6-digit YYMMDD form (both styles
    appear: underscore disagg/TFF vs spaced legacy)."""
    candidates = [
        "report_date_as_yyyy_mm_dd",
        "as of date in form yyyy mm dd",
        "report date", "date",
    ]
    lower = {norm(c): c for c in columns}
    for cand in candidates:
        if norm(cand) in lower:
            return lower[norm(cand)]
    for c in columns:
        cl = norm(c)
        if "date" in cl and "yymmdd" not in cl.replace(" ", ""):
            return c
    for c in columns:
        if "date" in norm(c):
            return c
    return None


def market_name_column(columns):
    for c in MARKET_NAME_COLUMNS:
        if c in columns:
            return c
    for c in columns:
        cl = str(c).lower()
        if "market" in cl and "name" in cl:
            return c
    return None


def needed_columns(columns, report_key: str) -> list:
    """Minimal raw columns required to normalise a report: market name, date,
    open interest, each cohort's long/short. ~10 instead of ~130."""
    keep = []

    def add(c):
        if c and c not in keep:
            keep.append(c)

    add(market_name_column(columns))
    add(resolve_date_column_name(columns))
    add(find_oi_column(columns))
    for _cohort, groups in COHORT_COLUMN_TOKENS[report_key].items():
        add(find_position_column(columns, groups, LONG_TOKENS))
        add(find_position_column(columns, groups, SHORT_TOKENS))
    return keep


def to_int(v):
    """Parse a CFTC integer cell ('123,456', '.', '' -> None) without pandas."""
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s == ".":
        return None
    try:
        return int(round(float(s.replace(",", ""))))
    except (TypeError, ValueError):
        return None


def resolve_contract_name(symbol: str, available):
    """Score `available` verbatim names for a symbol and return the best, or
    None. Candidate order is the main preference; a name is demoted if it carries
    a MICRO/ULTRA/MINI token the matched candidate didn't ask for (so the
    standard contract wins), the preferred exchange is boosted, and the
    shorter/cleaner name breaks ties. Pure — `available` is supplied by caller."""
    cfg = CONTRACTS[symbol]
    cands = [c.upper() for c in cfg["names"]]
    prefer_ex = (cfg.get("exchange") or "").upper()

    scored = []
    for name in available:
        nu = str(name).upper()
        ci = next((i for i, c in enumerate(cands) if c in nu), None)
        if ci is None:
            continue
        matched = cands[ci]
        s = (len(cands) - ci) * 100.0
        for tok in DEMOTE_VARIANT_TOKENS:
            T = tok.upper()
            if T in nu and T not in matched:
                s -= 500.0
        if prefer_ex and prefer_ex in nu:
            s += 300.0
        s -= len(nu) * 0.1
        scored.append((s, name))
    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[0][1]
