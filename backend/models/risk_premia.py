"""Risk premia calculations using actual Shiller earnings data."""

import pandas as pd
import numpy as np
from pathlib import Path


def load_shiller_earnings() -> pd.DataFrame:
    """Load Shiller S&P 500 price/earnings data."""
    path = Path(__file__).parent.parent / "data" / "shiller_pe.csv"
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path, sep="\t")
    # Parse date: format is YYYY.MM
    df["date"] = df["Date"].apply(lambda x: pd.Timestamp(
        year=int(str(x).split(".")[0]),
        month=int(str(x).split(".")[1]) if "." in str(x) else 1,
        day=1,
    ))
    df = df.set_index("date").sort_index()

    # Forward-fill earnings for months where it's missing
    df["Earnings"] = pd.to_numeric(df["Earnings"], errors="coerce")
    df["Price"] = pd.to_numeric(df["Price"], errors="coerce")
    df["Earnings"] = df["Earnings"].ffill()

    # Compute trailing PE and earnings yield
    df["PE"] = df["Price"] / df["Earnings"]
    df["EY"] = (df["Earnings"] / df["Price"]) * 100  # earnings yield in %

    return df


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

    # Resample earnings yield to daily by forward-filling monthly data
    ey_monthly = shiller["EY"].dropna()
    ey_daily = ey_monthly.resample("D").ffill()
    # Normalize dates to match FRED data format
    ey_daily.index = pd.to_datetime(ey_daily.index.date)

    # Align EY with real yield
    real = real_yield_10y.dropna()
    real.index = pd.to_datetime(real.index.date)
    common = ey_daily.index.intersection(real.index)
    if len(common) < 50:
        return {"top_chart": [], "diff_chart": [], "summary": [],
                "error": f"Not enough overlapping data: EY={len(ey_daily)}, DFII10={len(real)}, common={len(common)}"}

    ey = ey_daily.reindex(common)
    real_r = real.reindex(common)
    erp = ey - real_r

    # Term premium - ACM
    tp_acm = None
    if acm_term_premium is not None and len(acm_term_premium.dropna()) > 50:
        tp_acm = acm_term_premium.dropna()

    # Term premium - 2s10s proxy
    tp_2s10s = None
    if dgs10 is not None and dgs2 is not None:
        c = dgs10.index.intersection(dgs2.index)
        if len(c) > 50:
            tp_2s10s = (dgs10.reindex(c) - dgs2.reindex(c)).dropna()

    # ERP minus ACM term premium
    erp_minus_tp = None
    if tp_acm is not None:
        c = erp.index.intersection(tp_acm.index)
        if len(c) > 50:
            erp_minus_tp = erp.reindex(c) - tp_acm.reindex(c)

    # Build merged chart timeline
    top_chart = _merge_timelines(erp, tp_acm, tp_2s10s)
    diff_chart = [{"date": dt.strftime("%Y-%m-%d"), "value": round(float(v), 4)}
                  for dt, v in (erp_minus_tp or pd.Series(dtype=float)).items()
                  if not np.isnan(v)]

    # Summary statistics
    summary = []
    for name, series in [
        ("Equity Risk Premium", erp),
        ("Term Premium (ACM)", tp_acm),
        ("Term Premium (2s10s)", tp_2s10s),
    ]:
        if series is None or len(series) < 10:
            continue
        s = series.dropna()
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

    # Current PE and EY
    latest_pe = float(shiller["PE"].dropna().iloc[-1]) if len(shiller["PE"].dropna()) > 0 else 0
    latest_ey = float(shiller["EY"].dropna().iloc[-1]) if len(shiller["EY"].dropna()) > 0 else 0

    return {
        "top_chart": top_chart,
        "diff_chart": diff_chart,
        "summary": summary,
        "current_pe": round(latest_pe, 1),
        "current_ey": round(latest_ey, 2),
    }


def _merge_timelines(erp, tp_acm, tp_2s10s):
    """Merge multiple series into a single chart-ready timeline."""
    frames = {}
    if erp is not None and len(erp) > 0:
        frames["erp"] = erp
    if tp_acm is not None and len(tp_acm) > 0:
        frames["tp_acm"] = tp_acm
    if tp_2s10s is not None and len(tp_2s10s) > 0:
        frames["tp_2s10s"] = tp_2s10s

    if not frames:
        return []

    combined = pd.DataFrame(frames).ffill()

    result = []
    for dt, row in combined.iterrows():
        entry = {"date": dt.strftime("%Y-%m-%d")}
        for col in combined.columns:
            v = row[col]
            entry[col] = round(float(v), 4) if not np.isnan(v) else None
        result.append(entry)

    return result
