"""Risk premia calculations — Equity Risk Premium and Bond Term Premium."""

import pandas as pd
import numpy as np


def compute_risk_premia(
    spx_prices: pd.Series,
    real_yield_10y: pd.Series,
    acm_term_premium: pd.Series = None,
    dgs10: pd.Series = None,
    dgs2: pd.Series = None,
    pe_ratio: float = None,
) -> dict:
    """
    Compute ERP and term premium time series + summary statistics.

    ERP = S&P 500 Earnings Yield - 10Y Real Yield
    Earnings Yield = 1 / PE ratio (approximated as rolling or fixed)
    """
    # Earnings yield: use trailing PE if provided, otherwise estimate from price
    if pe_ratio and pe_ratio > 0:
        current_ey = (1.0 / pe_ratio) * 100  # percentage
    else:
        pe_ratio = 24.0  # reasonable default
        current_ey = (1.0 / pe_ratio) * 100

    # Build ERP time series
    # Approximate: use a slowly-varying PE estimate (PE was ~15-25 over history)
    # For a proper time series, we'd need historical PE data
    # Rough approach: use S&P earnings yield proxy = 1/PE, assume PE reverts around 20
    ey_series = pd.Series(current_ey, index=real_yield_10y.index)

    # Try to build a better earnings yield proxy from price momentum
    if spx_prices is not None and len(spx_prices) > 252:
        # Rolling earnings proxy: assume earnings grow with price over long term
        # Use 1-year trailing return as growth proxy, base PE on mean-reversion
        spx = spx_prices.reindex(real_yield_10y.index).ffill()
        if len(spx.dropna()) > 252:
            # Historical S&P PE has ranged 12-30, averaging ~20
            # Use CAPE-like smoothing: 10Y average earnings proxy
            price_10y_avg = spx.rolling(2520, min_periods=252).mean()
            # Earnings yield = smoothed price relationship
            ey_proxy = (price_10y_avg / spx) * current_ey
            ey_proxy = ey_proxy.clip(2.0, 12.0)  # reasonable bounds
            valid = ey_proxy.dropna()
            if len(valid) > 100:
                ey_series = ey_proxy

    erp = ey_series - real_yield_10y
    erp = erp.dropna()

    # Term premium
    tp_acm = None
    if acm_term_premium is not None:
        tp_acm = acm_term_premium.dropna()

    tp_2s10s = None
    if dgs10 is not None and dgs2 is not None:
        common = dgs10.index.intersection(dgs2.index)
        tp_2s10s = (dgs10.reindex(common) - dgs2.reindex(common))
        tp_2s10s = tp_2s10s.dropna()

    # ERP minus Term Premium
    erp_minus_tp = None
    if tp_acm is not None:
        common = erp.index.intersection(tp_acm.index)
        if len(common) > 50:
            erp_minus_tp = erp.reindex(common) - tp_acm.reindex(common)

    # Build chart timelines
    def _to_timeline(s, name):
        if s is None or len(s) == 0:
            return []
        return [{"date": dt.strftime("%Y-%m-%d"), name: round(float(v), 4)}
                for dt, v in s.items() if not np.isnan(v)]

    erp_tl = _to_timeline(erp, "erp")
    tp_acm_tl = _to_timeline(tp_acm, "tp_acm") if tp_acm is not None else []
    tp_2s10s_tl = _to_timeline(tp_2s10s, "tp_2s10s") if tp_2s10s is not None else []
    diff_tl = _to_timeline(erp_minus_tp, "erp_minus_tp") if erp_minus_tp is not None else []

    # Merge timelines for the top chart
    top_chart = _merge_timelines(erp, tp_acm, tp_2s10s)
    diff_chart = _to_timeline(erp_minus_tp, "value") if erp_minus_tp is not None else []

    # Summary statistics
    summary = []
    for name, series in [
        ("Equity Risk Premium", erp),
        ("Term Premium (ACM)", tp_acm),
        ("Term Premium (2s10s)", tp_2s10s),
    ]:
        if series is None or len(series) < 10:
            continue
        current = float(series.iloc[-1])
        avg_1y = float(series.iloc[-252:].mean()) if len(series) >= 252 else float(series.mean())
        avg_5y = float(series.iloc[-1260:].mean()) if len(series) >= 1260 else float(series.mean())
        hist_mean = float(series.mean())
        hist_std = float(series.std())
        percentile = float((series < current).sum() / len(series) * 100)
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

    return {
        "top_chart": top_chart,
        "diff_chart": diff_chart,
        "summary": summary,
        "current_pe": round(pe_ratio, 1),
        "current_ey": round(current_ey, 2),
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

    combined = pd.DataFrame(frames)
    combined = combined.ffill()

    result = []
    for dt, row in combined.iterrows():
        entry = {"date": dt.strftime("%Y-%m-%d")}
        for col in combined.columns:
            v = row[col]
            entry[col] = round(float(v), 4) if not np.isnan(v) else None
        result.append(entry)

    return result
