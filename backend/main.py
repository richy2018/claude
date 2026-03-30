"""FastAPI backend for the Macro Regime Dashboard."""

import os
import json
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import FRED_API_KEY, FRED_SERIES, YAHOO_TICKERS, SECTOR_ETFS, REGIME_DEFINITIONS
from .data.fred_fetcher import fetch_all_fred, compute_monthly_derived
from .data.yahoo_fetcher import fetch_all_yahoo, fetch_sector_holdings
from .data.processor import (
    align_daily_series,
    compute_rolling_returns,
    compute_rolling_zscores,
    compute_rolling_correlations,
    compute_linkage_metric,
    classify_linkage,
    prepare_json_series,
)
from .models.regime_classifier import (
    classify_regimes,
    compute_regime_stats,
    compute_transition_matrix,
    compute_transition_from_current,
    get_regime_description,
)

app = FastAPI(title="CFR Rates Regime Dashboard API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory data cache
_cache = {
    "fred_data": None,
    "yahoo_data": None,
    "aligned_data": None,
    "monthly_derived": None,
    "sector_holdings": None,
    "last_refresh": None,
}


def _nan_safe_json(obj):
    """Convert NaN/Inf to None for JSON serialization."""
    if isinstance(obj, float):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return round(obj, 6)
    if isinstance(obj, (np.floating,)):
        val = float(obj)
        if np.isnan(val) or np.isinf(val):
            return None
        return round(val, 6)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, np.ndarray):
        return [_nan_safe_json(x) for x in obj.tolist()]
    if isinstance(obj, dict):
        return {k: _nan_safe_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_nan_safe_json(x) for x in obj]
    return obj


class NanSafeEncoder(json.JSONEncoder):
    def default(self, obj):
        return _nan_safe_json(obj)


def safe_json_response(data):
    """Return a JSONResponse with NaN-safe serialization."""
    clean = _nan_safe_json(data)
    return JSONResponse(content=clean)


@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.post("/api/refresh")
async def refresh_data(fred_api_key: str = Query(default=None)):
    """Fetch all data from FRED and Yahoo Finance."""
    api_key = fred_api_key or FRED_API_KEY
    errors = {}

    try:
        fred_df, fred_errors = fetch_all_fred(api_key=api_key, start_date="2000-01-01")
        _cache["fred_data"] = fred_df
        if fred_errors:
            errors["fred"] = fred_errors
    except Exception as e:
        errors["fred_fatal"] = str(e)
        fred_df = pd.DataFrame()

    try:
        yahoo_df, yahoo_errors = fetch_all_yahoo(period="20y")
        _cache["yahoo_data"] = yahoo_df
        if yahoo_errors:
            errors["yahoo"] = yahoo_errors
    except Exception as e:
        errors["yahoo_fatal"] = str(e)
        yahoo_df = pd.DataFrame()

    # Align daily series
    if not fred_df.empty or not yahoo_df.empty:
        frames = [f for f in [fred_df, yahoo_df] if not f.empty]
        _cache["aligned_data"] = align_daily_series(*frames)

    # Compute monthly derived series
    if not fred_df.empty:
        _cache["monthly_derived"] = compute_monthly_derived(fred_df)

    _cache["last_refresh"] = datetime.now().isoformat()

    return safe_json_response({
        "status": "ok",
        "last_refresh": _cache["last_refresh"],
        "fred_series_count": len(fred_df.columns) if not fred_df.empty else 0,
        "yahoo_series_count": len(yahoo_df.columns) if not yahoo_df.empty else 0,
        "errors": errors,
    })


@app.get("/api/data/fred")
async def get_fred_data(series: str = Query(default=None)):
    """Get FRED data, optionally filtered by series ID."""
    if _cache["fred_data"] is None:
        raise HTTPException(status_code=400, detail="No data loaded. Call /api/refresh first.")

    df = _cache["fred_data"]
    if series:
        series_list = [s.strip() for s in series.split(",")]
        available = [s for s in series_list if s in df.columns]
        if not available:
            raise HTTPException(status_code=404, detail=f"Series not found: {series}")
        df = df[available]

    return safe_json_response(prepare_json_series(df.tail(2520)))  # ~10 years of daily data


@app.get("/api/data/yahoo")
async def get_yahoo_data(tickers: str = Query(default=None)):
    """Get Yahoo Finance data."""
    if _cache["yahoo_data"] is None:
        raise HTTPException(status_code=400, detail="No data loaded. Call /api/refresh first.")

    df = _cache["yahoo_data"]
    if tickers:
        ticker_list = [t.strip() for t in tickers.split(",")]
        available = [t for t in ticker_list if t in df.columns]
        if not available:
            raise HTTPException(status_code=404, detail=f"Tickers not found: {tickers}")
        df = df[available]

    return safe_json_response(prepare_json_series(df.tail(5040)))


@app.get("/api/data/monthly")
async def get_monthly_derived(series: str = Query(default=None)):
    """Get monthly derived series (MoM%, YoY%, annualized)."""
    if _cache["monthly_derived"] is None:
        raise HTTPException(status_code=400, detail="No data loaded. Call /api/refresh first.")

    result = {}
    derived = _cache["monthly_derived"]

    target_series = [series] if series else list(derived.keys())

    for s in target_series:
        if s in derived:
            result[s] = {
                "mom_pct": prepare_json_series(derived[s]["mom_pct"].to_frame(s)),
                "yoy_pct": prepare_json_series(derived[s]["yoy_pct"].to_frame(s)),
                "annualized_3m": prepare_json_series(derived[s]["annualized_3m"].to_frame(s)),
            }

    return safe_json_response(result)


