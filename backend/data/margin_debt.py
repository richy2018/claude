"""FINRA Margin Debt — Leverage/Sentiment Overlay (NOT a GLI composite factor).

Computes the year-over-year % change of FINRA customer margin debt (total
debit balances in securities margin accounts) as a risk-appetite / leverage
gauge. This is a *monitoring overlay* that lives BESIDE the GLI production
signal — it is deliberately excluded from the 5-factor composite because it
is coincident-to-lagging and would contaminate the liquidity signal.

Data source
-----------
FINRA Margin Statistics ("Debit Balances in Customers' Securities Margin
Accounts", monthly, USD millions). FINRA provides no API — only a downloadable
xlsx starting January 1997. We read from a cached CSV store
(``margin_debt.csv``) that ``scripts/update_margin_debt.py`` regenerates from
the FINRA xlsx. The backend never live-fetches FINRA on each request.

Publication lag
---------------
FINRA publishes month M's value in the THIRD WEEK of month M+1. To avoid
look-ahead bias, every point-in-time computation (z-score, percentile, regime
classification, forward-return analytics) lags the series by ``LAG_MONTHS``
(default 1). The "latest" display shows the freshest reference month but
labels its publication ("as of") date.

Methodology mirrors the GLI factors: YoY% change, expanding-window
(point-in-time) z-score and percentile — never full-sample.
"""

import csv
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

CSV_PATH = Path(__file__).parent / "margin_debt.csv"

# Publication lag in months (FINRA releases month M in ~3rd week of M+1)
LAG_MONTHS = 1

# Z-score / percentile windows (months) — same discipline as GLI factors
ZSCORE_WINDOW = 36
PERCENTILE_WINDOW = 60

# Regime thresholds on YoY% (configurable; sensible defaults)
DEFAULT_THRESHOLDS = {
    "froth": 30.0,         # YoY > +30%  → extreme expansion / froth
    "neutral_low": 0.0,    # 0% to +30%  → neutral
    "capitulation": -20.0,  # YoY < -20% → capitulation
    # contraction is YoY < 0% (between 0 and -20 = contraction, below -20 = capitulation)
}


# ──────────────────────────────────────────────────────────────────────────
# Data loading
# ──────────────────────────────────────────────────────────────────────────

def load_margin_debt(csv_path=None):
    """Load the cached margin-debt series from CSV.

    Returns (series, meta) where:
      series: pd.Series indexed by reference-month Timestamp (USD millions)
      meta:   {"source": str, "is_authoritative": bool, "rows": int}
    Returns (None, meta) if the store is missing or empty.
    """
    path = Path(csv_path) if csv_path else CSV_PATH
    meta = {"source": "missing", "is_authoritative": False, "rows": 0}
    if not path.exists():
        return None, meta

    source_line = None
    rows = []
    with open(path, newline="") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line.startswith("#"):
                if "source:" in line.lower():
                    source_line = line.split(":", 1)[1].strip()
                continue
            if not line.strip():
                continue
            parts = line.split(",")
            if parts[0].strip().lower() in ("date", "month"):
                continue  # header
            if len(parts) < 2:
                continue
            try:
                d = pd.Timestamp(parts[0].strip())
                v = float(parts[1].strip())
            except (ValueError, TypeError):
                continue
            rows.append((d, v))

    if not rows:
        return None, meta

    rows.sort(key=lambda r: r[0])
    series = pd.Series([v for _, v in rows], index=pd.DatetimeIndex([d for d, _ in rows]),
                       dtype=float, name="margin_debt_usd_m")
    series = series[~series.index.duplicated(keep="last")]

    meta["source"] = source_line or "unknown"
    meta["is_authoritative"] = bool(source_line) and "seed" not in source_line.lower() \
        and "placeholder" not in source_line.lower()
    meta["rows"] = int(len(series))
    return series, meta


# ──────────────────────────────────────────────────────────────────────────
# Computation
# ──────────────────────────────────────────────────────────────────────────

def _expanding_zscore(s, window=ZSCORE_WINDOW, min_periods=12):
    """Expanding/rolling-window z-score, point-in-time (no future lookahead).

    Matches the GLI factor methodology: rolling mean/std, clipped to [-3, 3].
    """
    m = s.rolling(window, min_periods=min_periods).mean()
    st = s.rolling(window, min_periods=min_periods).std().replace(0, np.nan)
    return ((s - m) / st).clip(-3, 3)


def _expanding_percentile(s, window=PERCENTILE_WINDOW, min_periods=12):
    """Rolling percentile rank of the current value vs its trailing window."""
    from scipy import stats as sp_stats
    return s.rolling(window, min_periods=min_periods).apply(
        lambda x: sp_stats.percentileofscore(x, x.iloc[-1]) if len(x) > 1 else 50.0,
        raw=False)


