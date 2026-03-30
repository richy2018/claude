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
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from .config import FRED_API_KEY, FRED_SERIES, YAHOO_TICKERS, SECTOR_ETFS, REGIME_DEFINITIONS
from .data.fred_fetcher import fetch_all_fred, compute_monthly_derived
from .data.yahoo_fetcher import fetch_all_yahoo, fetch_sector_holdings
from .data.sofr_parser import (
    parse_sofr_csv,
    generate_sample_sofr_curve,
    compute_implied_fed_funds_path,
    compute_meeting_probabilities,
    compute_terminal_rate,
    get_sofr_strip,
    compute_key_spreads,
)
from .data.processor import (
    align_daily_series,
    compute_rolling_returns,
    compute_rolling_zscores,
    compute_rolling_correlations,
    compute_linkage_metric,
    classify_linkage,
    prepare_json_series,
)
from .models.fair_value import compute_inflation_model, compute_growth_model
from .models.factor_analysis import (
    compute_factor_decomposition,
    get_sector_holdings_weights,
    generate_sample_holdings,
    SECTOR_ETF_MAP,
)
from .models.regime_classifier import (
    classify_regimes,
    compute_regime_stats,
    compute_transition_matrix,
    compute_transition_from_current,
    compute_regime_linkage,
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
    return {"status": "ok", "timestamp": datetime.now().isoformat(), "has_api_key": bool(FRED_API_KEY)}


def _find_col(df, *candidates):
    """Find the first available column from a list of candidates."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _get_series(name, *candidates):
    """Get a data series from aligned data, falling back to raw FRED/Yahoo caches.
    This handles the case where date alignment produces NaN columns."""
    # Try aligned data first
    aligned = _cache.get("aligned_data")
    if aligned is not None:
        for col in candidates:
            if col in aligned.columns:
                s = aligned[col].dropna()
                if len(s) > 50:
                    return s

    # Fall back to raw yahoo data
    yahoo = _cache.get("yahoo_data")
    if yahoo is not None:
        for col in candidates:
            if col in yahoo.columns:
                s = yahoo[col].dropna()
                if len(s) > 50:
                    # Strip timezone by extracting date only
                    s.index = pd.to_datetime(s.index.date)
                    s = s[~s.index.duplicated(keep='last')]
                    return s

    # Fall back to raw fred data
    fred = _cache.get("fred_data")
    if fred is not None:
        for col in candidates:
            if col in fred.columns:
                s = fred[col].dropna()
                if len(s) > 50:
                    s.index = pd.to_datetime(s.index.date)
                    return s

    return None


def _get_regime_assets(df):
    """Get the 3 regime asset series with robust lookups across all data caches."""
    spx = _get_series("SPX", "^GSPC", "SPY")
    rates = _get_series("10Y", "DGS10", "^TNX")
    dxy = _get_series("DXY", "DX-Y.NYB", "DTWEXBGS")

    missing = []
    if spx is None:
        missing.append("SPX (need ^GSPC or SPY)")
    if rates is None:
        missing.append("10Y (need DGS10 or ^TNX)")
    if dxy is None:
        missing.append("DXY (need DX-Y.NYB or DTWEXBGS)")

    if missing:
        avail_cols = []
        for cache_name in ["aligned_data", "yahoo_data", "fred_data"]:
            c = _cache.get(cache_name)
            if c is not None and hasattr(c, 'columns'):
                avail_cols.extend(list(c.columns))
        raise HTTPException(
            status_code=400,
            detail=f"Missing data for: {', '.join(missing)}. Available: {list(set(avail_cols))[:30]}"
        )

    # Align to common dates
    common = spx.index.intersection(rates.index).intersection(dxy.index)
    if len(common) < 50:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough overlapping data. SPX: {len(spx)}, 10Y: {len(rates)}, DXY: {len(dxy)}, common: {len(common)}"
        )

    return spx.reindex(common), rates.reindex(common), dxy.reindex(common)


@app.api_route("/api/refresh", methods=["GET", "POST"])
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

    # Diagnostics for the response
    aligned = _cache.get("aligned_data")
    aligned_info = {}
    if aligned is not None and not aligned.empty:
        aligned_info = {
            "total_columns": len(aligned.columns),
            "total_rows": len(aligned),
            "date_range": f"{aligned.index.min().strftime('%Y-%m-%d')} to {aligned.index.max().strftime('%Y-%m-%d')}",
            "columns": list(aligned.columns),
        }

    return safe_json_response({
        "status": "ok",
        "last_refresh": _cache["last_refresh"],
        "fred_series_count": len(fred_df.columns) if not fred_df.empty else 0,
        "yahoo_series_count": len(yahoo_df.columns) if not yahoo_df.empty else 0,
        "aligned": aligned_info,
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
    spx, rates, dxy = _get_regime_assets(df)

    # Classify
    regime_df = classify_regimes(spx, rates, dxy, lookback=lookback, vol_window=vol_window, vol_scaled=vol_scaled)

    if len(regime_df) == 0:
        # Return safe empty response
        return safe_json_response({
            "current_regime": "R1", "current_description": "Insufficient data",
            "current_color": REGIME_DEFINITIONS["R1"]["color"],
            "current_spx_metric": 0, "current_rates_metric": 0, "current_dxy_metric": 0,
            "current_linkage": 50, "linkage_label": "MODERATE",
            "stats": [], "transition_matrix": {"matrix": [], "counts": [], "regimes": []},
            "from_current": [], "timeline": [], "linkage_timeline": [],
            "regime_linkage": {}, "lookback": lookback, "vol_window": vol_window,
            "vol_scaled": vol_scaled, "range_days": range_days, "total_days": 0,
            "spx_last": float(spx.iloc[-1]) if len(spx) > 0 else 0,
            "rates_last": float(rates.iloc[-1]) if len(rates) > 0 else 0,
            "dxy_last": float(dxy.iloc[-1]) if len(dxy) > 0 else 0,
        })

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

    # Per-regime linkage and theme data
    regime_linkage = compute_regime_linkage(regime_df, spx, rates, dxy)

    # Enrich from_current with per-destination-regime median returns and linkage
    stats_lookup = {s["regime"]: s for s in stats}
    for t in from_current:
        dest = t["to"]
        if dest in stats_lookup:
            t["spx_median"] = stats_lookup[dest]["spx_median"]
            t["rates_median"] = stats_lookup[dest]["rates_median"]
            t["dxy_median"] = stats_lookup[dest]["dxy_median"]
        if dest in regime_linkage:
            t["linkage"] = regime_linkage[dest]["median_linkage"]

    # Enrich stats with linkage and theme
    for s in stats:
        r = s["regime"]
        if r in regime_linkage:
            s["linkage"] = regime_linkage[r]["median_linkage"]
            s["theme"] = regime_linkage[r]["theme"]

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
        "regime_linkage": regime_linkage,
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


@app.get("/api/sectors/factors")
async def get_sector_factors(
    sector: str = Query(default="Energy"),
    lookback: int = Query(default=10),
):
    """Compute factor decomposition for a sector's top holdings."""
    if _cache["yahoo_data"] is None:
        raise HTTPException(status_code=400, detail="No data loaded. Call /api/refresh first.")

    yahoo_df = _cache["yahoo_data"]

    # Get SPY and sector ETF prices
    if "SPY" not in yahoo_df.columns:
        raise HTTPException(status_code=400, detail="SPY data not available")

    spy = yahoo_df["SPY"].dropna()
    etf_ticker = SECTOR_ETF_MAP.get(sector)
    if not etf_ticker or etf_ticker not in yahoo_df.columns:
        raise HTTPException(status_code=400, detail=f"Sector ETF {etf_ticker} not available")

    sector_etf = yahoo_df[etf_ticker].dropna()

    # Get holdings weights
    weights = {}
    if _cache["sector_holdings"] and etf_ticker in _cache["sector_holdings"]:
        weights = get_sector_holdings_weights(sector, _cache["sector_holdings"])

    if not weights:
        weights = generate_sample_holdings(sector)

    # Try to fetch stock prices from yahoo cache or generate sample data
    stock_tickers = list(weights.keys())
    available_stocks = [t for t in stock_tickers if t in yahoo_df.columns]

    if available_stocks:
        stock_prices = yahoo_df[available_stocks]
    else:
        # Generate synthetic factor data for demo
        stock_prices = _generate_synthetic_stock_data(stock_tickers, spy, sector_etf, weights)

    result = compute_factor_decomposition(
        stock_prices=stock_prices,
        spy_prices=spy,
        sector_etf_prices=sector_etf,
        weights=weights,
        lookback_days=lookback,
    )

    result["sector"] = sector
    result["etf_ticker"] = etf_ticker
    result["lookback"] = lookback

    return safe_json_response(result)


def _generate_synthetic_stock_data(
    tickers: list,
    spy: pd.Series,
    sector_etf: pd.Series,
    weights: dict,
) -> pd.DataFrame:
    """Generate synthetic stock price data correlated with market/sector for demo."""
    np.random.seed(42)
    common = spy.index.intersection(sector_etf.index)
    spy_r = spy.reindex(common).pct_change().fillna(0)
    sec_r = sector_etf.reindex(common).pct_change().fillna(0)

    data = {}
    for ticker in tickers:
        beta_mkt = np.random.uniform(0.7, 1.5)
        beta_sec = np.random.uniform(0.1, 0.6)
        noise = np.random.randn(len(common)) * 0.005
        stock_ret = beta_mkt * spy_r + beta_sec * (sec_r - spy_r) + noise
        price = (1 + stock_ret).cumprod() * 100
        data[ticker] = price.values

    return pd.DataFrame(data, index=common)


@app.get("/api/fair-value")
async def get_fair_value(model: str = Query(default="cpi"), measure: str = Query(default="headline")):
    """
    Get fair value model data for inflation/growth models.
    model: cpi, pce, ppi, growth
    measure: headline, core
    """
    if _cache["fred_data"] is None:
        raise HTTPException(status_code=400, detail="No data loaded. Call /api/refresh first.")

    df = _cache["fred_data"]

    if model == "cpi":
        series_id = "CPILFESL" if measure == "core" else "CPIAUCSL"
        series_name = "Core CPI" if measure == "core" else "CPI"
        if series_id not in df.columns:
            raise HTTPException(status_code=404, detail=f"{series_id} not available")
        result = compute_inflation_model(df[series_id], series_name)
        return safe_json_response(result)

    elif model == "pce":
        series_id = "PCEPILFE" if measure == "core" else "PCEPI"
        series_name = "Core PCE" if measure == "core" else "PCE"
        if series_id not in df.columns:
            raise HTTPException(status_code=404, detail=f"{series_id} not available")
        result = compute_inflation_model(df[series_id], series_name)
        return safe_json_response(result)

    elif model == "ppi":
        series_id = "PPIFIS"
        series_name = "PPI"
        if series_id not in df.columns:
            raise HTTPException(status_code=404, detail=f"{series_id} not available")
        result = compute_inflation_model(df[series_id], series_name)
        return safe_json_response(result)

    elif model == "growth":
        payrolls = df["PAYEMS"] if "PAYEMS" in df.columns else None
        claims = df["ICSA"] if "ICSA" in df.columns else None
        gdp = df["GDP"] if "GDP" in df.columns else None
        result = compute_growth_model(payrolls=payrolls, claims=claims, gdp=gdp)
        return safe_json_response(result)

    else:
        raise HTTPException(status_code=400, detail=f"Unknown model: {model}")


@app.get("/api/stir")
async def get_stir():
    """Get STIR (Short-Term Interest Rates) data from SOFR curve."""
    # Try to load real SOFR CSV, fall back to sample
    sofr_csv_path = Path(__file__).parent / "data" / "sofr_curve.csv"
    if sofr_csv_path.exists():
        try:
            sofr_df = parse_sofr_csv(str(sofr_csv_path))
        except Exception:
            sofr_df = generate_sample_sofr_curve()
    else:
        sofr_df = generate_sample_sofr_curve()

    # Get current FFR from cache if available
    current_ffr = 3.625  # default
    if _cache["fred_data"] is not None and "DFF" in _cache["fred_data"].columns:
        ffr_series = _cache["fred_data"]["DFF"].dropna()
        if len(ffr_series) > 0:
            current_ffr = float(ffr_series.iloc[-1]) / 100 if ffr_series.iloc[-1] > 10 else float(ffr_series.iloc[-1])

    # Compute all STIR data
    terminal = compute_terminal_rate(sofr_df)
    implied_path = compute_implied_fed_funds_path(sofr_df, current_ffr)
    meeting_probs = compute_meeting_probabilities(sofr_df, current_ffr)
    strip = get_sofr_strip(sofr_df)
    spreads = compute_key_spreads(sofr_df)

    return safe_json_response({
        "current_ffr": current_ffr,
        "terminal": terminal,
        "implied_path": implied_path,
        "meeting_probabilities": meeting_probs,
        "strip": strip,
        "spreads": spreads,
    })


@app.get("/api/synthesis")
async def get_synthesis(
    lookback: int = Query(default=21),
    vol_window: int = Query(default=21),
    vol_scaled: bool = Query(default=True),
):
    """Compute synthesis data: stock-bond regime, dollar durability, curve regime, rate decomposition."""
    if _cache["aligned_data"] is None:
        raise HTTPException(status_code=400, detail="No data loaded. Call /api/refresh first.")

    df = _cache["aligned_data"]

    try:
        spx_c, rates_c, dxy_c = _get_regime_assets(df)
    except HTTPException:
        # Return safe empty synthesis if assets not available
        return safe_json_response({
            "stock_bond_regime": "N/A", "spx_metric": 0, "rates_metric": 0, "dxy_metric": 0,
            "dollar_regime": "N/A", "dollar_text": "Insufficient data",
            "dxy_last": 0, "dxy_chg": 0, "curve_regime": "N/A", "curve_v": 0,
            "top_transitions": [], "decomposition": [], "current_regime": "R1",
        })

    regime_df = classify_regimes(spx_c, rates_c, dxy_c, lookback=lookback, vol_window=vol_window, vol_scaled=vol_scaled)

    if len(regime_df) == 0:
        return safe_json_response({
            "stock_bond_regime": "N/A", "spx_metric": 0, "rates_metric": 0, "dxy_metric": 0,
            "dollar_regime": "N/A", "dollar_text": "Insufficient data for regime classification",
            "dxy_last": float(dxy_c.iloc[-1]) if len(dxy_c) > 0 else 0, "dxy_chg": 0,
            "curve_regime": "N/A", "curve_v": 0, "top_transitions": [], "decomposition": [],
            "current_regime": "R1",
        })

    current = regime_df.iloc[-1]
    spx_metric = float(current["spx_metric"])
    rates_metric = float(current["rates_metric"])
    dxy_metric = float(current["dxy_metric"])

    # Stock-Bond Regime
    spx_up = spx_metric > 0
    rates_up = rates_metric > 0
    if spx_up and rates_up:
        sb_regime = "GROWTH / INFLATION"
    elif spx_up and not rates_up:
        sb_regime = "GOLDILOCKS / FED-PUT"
    elif not spx_up and rates_up:
        sb_regime = "STAGFLATION RISK"
    else:
        sb_regime = "FLIGHT TO SAFETY"

    # Dollar Durability
    dxy_up = dxy_metric > 0
    if dxy_up:
        dollar_regime = "DURABLE"
        if not spx_up and rates_up:
            dollar_text = "Dollar confirms stagflation — worst-case macro, all signals aligned on stress"
        elif not spx_up:
            dollar_text = "Dollar strength in risk-off — classic safe-haven bid, flight to quality"
        else:
            dollar_text = "Dollar rising with risk-on — strong growth pulling capital inflows"
    else:
        dollar_regime = "FRAGILE"
        if not spx_up:
            dollar_text = "Dollar weakness suggests risk-off is localized, not systemic"
        elif rates_up:
            dollar_text = "Dollar weak despite rising rates — inflation fears eroding real purchasing power"
        else:
            dollar_text = "Dollar weakening in goldilocks — Fed easing expectations outweigh growth"

    # Curve Regime (2s10s)
    rates_2y_col = _find_col(df, "DGS2")
    rates_10y_col = _find_col(df, "DGS10", "^TNX")
    curve_regime = "N/A"
    curve_v = 0.0
    if rates_2y_col and rates_10y_col:
        r2 = df[rates_2y_col].dropna()
        r10 = df[rates_10y_col].dropna()
        common_curve = r2.index.intersection(r10.index)
        spread_2s10s = r10.reindex(common_curve) - r2.reindex(common_curve)

        if len(spread_2s10s) > lookback:
            spread_chg = spread_2s10s.diff(lookback).iloc[-1]
            rate_chg = r10.reindex(common_curve).diff(lookback).iloc[-1]

            if not np.isnan(spread_chg) and not np.isnan(rate_chg):
                curve_steepening = spread_chg > 0
                rates_rising = rate_chg > 0

                if rates_rising and not curve_steepening:
                    curve_regime = "Bear Flattener"
                elif not rates_rising and curve_steepening:
                    curve_regime = "Bull Steepener"
                elif rates_rising and curve_steepening:
                    curve_regime = "Bear Steepener"
                else:
                    curve_regime = "Bull Flattener"

            # Curve-cross asset V: correlation of curve changes with regime asset changes
            spx_ret = spx_c.pct_change().rolling(lookback).sum()
            curve_chg = spread_2s10s.reindex(spx_ret.index).diff(lookback)
            valid = pd.DataFrame({"spx": spx_ret, "curve": curve_chg}).dropna()
            if len(valid) > 30:
                curve_v = abs(float(valid["spx"].corr(valid["curve"])))

    # DXY last values
    dxy_last = float(dxy_c.iloc[-1]) if len(dxy_c) > 0 else 0
    dxy_chg = float(dxy_c.pct_change().iloc[-1] * 100) if len(dxy_c) > 1 else 0

    # Multi-lookback rate decomposition
    tenor_map = {
        "5Y": {"nom": "DGS5", "be": "T5YIE", "real": "DFII5"},
        "10Y": {"nom": "DGS10", "be": "T10YIE", "real": "DFII10"},
        "30Y": {"nom": "DGS30", "be": None, "real": "DFII30"},
    }
    # Also add 1Y and 2Y (no breakevens available, so just nominal)
    if "DGS1" in df.columns:
        tenor_map["1Y"] = {"nom": "DGS1", "be": None, "real": None}
    if "DGS2" in df.columns:
        tenor_map["2Y"] = {"nom": "DGS2", "be": None, "real": None}

    decomposition_lookbacks = [5, 10, 20, 60]
    decomposition = []
    tenor_order = ["1Y", "2Y", "5Y", "10Y", "30Y"]

    for tenor in tenor_order:
        if tenor not in tenor_map:
            continue
        tm = tenor_map[tenor]
        row = {"tenor": tenor}

        for lb in decomposition_lookbacks:
            nom_col = tm["nom"]
            be_col = tm.get("be")
            real_col = tm.get("real")

            nom_chg = None
            real_chg = None
            infl_chg = None

            if nom_col and nom_col in df.columns:
                s = df[nom_col].dropna()
                if len(s) > lb:
                    nom_chg = float((s.iloc[-1] - s.iloc[-lb]) * 100)  # bp

            if real_col and real_col in df.columns:
                s = df[real_col].dropna()
                if len(s) > lb:
                    real_chg = float((s.iloc[-1] - s.iloc[-lb]) * 100)  # bp

            if nom_chg is not None and real_chg is not None:
                infl_chg = nom_chg - real_chg
            elif be_col and be_col in df.columns:
                s = df[be_col].dropna()
                if len(s) > lb:
                    infl_chg = float((s.iloc[-1] - s.iloc[-lb]) * 100)
                    if nom_chg is not None and real_chg is None:
                        real_chg = nom_chg - infl_chg

            row[f"{lb}d_nom"] = round(nom_chg, 1) if nom_chg is not None else None
            row[f"{lb}d_real"] = round(real_chg, 1) if real_chg is not None else None
            row[f"{lb}d_infl"] = round(infl_chg, 1) if infl_chg is not None else None

        decomposition.append(row)

    # Top transition probabilities for curve regime context
    from_current = compute_transition_from_current(regime_df["regime"], regime_df.iloc[-1]["regime"])
    top_transitions = from_current[:3]

    return safe_json_response({
        "stock_bond_regime": sb_regime,
        "spx_metric": spx_metric,
        "rates_metric": rates_metric,
        "dxy_metric": dxy_metric,
        "dollar_regime": dollar_regime,
        "dollar_text": dollar_text,
        "dxy_last": dxy_last,
        "dxy_chg": round(dxy_chg, 2),
        "curve_regime": curve_regime,
        "curve_v": round(curve_v, 3),
        "top_transitions": top_transitions,
        "decomposition": decomposition,
        "current_regime": regime_df.iloc[-1]["regime"] if len(regime_df) > 0 else "R1",
    })


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


# --- Serve built frontend as static files ---
_static_dir = Path(__file__).parent.parent / "frontend" / "dist"
if _static_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(_static_dir / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the React SPA for any non-API route."""
        file_path = _static_dir / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_static_dir / "index.html"))