@app.get("/api/regimes")
async def get_regimes(
    lookback: int = Query(default=21),
    vol_window: int = Query(default=21),
    vol_scaled: bool = Query(default=True),
    range_days: int = Query(default=500),
):
    """Compute and return regime classification data."""
    if _cache["aligned_data"] is None:
        raise HTTPException(status_code=400, detail="No data loaded. Call /api/refresh first.")

    df = _cache["aligned_data"]

    # Get the 3 assets
    spx_col = "^GSPC" if "^GSPC" in df.columns else None
    rates_col = "DGS10" if "DGS10" in df.columns else "^TNX"
    dxy_col = "DX-Y.NYB" if "DX-Y.NYB" in df.columns else "DTWEXBGS"

    if spx_col is None:
        raise HTTPException(status_code=400, detail="S&P 500 data not available")

    spx = df[spx_col].dropna()
    rates = df[rates_col].dropna()
    dxy = df[dxy_col].dropna()

    # Align the three series
    common = spx.index.intersection(rates.index).intersection(dxy.index)
    spx = spx.reindex(common)
    rates = rates.reindex(common)
    dxy = dxy.reindex(common)

    # Classify
    regime_df = classify_regimes(spx, rates, dxy, lookback=lookback, vol_window=vol_window, vol_scaled=vol_scaled)

    # Trim to requested range
    if range_days > 0 and len(regime_df) > range_days:
        regime_df = regime_df.iloc[-range_days:]
        spx = spx.reindex(regime_df.index)
        rates = rates.reindex(regime_df.index)
        dxy = dxy.reindex(regime_df.index)

    # Current regime info
    current = regime_df.iloc[-1] if len(regime_df) > 0 else None
    current_regime = current["regime"] if current is not None else "R1"

    # Stats
    stats = compute_regime_stats(regime_df, spx, rates, dxy)

    # Transition matrix
    transitions = compute_transition_matrix(regime_df["regime"])

    # Transitions from current
    from_current = compute_transition_from_current(regime_df["regime"], current_regime)

    # Correlations and linkage
    asset_df = pd.DataFrame({"SPX": spx, "10Y": rates, "DXY": dxy}).dropna()
    corr_df = compute_rolling_correlations(asset_df, window=63)
    linkage = compute_linkage_metric(corr_df)
    current_linkage = float(linkage.iloc[-1]) if len(linkage) > 0 and not np.isnan(linkage.iloc[-1]) else 50.0

    # Timeline data
    timeline = []
    for dt, row in regime_df.iterrows():
        timeline.append({
            "date": dt.strftime("%Y-%m-%d"),
            "regime": row["regime"],
            "spx_metric": row["spx_metric"],
            "rates_metric": row["rates_metric"],
            "dxy_metric": row["dxy_metric"],
            "color": REGIME_DEFINITIONS[row["regime"]]["color"],
        })

    # Linkage timeline
    linkage_timeline = []
    corr_cols = corr_df.columns.tolist()
    for dt in corr_df.index:
        entry = {"date": dt.strftime("%Y-%m-%d")}
        for col in corr_cols:
            val = corr_df.loc[dt, col]
            entry[col] = float(val) if not np.isnan(val) else None
        entry["linkage"] = float(linkage.loc[dt]) if dt in linkage.index and not np.isnan(linkage.loc[dt]) else None
        linkage_timeline.append(entry)

    return safe_json_response({
        "current_regime": current_regime,
        "current_description": get_regime_description(current_regime),
        "current_color": REGIME_DEFINITIONS[current_regime]["color"],
        "current_spx_metric": current["spx_metric"] if current is not None else 0,
        "current_rates_metric": current["rates_metric"] if current is not None else 0,
        "current_dxy_metric": current["dxy_metric"] if current is not None else 0,
        "current_linkage": current_linkage,
        "linkage_label": classify_linkage(current_linkage),
        "stats": stats,
        "transition_matrix": transitions,
        "from_current": from_current,
        "timeline": timeline,
        "linkage_timeline": linkage_timeline[-range_days:] if range_days > 0 else linkage_timeline,
        "lookback": lookback,
        "vol_window": vol_window,
        "vol_scaled": vol_scaled,
        "range_days": range_days,
        "total_days": len(regime_df),
        "spx_last": float(spx.iloc[-1]) if len(spx) > 0 else 0,
        "rates_last": float(rates.iloc[-1]) if len(rates) > 0 else 0,
        "dxy_last": float(dxy.iloc[-1]) if len(dxy) > 0 else 0,
    })


@app.get("/api/regime-definitions")
async def get_regime_definitions():
    """Return regime color/label definitions."""
    return safe_json_response(REGIME_DEFINITIONS)


@app.get("/api/sectors/holdings")
async def get_sector_holdings():
    """Get top holdings for each sector ETF."""
    if _cache["sector_holdings"] is None:
        try:
            _cache["sector_holdings"] = fetch_sector_holdings()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return safe_json_response(_cache["sector_holdings"])


@app.get("/api/status")
async def get_status():
    """Get current data status."""
    return safe_json_response({
        "last_refresh": _cache["last_refresh"],
        "has_fred": _cache["fred_data"] is not None,
        "has_yahoo": _cache["yahoo_data"] is not None,
        "has_aligned": _cache["aligned_data"] is not None,
        "fred_series": list(_cache["fred_data"].columns) if _cache["fred_data"] is not None else [],
        "yahoo_tickers": list(_cache["yahoo_data"].columns) if _cache["yahoo_data"] is not None else [],
    })
