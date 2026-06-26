"""COT transforms — net position, the 156-week COT index, z-score, read view.

The COT-index formula and net definition are the author's validated logic (§4)
and are implemented EXACTLY as written — do not substitute. Validated on NQ:
2026-06-16 legacy nets Non-Comm -8,908 / Comm +4,087 / Non-Rept +4,821 tie to
CFTC COT<GO>; the resulting cot_index column matches cot_nq_processed.csv.

Also handles cohort normalisation: mapping a raw CFTC report frame (messy,
shifting column names) onto the canonical cohort keys via runtime column
resolution, mirroring the contract-name resolution approach.
"""

import pandas as pd

import re

from .config import (
    COHORT_COLUMN_TOKENS, COHORT_COLUMN_EXCLUDE, COHORT_COLUMN_REQUIRE,
    LONG_TOKENS, SHORT_TOKENS, OPEN_INTEREST_TOKENS, COHORTS_BY_REPORT,
    DEFAULT_LOOKBACK,
)


# ── §4 transform — implemented exactly as specified ──────────────────────────
def net_position(longs, shorts):
    return longs - shorts


def cot_index(net: pd.Series, lookback: int = 156) -> pd.Series:
    """156-week (3y) stochastic of net position, 0-100.
    100 = most net-long in window, 0 = most net-short. The primary signal;
    raw net contracts are non-stationary and not comparable across time/assets."""
    mn = net.rolling(lookback, min_periods=lookback // 2).min()
    mx = net.rolling(lookback, min_periods=lookback // 2).max()
    return 100 * (net - mn) / (mx - mn)


def cot_zscore(net: pd.Series, lookback: int = 156) -> pd.Series:
    """Rolling z-score of net position over the same window. Secondary read,
    complements the bounded 0-100 index with a magnitude-of-deviation view."""
    mean = net.rolling(lookback, min_periods=lookback // 2).mean()
    std = net.rolling(lookback, min_periods=lookback // 2).std()
    return (net - mean) / std


# ── cohort normalisation (raw CFTC frame -> canonical rows) ───────────────────
def _norm(s: str) -> str:
    """Lower-case and flatten _ - ( ) / to single spaces so spaced legacy names
    and underscore TFF/disagg codes match the same tokens."""
    t = str(s).lower()
    t = re.sub(r"[_\-()/.,]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _find_position_column(columns, token_groups, side_tokens):
    """Return the All-period long/short position column for a cohort.

    A column qualifies if (after normalisation) it contains every REQUIRE token
    ('positions', 'all'), a side token, no EXCLUDE token, and matches ANY one of
    the cohort's alternative token-groups. 'commercial' is disambiguated from
    'noncommercial'. Shortest surviving name wins (the plain position column).
    """
    cands = []
    for col in columns:
        cl = _norm(col)
        if any(ex in cl for ex in COHORT_COLUMN_EXCLUDE):
            continue
        if not all(req in cl for req in COHORT_COLUMN_REQUIRE):
            continue
        if not any(st in cl for st in side_tokens):
            continue
        if not _group_match(cl, token_groups):
            continue
        cands.append(col)
    if not cands:
        return None
    return sorted(cands, key=lambda c: len(str(c)))[0]


def _group_match(normalized_col: str, token_groups) -> bool:
    """True if every token in any one group is present. Handles the
    'commercial' vs 'noncommercial' overlap explicitly."""
    for group in token_groups:
        if group == ["commercial"] and "noncommercial" in normalized_col.replace(" ", ""):
            continue
        if all(tok in normalized_col for tok in group):
            return True
    return False


def _find_oi_column(columns):
    for col in columns:
        cl = _norm(col)
        if "open interest" in cl and not any(
                ex in cl for ex in ("spread", "pct", "percent", "change", "old", "other")):
            return col
    return None


def normalize_report_frame(df: pd.DataFrame, report_type: str, symbol: str,
                           contract_name: str, date_col=None) -> list[dict]:
    """Turn one contract's raw report frame into canonical cot_observation rows
    (one per date per cohort). Resolves cohort long/short columns at runtime.

    Raises ValueError if no cohort columns resolve (wrong report loaded / format
    change) so the caller can route it to the alert path.
    """
    if df is None or len(df) == 0:
        return []
    df = df.copy()

    # Resolve the date column.
    if date_col is None:
        date_col = _resolve_date_column(df)
    if date_col is None:
        raise ValueError(f"{symbol}/{report_type}: no date column found")
    dates = pd.to_datetime(df[date_col], errors="coerce")

    token_map = COHORT_COLUMN_TOKENS[report_type]
    oi_col = _find_oi_column(df.columns)

    resolved = {}
    for cohort, tokens in token_map.items():
        long_col = _find_position_column(df.columns, tokens, LONG_TOKENS)
        short_col = _find_position_column(df.columns, tokens, SHORT_TOKENS)
        if long_col is not None and short_col is not None and long_col != short_col:
            resolved[cohort] = (long_col, short_col)

    if not resolved:
        raise ValueError(
            f"{symbol}/{report_type}: no cohort columns resolved from "
            f"{list(df.columns)[:12]}... (wrong report or format change)")

    rows = []
    for i in range(len(df)):
        d = dates.iloc[i]
        if pd.isna(d):
            continue
        rd = d.date()
        oi = _to_int(df[oi_col].iloc[i]) if oi_col else None
        for cohort, (lc, sc) in resolved.items():
            longs = _to_int(df[lc].iloc[i])
            shorts = _to_int(df[sc].iloc[i])
            if longs is None and shorts is None:
                continue
            net = (longs or 0) - (shorts or 0)
            rows.append({
                "report_date": rd,
                "symbol": symbol,
                "contract_name": contract_name,
                "report_type": report_type,
                "cohort": cohort,
                "longs": longs,
                "shorts": shorts,
                "net": net,
                "open_interest": oi,
            })
    return rows


def _resolve_date_column(df: pd.DataFrame):
    return _resolve_date_column_name(df.columns)


def _resolve_date_column_name(columns):
    # Prefer the YYYY-MM-DD form over the 6-digit YYMMDD form. Both naming
    # styles appear (underscore disagg/TFF vs spaced legacy).
    candidates = [
        "report_date_as_yyyy_mm_dd",          # disagg / TFF
        "as of date in form yyyy mm dd",      # legacy spaced
        "report date", "date",
    ]
    lower = {_norm(c): c for c in columns}
    for cand in candidates:
        if _norm(cand) in lower:
            return lower[_norm(cand)]
    # any column with 'date' but not the 6-digit yymmdd form
    for c in columns:
        cl = _norm(c)
        if "date" in cl and "yymmdd" not in cl.replace(" ", ""):
            return c
    for c in columns:
        if "date" in _norm(c):
            return c
    return None


def needed_columns(columns, report_key: str) -> list:
    """The minimal set of raw columns required to normalise a report: the
    market-name, the date, open interest, and each cohort's long/short position
    columns. Used to read only ~10 columns per year instead of ~130, keeping
    backfill within a small instance's memory."""
    keep = []

    def add(c):
        if c and c not in keep:
            keep.append(c)

    for c in columns:
        cl = _norm(c)
        if "market" in cl and "name" in cl:
            add(c)
            break
    add(_resolve_date_column_name(columns))
    add(_find_oi_column(columns))
    for _cohort, groups in COHORT_COLUMN_TOKENS[report_key].items():
        add(_find_position_column(columns, groups, LONG_TOKENS))
        add(_find_position_column(columns, groups, SHORT_TOKENS))
    return keep


def _to_int(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(round(float(str(v).replace(",", "").strip())))
    except (TypeError, ValueError):
        return None


# ── read view: stored rows -> per-cohort time series with index + zscore ─────
def build_series(rows: list[dict], lookback: int = DEFAULT_LOOKBACK) -> dict:
    """Pivot stored observations (for one symbol+report) into per-cohort series
    with net, open_interest, cot_index (warmup-aware null) and z-score.

    Returns {"cohorts": {cohort: [{date, net, longs, shorts, open_interest,
    cot_index, zscore}]}, "dates": [...], "lookback": n}. COT index is null
    until `lookback` history exists (warmup) — never a half-formed signal.
    """
    if not rows:
        return {"cohorts": {}, "dates": [], "lookback": lookback}
    df = pd.DataFrame(rows)
    df["report_date"] = pd.to_datetime(df["report_date"])
    report_type = df["report_type"].iloc[0]
    order = COHORTS_BY_REPORT.get(report_type, sorted(df["cohort"].unique()))

    out_cohorts = {}
    all_dates = sorted(df["report_date"].unique())
    for cohort in order:
        sub = df[df["cohort"] == cohort].sort_values("report_date")
        if sub.empty:
            continue
        sub = sub.drop_duplicates("report_date", keep="last").set_index("report_date")
        net = sub["net"].astype(float)
        idx = cot_index(net, lookback)
        z = cot_zscore(net, lookback)
        recs = []
        for d in sub.index:
            recs.append({
                "date": d.strftime("%Y-%m-%d"),
                "net": _none_if_nan(sub.at[d, "net"]),
                "longs": _none_if_nan(sub.at[d, "longs"]),
                "shorts": _none_if_nan(sub.at[d, "shorts"]),
                "open_interest": _none_if_nan(sub.at[d, "open_interest"]),
                "cot_index": _none_if_nan(idx.at[d]),
                "zscore": _none_if_nan(z.at[d]),
            })
        out_cohorts[cohort] = recs

    return {
        "cohorts": out_cohorts,
        "dates": [pd.Timestamp(d).strftime("%Y-%m-%d") for d in all_dates],
        "report_type": report_type,
        "lookback": lookback,
    }


def latest_cot_index(rows: list[dict], cohort: str, lookback: int = DEFAULT_LOOKBACK):
    """Latest cot_index value (and 1w/4w change) for one cohort — heatmap cell.
    Returns dict {value, net, date, chg_1w, chg_4w} or None."""
    sub = [r for r in rows if r["cohort"] == cohort]
    if not sub:
        return None
    df = pd.DataFrame(sub)
    df["report_date"] = pd.to_datetime(df["report_date"])
    df = df.sort_values("report_date").drop_duplicates("report_date", keep="last")
    df = df.set_index("report_date")
    idx = cot_index(df["net"].astype(float), lookback)
    if idx.dropna().empty:
        cur = None
        date = df.index[-1]
    else:
        cur = idx.iloc[-1]
        date = idx.index[-1]
    chg_1w = _delta(idx, 1)
    chg_4w = _delta(idx, 4)
    return {
        "value": _none_if_nan(cur),
        "net": _none_if_nan(df["net"].iloc[-1]),
        "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
        "chg_1w": chg_1w,
        "chg_4w": chg_4w,
        # short sparkline of recent index (last 12 wks) for the heatmap cell
        "spark": [_none_if_nan(v) for v in idx.iloc[-12:].tolist()],
    }


def _delta(series: pd.Series, n: int):
    s = series.dropna()
    if len(s) <= n:
        return None
    return _none_if_nan(s.iloc[-1] - s.iloc[-1 - n])


def _none_if_nan(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        return v
    if isinstance(v, float):
        return round(v, 4)
    try:
        return int(v)
    except (TypeError, ValueError):
        return float(v)
