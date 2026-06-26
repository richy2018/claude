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

from .config import COHORT_COLUMN_TOKENS, LONG_TOKENS, SHORT_TOKENS, COHORTS_BY_REPORT, DEFAULT_LOOKBACK
from .columns import (
    find_position_column as _find_position_column,
    find_oi_column as _find_oi_column,
    resolve_date_column_name,
    needed_columns,
    to_int as _to_int,
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
# Pure column-resolution helpers live in columns.py (pandas-free, shared with
# the streaming backfill). This module keeps the pandas-based frame normalise.
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
    return resolve_date_column_name(df.columns)


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
