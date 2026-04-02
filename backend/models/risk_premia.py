"""Risk premia calculations using actual Shiller earnings data + daily Yahoo PE."""

import pandas as pd
import numpy as np
from pathlib import Path

from ..data.pe_store import get_daily_pe_history


def load_shiller_earnings() -> pd.DataFrame:
    """Load Shiller S&P 500 price/earnings data."""
    path = Path(__file__).parent.parent / "data" / "shiller_pe.csv"
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path, sep="\t")
    # Parse date: format is YYYY.MM as float (e.g., 1999.01=Jan, 1999.1=Oct)
    def _parse_date(x):
        x = float(x)
        year = int(x)
        month = round((x - year) * 100)
        if month < 1:
            month = 1
        if month > 12:
            month = 12
        return pd.Timestamp(year=year, month=month, day=1)
    df["date"] = df["Date"].apply(_parse_date)
    df = df.set_index("date").sort_index()

    # Forward-fill earnings for months where it's missing
    df["Earnings"] = pd.to_numeric(df["Earnings"], errors="coerce")
    df["Price"] = pd.to_numeric(df["Price"], errors="coerce")
    df["Earnings"] = df["Earnings"].ffill()

    # Compute trailing PE and earnings yield
    df["PE"] = df["Price"] / df["Earnings"]
    df["EY"] = (df["Earnings"] / df["Price"]) * 100  # earnings yield in %

    return df


def _load_daily_pe_as_series() -> pd.Series:
    """Load daily PE store and return an EY (earnings yield) series indexed by date."""
    store = get_daily_pe_history()
    if not store:
        return pd.Series(dtype=float)
    records = []
    for date_str, entry in store.items():
        ey = entry.get("ey")
        if ey is not None:
            try:
                records.append((pd.Timestamp(date_str), float(ey)))
            except Exception:
                continue
    if not records:
        return pd.Series(dtype=float)
    s = pd.Series(dict(records)).sort_index()
    s.index.name = "date"
    return s