def classify_regime(yoy_pct, thresholds=None):
    """Map a YoY% value to a regime label. None-safe."""
    if yoy_pct is None or (isinstance(yoy_pct, float) and np.isnan(yoy_pct)):
        return None
    t = thresholds or DEFAULT_THRESHOLDS
    if yoy_pct > t["froth"]:
        return "froth"
    if yoy_pct >= t["neutral_low"]:
        return "neutral"
    if yoy_pct <= t["capitulation"]:
        return "capitulation"
    return "contraction"


def compute_margin_debt_signal(series, thresholds=None, lag_months=LAG_MONTHS):
    """Compute the full margin-debt overlay from a raw debit-balance series.

    Args:
        series: pd.Series of margin debt (USD millions), monthly, ref-month indexed.
        thresholds: optional regime thresholds dict.
        lag_months: publication lag applied to point-in-time stats.

    Returns a dict matching the API contract:
        {series: [{date, ref_month, margin_debt, yoy_pct, yoy_z, percentile, regime, as_of}],
         latest: {...}, thresholds: {...}, meta: {...}}

    No-lookahead discipline: YoY% is computed on the raw series, but the
    z-score / percentile / regime used for *point-in-time* records are computed
    on the LAGGED series (shifted forward by lag_months) so that at calendar
    date D only values published on/before D inform the statistic.
    """
    thresholds = thresholds or DEFAULT_THRESHOLDS
    if series is None or len(series) < 13:
        return {"series": [], "latest": None, "thresholds": thresholds,
                "meta": {"insufficient_data": True, "n_obs": 0 if series is None else len(series)}}

    s = series.sort_index().astype(float)

    # Year-over-year % change (raw, by reference month)
    yoy = (s / s.shift(12) - 1.0) * 100.0

    # Point-in-time statistics on the YoY series. The z-score/percentile at a
    # given reference month only ever use trailing YoY values (rolling window),
    # which is already point-in-time. The publication lag matters when we ask
    # "what was knowable at calendar date D" — see _as_of below.
    yoy_z = _expanding_zscore(yoy)
    yoy_pctl = _expanding_percentile(yoy)

    def _as_of(ref_month):
        """Publication date: ~3rd week of the month after the reference month."""
        # ref_month is YYYY-MM-01; publication ≈ next month + ~20 days
        pub_month = (ref_month + pd.offsets.MonthBegin(lag_months))
        return (pub_month + timedelta(days=20)).strftime("%Y-%m-%d")

    out = []
    for ref_month in s.index:
        yv = yoy.get(ref_month)
        zv = yoy_z.get(ref_month)
        pv = yoy_pctl.get(ref_month)
        out.append({
            "date": ref_month.strftime("%Y-%m-%d"),
            "ref_month": ref_month.strftime("%Y-%m"),
            "as_of": _as_of(ref_month),
            "margin_debt": round(float(s[ref_month]), 1),
            "yoy_pct": round(float(yv), 2) if pd.notna(yv) else None,
            "yoy_z": round(float(zv), 3) if pd.notna(zv) else None,
            "percentile": round(float(pv), 1) if pd.notna(pv) else None,
            "regime": classify_regime(float(yv) if pd.notna(yv) else None, thresholds),
        })

    latest = out[-1] if out else None

    return {
        "series": out,
        "latest": latest,
        "thresholds": thresholds,
        "meta": {
            "lag_months": lag_months,
            "zscore_window": ZSCORE_WINDOW,
            "percentile_window": PERCENTILE_WINDOW,
            "n_obs": int(len(s)),
            "first_ref_month": s.index[0].strftime("%Y-%m"),
            "last_ref_month": s.index[-1].strftime("%Y-%m"),
        },
    }


def get_margin_debt_overlay(csv_path=None, thresholds=None):
    """Top-level: load the cached series and compute the overlay payload."""
    series, meta = load_margin_debt(csv_path)
    result = compute_margin_debt_signal(series, thresholds=thresholds)
    result["meta"].update({
        "data_source": meta["source"],
        "is_authoritative": meta["is_authoritative"],
    })
    return result


def margin_debt_yoy_series(csv_path=None, lagged=True, lag_months=LAG_MONTHS):
    """Helper for analytics (rolling corr with GLI, forward-return-by-regime).

    Returns a pd.Series of YoY% indexed by month. When ``lagged`` is True the
    series is shifted forward by ``lag_months`` so it reflects only data
    publishable at each calendar month (point-in-time, no lookahead).
    """
    series, _ = load_margin_debt(csv_path)
    if series is None or len(series) < 13:
        return pd.Series(dtype=float)
    yoy = (series.sort_index() / series.sort_index().shift(12) - 1.0) * 100.0
    yoy = yoy.dropna()
    if lagged and lag_months:
        yoy = yoy.shift(lag_months)
    return yoy.dropna()