def compute_risk_premia(
    real_yield_10y: pd.Series,
    acm_term_premium: pd.Series = None,
    dgs10: pd.Series = None,
    dgs2: pd.Series = None,
    spx_prices: pd.Series = None,
) -> dict:
    """
    Compute ERP and term premium using actual Shiller earnings data.

    ERP = Earnings Yield (from Shiller) − 10Y Real Yield (DFII10)
    """
    # Load actual earnings data
    shiller = load_shiller_earnings()
    if shiller.empty or "EY" not in shiller.columns:
        return {"top_chart": [], "diff_chart": [], "summary": [],
                "error": "Shiller earnings data not available"}

    # Resample Shiller earnings yield to daily by forward-filling monthly data
    ey_monthly = shiller["EY"].dropna()
    ey_daily = ey_monthly.resample("D").ffill()

    # Overlay daily Yahoo PE data for recent dates (replaces stale forward-filled values)
    daily_pe_ey = _load_daily_pe_as_series()
    if len(daily_pe_ey) > 0:
        ey_daily = ey_daily.copy()
        for dt, ey_val in daily_pe_ey.items():
            ey_daily[dt] = ey_val
        # Forward-fill from the daily PE entries to cover weekends/gaps
        ey_daily = ey_daily.sort_index().ffill()

    # Convert everything to string-date indexed series for safe merging
    ey_s = _to_str_index(ey_daily)
    real_s = _to_str_index(real_yield_10y.dropna())

    if ey_s is None or real_s is None:
        return {"top_chart": [], "diff_chart": [], "summary": [],
                "error": "Missing earnings yield or real yield data"}

    common = sorted(set(ey_s.index) & set(real_s.index))
    if len(common) < 50:
        return {"top_chart": [], "diff_chart": [], "summary": [],
                "error": f"Not enough overlapping data: EY={len(ey_s)}, DFII10={len(real_s)}, common={len(common)}"}

    # Compute ERP on aligned string-date index
    erp_vals = [float(ey_s[d]) - float(real_s[d]) for d in common]
    erp = pd.Series(erp_vals, index=common)

    # Term premium - ACM
    tp_acm = None
    if acm_term_premium is not None and len(acm_term_premium.dropna()) > 50:
        tp_acm = _to_str_index(acm_term_premium.dropna())

    # Term premium - 2s10s proxy
    tp_2s10s = None
    if dgs10 is not None and dgs2 is not None:
        d10_s = _to_str_index(dgs10.dropna())
        d2_s = _to_str_index(dgs2.dropna())
        if d10_s is not None and d2_s is not None:
            c = sorted(set(d10_s.index) & set(d2_s.index))
            if len(c) > 50:
                tp_2s10s = pd.Series(
                    [float(d10_s[d]) - float(d2_s[d]) for d in c],
                    index=c,
                )

    # ERP minus ACM term premium
    erp_minus_tp = None
    if tp_acm is not None:
        c = sorted(set(erp.index) & set(tp_acm.index))
        if len(c) > 50:
            erp_minus_tp = pd.Series(
                [float(erp[d]) - float(tp_acm[d]) for d in c],
                index=c,
            )

    # Build merged chart timeline
    top_chart = _merge_timelines(erp, tp_acm, tp_2s10s)
    diff_chart = []
    if erp_minus_tp is not None:
        for d, v in erp_minus_tp.items():
            fv = float(v)
            if not np.isnan(fv):
                diff_chart.append({"date": d, "value": round(fv, 4)})

    # Summary statistics
    summary = []
    for name, series in [
        ("Equity Risk Premium", erp),
        ("Term Premium (ACM)", tp_acm),
        ("Term Premium (2s10s)", tp_2s10s),
    ]:
        if series is None or len(series) < 10:
            continue
        s = series.dropna().astype(float)
        current = float(s.iloc[-1])
        avg_1y = float(s.iloc[-252:].mean()) if len(s) >= 252 else float(s.mean())
        avg_5y = float(s.iloc[-1260:].mean()) if len(s) >= 1260 else float(s.mean())
        hist_mean = float(s.mean())
        hist_std = float(s.std())
        percentile = float((s < current).sum() / len(s) * 100)
        zscore = (current - hist_mean) / hist_std if hist_std > 0 else 0

        summary.append({
            "name": name,
            "current": round(current, 3),
            "avg_1y": round(avg_1y, 3),
            "avg_5y": round(avg_5y, 3),
            "percentile": round(percentile, 1),
            "zscore": round(zscore, 2),
            "hist_mean": round(hist_mean, 3),
        })

    # Current PE and EY — prefer daily Yahoo data over stale Shiller
    daily_store = get_daily_pe_history()
    if daily_store:
        latest_date = max(daily_store.keys())
        latest_pe = daily_store[latest_date].get("pe", 0)
        latest_ey = daily_store[latest_date].get("ey", 0)
    else:
        latest_pe = float(shiller["PE"].dropna().iloc[-1]) if len(shiller["PE"].dropna()) > 0 else 0
        latest_ey = float(shiller["EY"].dropna().iloc[-1]) if len(shiller["EY"].dropna()) > 0 else 0

    return {
        "top_chart": top_chart,
        "diff_chart": diff_chart,
        "summary": summary,
        "current_pe": round(latest_pe, 1),
        "current_ey": round(latest_ey, 2),
    }


def _to_str_index(s):
    """Convert any series to string date index, deduplicating."""
    if s is None or len(s) == 0:
        return None
    s = s.copy()
    s.index = [str(d)[:10] for d in s.index]
    return s[~s.index.duplicated(keep='last')]


def _merge_timelines(erp, tp_acm, tp_2s10s):
    """Merge multiple series into a single chart-ready timeline."""
    frames = {}
    for name, s in [("erp", erp), ("tp_acm", tp_acm), ("tp_2s10s", tp_2s10s)]:
        cleaned = _to_str_index(s)
        if cleaned is not None and len(cleaned) > 0:
            frames[name] = cleaned

    if not frames:
        return []

    # Merge on string date keys to avoid all datetime type issues
    all_dates = sorted(set().union(*[set(s.index) for s in frames.values()]))
    result = []
    prev = {}
    for date in all_dates:
        entry = {"date": date}
        for name, s in frames.items():
            if date in s.index:
                val = float(s[date])
                if not np.isnan(val):
                    prev[name] = val
            entry[name] = round(prev.get(name), 4) if prev.get(name) is not None else None
        result.append(entry)

    return result
