"""FastAPI backend for the Macro Regime Dashboard."""

import os
import json
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, Query, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from .config import FRED_API_KEY, FRED_SERIES, YAHOO_TICKERS, SECTOR_ETFS, REGIME_DEFINITIONS, GLI_FED_SERIES
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
from .models.risk_premia import compute_risk_premia
from .data.pe_store import fetch_and_store_pe
from .data.tic_parser import load_tic_data, compute_tic_summary
from .data.bond_parser import parse_bond_csv, filter_bonds, get_bond_summary
from .models.optimizer import optimize_portfolio
from .models.curve_regimes import (
    classify_curve_regimes,
    compute_curve_regime_stats,
    SPREAD_PAIRS,
    CURVE_REGIMES,
)
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


@app.on_event("startup")
async def startup_load_cache():
    """Load persistent cache on startup. No API calls — just disk read."""
    has_cache = _load_persistent_cache()
    if has_cache:
        print(f"[STARTUP] Serving from persistent cache (last refreshed: {_cache.get('last_refresh')})")
    else:
        print("[STARTUP] No persistent cache. Click REFRESH to load data.")

# --- Persistent cache ---
# Use Render persistent disk if available, otherwise local data dir
_RENDER_DISK = Path("/opt/render/data")
if _RENDER_DISK.exists():
    _CACHE_FILE = _RENDER_DISK / "dashboard_cache.json"
    print(f"[CACHE] Using Render persistent disk: {_CACHE_FILE}")
else:
    _CACHE_FILE = Path(__file__).resolve().parent / "data" / "dashboard_cache.json"
    print(f"[CACHE] Using local path: {_CACHE_FILE}")

def _save_persistent_cache():
    """Save the in-memory cache to a JSON file for persistence across restarts."""
    try:
        serializable = {}
        for key, val in _cache.items():
            if val is None:
                serializable[key] = None
            elif isinstance(val, pd.DataFrame):
                # Save DataFrames as CSV strings — simple and reliable
                try:
                    csv_str = val.to_csv()
                    serializable[key] = {"_type": "dataframe_csv", "csv": csv_str}
                except Exception as e:
                    print(f"[CACHE] Skip {key} (DataFrame serialize error): {e}")
            elif isinstance(val, str):
                serializable[key] = {"_type": "string", "value": val}
            elif isinstance(val, (dict, list)):
                # For dicts/lists, convert NaN/Inf to None first
                try:
                    clean = json.loads(json.dumps(val, default=str))
                    serializable[key] = {"_type": "json", "value": clean}
                except Exception as e:
                    print(f"[CACHE] Skip {key} (dict serialize error): {e}")
            else:
                serializable[key] = {"_type": "string", "value": str(val)}

        _CACHE_FILE.write_text(json.dumps(serializable))
        size_kb = _CACHE_FILE.stat().st_size / 1024
        print(f"[CACHE] Saved {len(serializable)} keys ({size_kb:.0f} KB) to {_CACHE_FILE}")
    except Exception as e:
        print(f"[CACHE] SAVE FAILED: {e}")
        import traceback; traceback.print_exc()


def _load_persistent_cache() -> bool:
    """Load the persistent cache from disk on startup."""
    if not _CACHE_FILE.exists():
        print(f"[CACHE] No cache file at {_CACHE_FILE}")
        return False
    try:
        size_kb = _CACHE_FILE.stat().st_size / 1024
        raw = json.loads(_CACHE_FILE.read_text())
        loaded = 0
        for key, val in raw.items():
            if val is None:
                _cache[key] = None
                continue
            try:
                t = val.get("_type") if isinstance(val, dict) else None
                if t == "dataframe_csv":
                    from io import StringIO
                    df = pd.read_csv(StringIO(val["csv"]), index_col=0, parse_dates=True)
                    _cache[key] = df
                    loaded += 1
                    print(f"[CACHE] Loaded {key}: DataFrame {df.shape}, cols={list(df.columns)[:10]}")
                elif t == "string":
                    _cache[key] = val["value"]
                    loaded += 1
                elif t == "json":
                    _cache[key] = val["value"]
                    loaded += 1
                elif isinstance(val, dict):
                    _cache[key] = val
                    loaded += 1
            except Exception as e:
                print(f"[CACHE] Failed to load key '{key}': {e}")

        # Recompute derived data from loaded DataFrames
        fred_df = _cache.get("fred_data")
        yahoo_df = _cache.get("yahoo_data")
        if isinstance(fred_df, pd.DataFrame) and not fred_df.empty:
            if isinstance(yahoo_df, pd.DataFrame) and not yahoo_df.empty:
                try:
                    _cache["aligned_data"] = align_daily_series(fred_df, yahoo_df)
                    print(f"[CACHE] Recomputed aligned_data: {_cache['aligned_data'].shape}")
                except Exception as e:
                    print(f"[CACHE] aligned_data recompute failed: {e}")
            try:
                _cache["monthly_derived"] = compute_monthly_derived(fred_df)
                print(f"[CACHE] Recomputed monthly_derived")
            except Exception as e:
                print(f"[CACHE] monthly_derived recompute failed: {e}")

        has_data = _cache.get("last_refresh") is not None
        print(f"[CACHE] Loaded {loaded} keys ({size_kb:.0f} KB), last_refresh={_cache.get('last_refresh')}")
        return has_data
    except Exception as e:
        print(f"[CACHE] LOAD FAILED: {e}")
        import traceback; traceback.print_exc()
        return False


# In-memory data cache
_cache = {
    "fred_data": None,
    "yahoo_data": None,
    "aligned_data": None,
    "monthly_derived": None,
    "sector_holdings": None,
    "last_refresh": None,
    "gli_fed_net": None,
    "gli_cb_sheets": None,
    "gli_bis_credit": None,
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


@app.get("/api/cache-status")
async def cache_status():
    """Check what data is available in the cache."""
    status = {}
    for key, val in _cache.items():
        if val is None:
            status[key] = None
        elif isinstance(val, pd.DataFrame):
            status[key] = f"DataFrame({len(val)} rows, {len(val.columns)} cols)"
        elif isinstance(val, dict):
            status[key] = f"dict({len(val)} keys)"
        elif isinstance(val, str):
            status[key] = val[:50]
        else:
            status[key] = str(type(val).__name__)
    return {
        "cached": _cache.get("last_refresh") is not None,
        "last_refresh": _cache.get("last_refresh"),
        "cache_file_exists": _CACHE_FILE.exists(),
        "cache_file_size_kb": round(_CACHE_FILE.stat().st_size / 1024, 1) if _CACHE_FILE.exists() else 0,
        "keys": status,
    }


def _find_col(df, *candidates):
    """Find the first available column from a list of candidates."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


# Yahoo yield tickers are reported as yield × 10 (e.g., ^TNX 42.77 = 4.277%)
# Divide by 10 to normalize to same scale as FRED (DGS10 = 4.277)
YAHOO_YIELD_TICKERS = {"^TNX", "^TYX", "^FVX"}


def _get_series(name, *candidates):
    """Get a data series from aligned data, falling back to raw FRED/Yahoo caches.
    Always returns a series with unique, tz-naive date index."""
    def _clean(s):
        """Normalize index and remove duplicates."""
        s = s.copy()
        s.index = pd.to_datetime(s.index.date)
        return s[~s.index.duplicated(keep='last')]

    # Try aligned data first
    aligned = _cache.get("aligned_data")
    if aligned is not None:
        for col in candidates:
            if col in aligned.columns:
                s = aligned[col].dropna()
                if len(s) > 50:
                    s = _clean(s)
                    if col in YAHOO_YIELD_TICKERS and s.median() > 20:
                        s = s / 10.0
                    return s

    # Fall back to raw yahoo data
    yahoo = _cache.get("yahoo_data")
    if yahoo is not None:
        for col in candidates:
            if col in yahoo.columns:
                s = yahoo[col].dropna()
                if len(s) > 50:
                    s = _clean(s)
                    if col in YAHOO_YIELD_TICKERS and s.median() > 20:
                        s = s / 10.0
                    return s

    # Fall back to raw fred data
    fred = _cache.get("fred_data")
    if fred is not None:
        for col in candidates:
            if col in fred.columns:
                s = fred[col].dropna()
                if len(s) > 50:
                    s = _clean(s)
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

    # Fetch and persist today's S&P 500 PE for ERP calculation
    try:
        pe_result = fetch_and_store_pe()
        pe_count = len(pe_result) if pe_result else 0
        print(f"[STARTUP] PE store: {pe_count} daily entries")
    except Exception as e:
        errors["pe_store"] = str(e)
        print(f"[STARTUP] PE store error: {e}")

    # Align daily series
    if not fred_df.empty or not yahoo_df.empty:
        frames = [f for f in [fred_df, yahoo_df] if not f.empty]
        _cache["aligned_data"] = align_daily_series(*frames)

    # Compute monthly derived series
    if not fred_df.empty:
        _cache["monthly_derived"] = compute_monthly_derived(fred_df)

    # GLI: refresh all layers (each wrapped in try/except so failures don't block others)
    gli_status = {}

    # GLI Fed net liquidity
    try:
        from .data.gli_fetcher import fetch_gli_fed, fetch_rrp_tga
        from .models.gli_engine import compute_fed_net_liquidity

        # Diagnostic: test RRP/TGA directly
        print("[REFRESH] === RRP/TGA DIAGNOSTIC ===")
        fetch_rrp_tga(api_key)
        print("[REFRESH] === END DIAGNOSTIC ===")

        fed_df_gli, fed_gli_errors = fetch_gli_fed(api_key=api_key)
        if fed_gli_errors:
            errors["gli_fed_series"] = fed_gli_errors
        fed_result = compute_fed_net_liquidity(fed_df_gli)

        # Add SPX price data for overlay chart
        try:
            spx = None
            # Try Yahoo cache first
            yahoo = _cache.get("yahoo_data")
            if yahoo is not None and "^GSPC" in yahoo.columns:
                spx = yahoo["^GSPC"].dropna()
                print(f"[REFRESH] GLI Fed: SPX from Yahoo cache ({len(spx)} points)")

            # Fallback: fetch SPY via yfinance directly
            if spx is None or len(spx) < 100:
                try:
                    import yfinance as yf
                    spy = yf.download("SPY", start="2003-01-01", progress=False)
                    if not spy.empty:
                        spx = spy["Close"].dropna()
                        if hasattr(spx, 'droplevel'):
                            spx = spx.droplevel(1) if spx.index.nlevels > 1 else spx
                        print(f"[REFRESH] GLI Fed: SPX from yfinance ({len(spx)} points)")
                except Exception as yfe:
                    print(f"[REFRESH] GLI Fed: yfinance failed: {yfe}")

            if spx is not None and len(spx) > 0:
                spx.index = pd.to_datetime(spx.index)
                spx_weekly = spx.resample("W-WED").last().dropna()
                spx_data = [{"date": d.strftime("%Y-%m-%d"), "spx": float(v)}
                            for d, v in spx_weekly.items()]
                fed_result["spx"] = spx_data
                print(f"[REFRESH] GLI Fed: added {len(spx_data)} SPX weekly points")
        except Exception as e:
            print(f"[REFRESH] GLI Fed SPX overlay error: {e}")

        fed_result["updated_at"] = datetime.now().isoformat()
        _cache["gli_fed_net"] = fed_result
        _save_gli_cache("fed", fed_result)
        gli_status["fed"] = "ok"
        print(f"[REFRESH] GLI Fed: {len(fed_result.get('components', []))} records")
    except Exception as e:
        errors["gli_fed"] = str(e)
        gli_status["fed"] = f"error: {e}"
        print(f"[REFRESH] GLI Fed error: {e}")

    # GLI Central Banks
    try:
        from .data.gli_fetcher import fetch_gli_cb_fred, fetch_gli_fx, fetch_ecb_balance_sheet, fetch_pboc_balance_sheet
        from .models.gli_engine import convert_cb_to_usd, compute_zscore_momentum as _cb_zscore

        cb_df, cb_errors = fetch_gli_cb_fred(api_key=api_key)
        if cb_errors:
            errors["gli_cb_fred"] = cb_errors
        fx_df, fx_errors = fetch_gli_fx(api_key=api_key)
        if fx_errors:
            errors["gli_cb_fx"] = fx_errors

        try:
            ecb = fetch_ecb_balance_sheet()
            cb_df["ECB"] = ecb.reindex(cb_df.index, method="nearest")
        except Exception as e:
            errors["gli_ecb"] = str(e)
            print(f"[REFRESH] GLI ECB error: {e}")

        pboc_available = False
        pboc_is_estimate = False
        try:
            pboc = fetch_pboc_balance_sheet()
            cb_df["PBoC"] = pboc.reindex(cb_df.index, method="nearest")
            pboc_available = True
            # Check if it's a static estimate (short series starting from 2020)
            if len(pboc) < 100:
                pboc_is_estimate = True
                print(f"[REFRESH] GLI PBoC: using static estimate ({len(pboc)} obs)")
            else:
                print(f"[REFRESH] GLI PBoC: {len(pboc)} obs loaded from API")
        except Exception as e:
            errors["gli_pboc"] = str(e)
            print(f"[REFRESH] GLI PBoC error: {e}")

        cb_monthly = cb_df.resample("MS").last().ffill()
        fx_monthly = fx_df.resample("MS").last().ffill()
        cb_usd = convert_cb_to_usd(cb_monthly, fx_monthly)

        z_scores = {}
        for col in cb_usd.columns:
            s = cb_usd[col].dropna()
            if len(s) > 12:
                z_scores[col] = _cb_zscore(s)

        cb_series = []
        for date, row in cb_usd.iterrows():
            entry = {"date": date.strftime("%Y-%m-%d")}
            for col in cb_usd.columns:
                entry[col] = row[col] if pd.notna(row[col]) else None
            entry["total"] = sum(v for v in row.values if pd.notna(v))
            cb_series.append(entry)

        latest_row = cb_usd.dropna(how="all").iloc[-1] if not cb_usd.empty else pd.Series()
        cb_summary = {}
        for col in cb_usd.columns:
            val = latest_row.get(col)
            cb_summary[col] = {
                "usd_billions": float(val) if pd.notna(val) else None,
                "momentum_score": z_scores.get(col, {}).get("momentum_score"),
            }

        # Compute Howell 65-month sine wave
        from .models.gli_engine import compute_howell_sine_wave
        sine_dates = cb_usd.index
        sine_wave = compute_howell_sine_wave(sine_dates)

        cb_result = {
            "series": cb_series, "z_scores": z_scores,
            "summary": cb_summary, "sine_wave": sine_wave,
            "warnings": ["PBoC: Manual estimate — no API source available"] if pboc_is_estimate else ([] if pboc_available else ["PBoC: Data unavailable"]),
            "pboc_available": pboc_available,
            "pboc_is_estimate": pboc_is_estimate,
            "updated_at": datetime.now().isoformat(),
        }
        _cache["gli_cb_sheets"] = cb_result
        _save_gli_cache("cb", cb_result)
        gli_status["cb"] = "ok"
        print(f"[REFRESH] GLI CB: {len(cb_series)} records, banks={list(cb_usd.columns)}")
    except Exception as e:
        errors["gli_cb"] = str(e)
        gli_status["cb"] = f"error: {e}"
        print(f"[REFRESH] GLI CB error: {e}")

    # GLI BIS Credit
    try:
        from .data.gli_fetcher import fetch_bis_credit
        from .models.gli_engine import interpolate_quarterly_to_monthly, compute_zscore_momentum as _bis_zscore, compute_diffusion_index

        bis_df, bis_errors = fetch_bis_credit()
        if bis_errors:
            errors["gli_bis_countries"] = bis_errors
        bis_monthly = interpolate_quarterly_to_monthly(bis_df)

        country_zscores = {}
        for col in bis_monthly.columns:
            s = bis_monthly[col].dropna()
            if len(s) > 24:
                country_zscores[col] = _bis_zscore(s, window=40)
                print(f"[BIS zscore] {col}: {len(s)} months, score={country_zscores[col].get('momentum_score', '?')}")
            else:
                print(f"[BIS zscore] {col}: SKIPPED, only {len(s)} months (need >24)")

        diffusion = compute_diffusion_index(country_zscores)

        bis_series = []
        for date, row in bis_monthly.iterrows():
            entry = {"date": date.strftime("%Y-%m-%d")}
            for col in bis_monthly.columns:
                entry[col] = float(row[col]) if pd.notna(row[col]) else None
            entry["total"] = sum(v for v in row.values if pd.notna(v))
            bis_series.append(entry)

        latest_row = bis_monthly.dropna(how="all").iloc[-1] if not bis_monthly.empty else pd.Series()
        country_summary = {}
        for col in bis_monthly.columns:
            val = latest_row.get(col)
            country_summary[col] = {
                "usd_billions": float(val) if pd.notna(val) else None,
                "momentum_score": country_zscores.get(col, {}).get("momentum_score"),
            }

        # Compute debt/liquidity ratio: BIS all-sector credit / BIS private NF credit
        debt_ratio = None
        try:
            from .models.gli_engine import compute_debt_liquidity_ratio
            from .data.gli_fetcher import fetch_bis_private_nf_credit
            if "All reporting countries" in bis_monthly.columns:
                all_sector = bis_monthly["All reporting countries"].dropna()
                # Fetch private non-financial credit (borrowing_sector=P)
                private_nf = fetch_bis_private_nf_credit()
                private_nf.index = pd.to_datetime(private_nf.index)
                # Interpolate to monthly
                private_nf_monthly = interpolate_quarterly_to_monthly(pd.DataFrame({"pnf": private_nf}))["pnf"].dropna()
                print(f"[REFRESH] GLI debt ratio: all_sector latest={all_sector.iloc[-1]:.0f}, private_nf latest={private_nf_monthly.iloc[-1]:.0f}")
                if len(all_sector) > 0 and len(private_nf_monthly) > 0:
                    # Get all 5 components for composite indicator
                    policy_rate = hy_spread = yield_curve = m2_supply = None
                    fred = _cache.get("fred_data")
                    if fred is not None and isinstance(fred, pd.DataFrame):
                        for rate_col in ["DFF", "FEDFUNDS"]:
                            if rate_col in fred.columns:
                                policy_rate = fred[rate_col].dropna()
                                break
                        if "BAMLH0A0HYM2" in fred.columns:
                            hy_spread = fred["BAMLH0A0HYM2"].dropna()
                        if "T10Y2Y" in fred.columns:
                            yield_curve = fred["T10Y2Y"].dropna()
                        if "M2SL" in fred.columns:
                            m2_supply = fred["M2SL"].dropna()
                    # Fetch Dollar Stress from gist
                    ds_series = None
                    try:
                        from .data.dollar_stress import get_dollar_stress
                        ds_series = get_dollar_stress()
                        print(f"[REFRESH] Dollar Stress: {len(ds_series)} months")
                    except Exception as ds_e:
                        print(f"[REFRESH] Dollar Stress fetch failed: {ds_e}")
                    debt_ratio = compute_debt_liquidity_ratio(
                        all_sector, private_nf_monthly,
                        policy_rate=policy_rate, hy_spread=hy_spread,
                        yield_curve=yield_curve, m2_supply=m2_supply,
                        dollar_stress=ds_series)
                    print(f"[REFRESH] GLI debt ratio: {debt_ratio.get('current_ratio', '?'):.2f}x, composite={debt_ratio.get('current_composite', '?')}, pct={debt_ratio.get('composite_percentile', '?')}, {len(debt_ratio.get('ratio_series', []))} pts")
        except Exception as e:
            print(f"[REFRESH] GLI debt ratio error: {e}")
            import traceback; traceback.print_exc()

        bis_result = {
            "series": bis_series, "z_scores": country_zscores,
            "diffusion": diffusion, "country_summary": country_summary,
            "debt_ratio": debt_ratio,
            "updated_at": datetime.now().isoformat(),
        }
        _cache["gli_bis_credit"] = bis_result
        _save_gli_cache("bis", bis_result)
        gli_status["bis"] = "ok"
        print(f"[REFRESH] GLI BIS: {len(bis_series)} records, countries={list(bis_monthly.columns)}")
    except Exception as e:
        errors["gli_bis"] = str(e)
        gli_status["bis"] = f"error: {e}"
        print(f"[REFRESH] GLI BIS error: {e}")

    _cache["last_refresh"] = datetime.now().isoformat()

    # Save all data to persistent cache file
    _save_persistent_cache()

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
        "gli": gli_status,
        "aligned": aligned_info,
        "errors": errors,
    })


@app.get("/api/data/fred")
async def get_fred_data(series: str = Query(default=None)):
    """Get FRED data, optionally filtered by series ID."""
    if _cache["fred_data"] is None:
        return safe_json_response({"cached": False, "message": "No data yet. Click Refresh to load."})

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
        return safe_json_response({"cached": False, "message": "No data yet. Click Refresh to load."})

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
        return safe_json_response({"cached": False, "message": "No data yet. Click Refresh to load."})

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
        return safe_json_response({"cached": False, "message": "No data yet. Click Refresh to load."})

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
            # Scale individual correlations to 0-100 absolute percentage (same scale as linkage)
            entry[col] = abs(float(val)) * 100 if not np.isnan(val) else None
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
        return safe_json_response({"cached": False, "message": "No data yet. Click Refresh to load."})

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
        return safe_json_response({"cached": False, "message": "No data yet. Click Refresh to load."})

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


# --- Portfolio Builder endpoints ---

@app.post("/api/portfolio/upload-bonds")
async def upload_bonds(file: UploadFile = File(...)):
    """Upload and parse a Bloomberg bond universe CSV."""
    try:
        content = await file.read()
        text = content.decode('utf-8', errors='replace')
        bonds = parse_bond_csv(text)
        _cache["bond_universe"] = bonds
        summary = get_bond_summary(bonds)
        return safe_json_response({"status": "ok", "summary": summary})
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {str(e)}")


@app.get("/api/portfolio/bonds")
async def get_bonds(
    search: str = Query(default=""),
    currencies: str = Query(default=""),
    rating_min: int = Query(default=None),
    rating_max: int = Query(default=None),
    maturity_min: float = Query(default=None),
    maturity_max: float = Query(default=None),
    duration_min: float = Query(default=None),
    duration_max: float = Query(default=None),
    ytm_min: float = Query(default=None),
    ytm_max: float = Query(default=None),
    oas_min: float = Query(default=None),
    oas_max: float = Query(default=None),
    coupon_min: float = Query(default=None),
    coupon_max: float = Query(default=None),
    amount_min: float = Query(default=None),
    default_prob_max: float = Query(default=None),
    payment_ranks: str = Query(default=""),
    asset_classes: str = Query(default=""),
):
    """Get filtered bond universe."""
    # Auto-load sample bonds if nothing uploaded
    if _cache.get("bond_universe") is None:
        # Try new bond template first, fall back to sample_bonds.csv
        for csv_name in ["Bond template.csv", "sample_bonds.csv"]:
            sample_path = Path(__file__).parent / "data" / csv_name
            if sample_path.exists():
                with open(sample_path, encoding='utf-8-sig') as f:
                    _cache["bond_universe"] = parse_bond_csv(f.read())
                break
    if _cache.get("bond_universe") is None:
        raise HTTPException(status_code=400, detail="No bond universe loaded. Upload a CSV first.")

    filters = {
        'search': search, 'currencies': currencies,
        'rating_min': rating_min, 'rating_max': rating_max,
        'maturity_min': maturity_min, 'maturity_max': maturity_max,
        'duration_min': duration_min, 'duration_max': duration_max,
        'ytm_min': ytm_min, 'ytm_max': ytm_max,
        'oas_min': oas_min, 'oas_max': oas_max,
        'coupon_min': coupon_min, 'coupon_max': coupon_max,
        'amount_min': amount_min, 'default_prob_max': default_prob_max,
        'payment_ranks': payment_ranks, 'asset_classes': asset_classes,
    }
    # Remove None values
    filters = {k: v for k, v in filters.items() if v is not None and v != ""}

    filtered = filter_bonds(_cache["bond_universe"], filters)
    summary = get_bond_summary(filtered)

    return safe_json_response({
        "bonds": filtered,
        "summary": summary,
        "total_universe": len(_cache["bond_universe"]),
    })


@app.post("/api/portfolio/optimize")
async def run_optimizer(constraints: dict = None):
    """Run portfolio optimizer on the uploaded bond universe."""
    if _cache.get("bond_universe") is None:
        raise HTTPException(status_code=400, detail="No bond universe loaded.")

    if constraints is None:
        constraints = {}

    try:
        result = optimize_portfolio(_cache["bond_universe"], constraints)
        return safe_json_response(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Optimizer failed: {str(e)}")


@app.get("/api/portfolio/equity/{ticker}")
async def get_equity_data(ticker: str):
    """Fetch equity data from yfinance for portfolio construction. Cached with retry."""
    import asyncio

    # Cache key v3 — forces re-fetch to fix dividend yield scaling
    cache_key = f"equity_v3_{ticker.upper()}"
    cached = _cache.get(cache_key)
    if cached and cached.get('roe') is not None:
        return safe_json_response(cached)

    # Retry up to 3 times with delays for rate limiting
    for attempt in range(3):
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            info = t.info or {}

            if not info or not info.get("shortName"):
                if attempt < 2:
                    await asyncio.sleep(3)
                    continue
                raise Exception("No data returned — ticker may be invalid")

            # Get trailing 3Y return
            hist = t.history(period="3y")
            cap_appreciation = None
            if hist is not None and len(hist) > 60:
                start_price = float(hist['Close'].iloc[0])
                end_price = float(hist['Close'].iloc[-1])
                years = len(hist) / 252
                if start_price > 0 and years > 0:
                    cap_appreciation = ((end_price / start_price) ** (1 / years) - 1) * 100

            raw_div = info.get("dividendYield") or 0
            # yfinance returns dividendYield as a decimal (e.g. 0.0041 for 0.41%)
            # Guard against values already in percentage form (>0.15 means >15% — unlikely for real div yield)
            div_yield = raw_div * 100 if raw_div < 0.15 else raw_div

            # Fundamental metrics — try multiple key names for compatibility
            def _get(*keys):
                for k in keys:
                    v = info.get(k)
                    if v is not None:
                        return v
                return None

            roe = _get("returnOnEquity", "return_on_equity")
            net_margin = _get("profitMargins", "profit_margins", "netMargin")
            rev_growth = _get("revenueGrowth", "revenue_growth", "earningsGrowth")
            debt_equity = _get("debtToEquity", "debt_to_equity")
            payout_ratio = _get("payoutRatio", "payout_ratio")
            free_cf = _get("freeCashflow", "free_cashflow", "operatingCashflow")
            market_cap_val = _get("marketCap", "market_cap")
            fcf_yield = (free_cf / market_cap_val * 100) if free_cf and market_cap_val and market_cap_val > 0 else None

            result = {
                "ticker": ticker.upper(),
                "name": info.get("longName") or info.get("shortName") or ticker,
                "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "currency": info.get("currency", "USD"),
                "dividend_yield": round(div_yield, 2),
                "beta": info.get("beta"),
                "pe_ratio": info.get("trailingPE"),
                "sector": info.get("sector", "N/A"),
                "industry": info.get("industry", "N/A"),
                "market_cap": market_cap_val,
                "trailing_3y_return": round(cap_appreciation, 2) if cap_appreciation is not None else None,
                "historical_vol": None,
                "roe": round(roe * 100, 1) if roe else None,
                "net_margin": round(net_margin * 100, 1) if net_margin else None,
                "revenue_growth": round(rev_growth * 100, 1) if rev_growth else None,
                "debt_equity": round(debt_equity, 1) if debt_equity else None,
                "fcf_yield": round(fcf_yield, 2) if fcf_yield else None,
                "payout_ratio": round(payout_ratio * 100, 1) if payout_ratio else None,
            }

            _cache[cache_key] = result
            return safe_json_response(result)

        except Exception as e:
            if "Rate" in str(e) or "Too Many" in str(e):
                if attempt < 2:
                    await asyncio.sleep(5 * (attempt + 1))  # 5s, 10s
                    continue
            raise HTTPException(status_code=400, detail=f"Failed to fetch {ticker}: {str(e)}")


@app.get("/api/tic-holdings")
async def get_tic_holdings(
    range_years: int = Query(default=10),
    countries: str = Query(default=""),
):
    """Serve TIC Major Foreign Holders data."""
    if _cache.get("tic_data") is None:
        tic = load_tic_data()
        if tic is None:
            raise HTTPException(status_code=400, detail="TIC data not available. Run fetch_tic.py first.")
        _cache["tic_data"] = tic

    data = _cache["tic_data"]

    # Filter by date range
    if range_years > 0:
        from datetime import datetime
        cutoff_year = datetime.now().year - range_years
        cutoff = f"{cutoff_year}-{datetime.now().month:02d}"
    else:
        cutoff = "1990-01"

    def _filter_series(series):
        dates = series['dates']
        values = series['values']
        filtered = [(d, v) for d, v in zip(dates, values) if d >= cutoff]
        if not filtered:
            return {'dates': [], 'values': []}
        return {'dates': [x[0] for x in filtered], 'values': [x[1] for x in filtered]}

    # Filter countries if specified
    country_list = [c.strip() for c in countries.split(',') if c.strip()] if countries else None

    result_countries = {}
    for name, series in data.get('countries', {}).items():
        if country_list and name not in country_list:
            continue
        result_countries[name] = _filter_series(series)

    result_aggregates = {}
    for key, series in data.get('aggregates', {}).items():
        result_aggregates[key] = _filter_series(series)

    # Compute summary
    summary = compute_tic_summary(data)

    return safe_json_response({
        'countries': result_countries,
        'aggregates': result_aggregates,
        'summary': summary[:20],  # top 20
        'metadata': data.get('metadata', {}),
    })


@app.get("/api/risk-premia")
async def get_risk_premia(range_days: int = Query(default=2520)):
    """Compute risk premia: ERP and term premium."""
    if _cache["fred_data"] is None and _cache["yahoo_data"] is None:
        return safe_json_response({"cached": False, "message": "No data yet. Click Refresh to load."})

    # Get SPX prices
    spx = _get_series("SPX", "^GSPC", "SPY")

    # Get real yield
    real_10y = _get_series("DFII10", "DFII10")
    if real_10y is None:
        raise HTTPException(status_code=400, detail="DFII10 (10Y TIPS) not available")

    # Get ACM term premium
    tp_acm = _get_series("THREEFYTP10", "THREEFYTP10")

    # Get nominal yields for 2s10s proxy
    dgs10 = _get_series("DGS10", "DGS10", "^TNX")
    dgs2 = _get_series("DGS2", "DGS2")

    # Normalize ^TNX if used
    if dgs10 is not None and dgs10.median() > 20:
        dgs10 = dgs10 / 10.0

    try:
        result = compute_risk_premia(
            real_yield_10y=real_10y,
            acm_term_premium=tp_acm,
            dgs10=dgs10,
            dgs2=dgs2,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Risk premia computation failed: {str(e)}")

    # Trim chart data to range
    if range_days > 0:
        result["top_chart"] = result["top_chart"][-range_days:]
        result["diff_chart"] = result["diff_chart"][-range_days:]

    return safe_json_response(result)


@app.get("/api/curve-regimes")
async def get_curve_regimes(
    pair: str = Query(default="10Y-2Y"),
    lookback: int = Query(default=21),
    range_days: int = Query(default=504),
):
    """Compute yield curve regime classification."""
    if _cache["aligned_data"] is None and _cache["fred_data"] is None:
        return safe_json_response({"cached": False, "message": "No data yet. Click Refresh to load."})

    if pair not in SPREAD_PAIRS:
        raise HTTPException(status_code=400, detail=f"Unknown pair: {pair}. Available: {list(SPREAD_PAIRS.keys())}")

    short_col, long_col = SPREAD_PAIRS[pair]

    # Try to get data from caches
    def _find(col):
        for cache_name in ["fred_data", "aligned_data"]:
            c = _cache.get(cache_name)
            if c is not None and col in c.columns:
                s = c[col].dropna()
                if len(s) > 50:
                    s.index = pd.to_datetime(s.index.date)
                    s = s[~s.index.duplicated(keep='last')]
                    return s
        return None

    short = _find(short_col)
    long = _find(long_col)

    if short is None:
        raise HTTPException(status_code=400, detail=f"Short tenor {short_col} not available")
    if long is None:
        raise HTTPException(status_code=400, detail=f"Long tenor {long_col} not available")

    # Align
    common = short.index.intersection(long.index)
    short = short.reindex(common)
    long = long.reindex(common)

    # Classify
    regime_df = classify_curve_regimes(short, long, lookback=lookback)

    # Trim to range
    if range_days > 0 and len(regime_df) > range_days:
        regime_df = regime_df.iloc[-range_days:]
        short = short.reindex(regime_df.index)
        long = long.reindex(regime_df.index)

    # Stats
    stats = compute_curve_regime_stats(regime_df, short, long)

    # Timeline for chart
    timeline = []
    for dt, row in regime_df.iterrows():
        timeline.append({
            "date": dt.strftime("%Y-%m-%d"),
            "regime": row["regime"],
            "spread_bp": round(float(row["spread_bp"]), 1),
            "color": CURVE_REGIMES.get(row["regime"], {}).get("color", "#888"),
            "short_yield": round(float(row["short_yield"]), 3),
            "long_yield": round(float(row["long_yield"]), 3),
        })

    # Current state
    current = regime_df.iloc[-1] if len(regime_df) > 0 else None

    # Short/long tenor labels from the pair
    pair_parts = pair.split("-")

    return safe_json_response({
        "pair": pair,
        "short_label": pair_parts[1] if len(pair_parts) > 1 else short_col,
        "long_label": pair_parts[0] if len(pair_parts) > 0 else long_col,
        "lookback": lookback,
        "total_days": len(regime_df),
        "current_regime": current["regime"] if current is not None else "N/A",
        "current_spread_bp": round(float(current["spread_bp"]), 1) if current is not None else 0,
        "current_color": CURVE_REGIMES.get(current["regime"], {}).get("color", "#888") if current is not None else "#888",
        "stats": stats,
        "timeline": timeline,
        "regime_definitions": {k: v for k, v in CURVE_REGIMES.items()},
    })


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
        return safe_json_response({"cached": False, "message": "No data yet. Click Refresh to load."})

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


# --- GLI (Global Liquidity Index) endpoints ---

_GLI_CACHE_DIR = _RENDER_DISK if _RENDER_DISK.exists() else Path(__file__).resolve().parent / "data"

def _load_gli_cache(layer: str) -> dict | None:
    """Load GLI cache from JSON file."""
    path = _GLI_CACHE_DIR / f"gli_cache_{layer}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _save_gli_cache(layer: str, data: dict):
    """Save GLI cache to JSON file."""
    path = _GLI_CACHE_DIR / f"gli_cache_{layer}.json"
    path.write_text(json.dumps(data, indent=2, default=str))


# Load GLI caches on module import (no API calls)
for _layer in ("fed", "cb", "bis"):
    _cached = _load_gli_cache(_layer)
    if _cached is not None:
        _cache[f"gli_{_layer}_net" if _layer == "fed" else f"gli_{_layer}_{'sheets' if _layer == 'cb' else 'credit'}"] = _cached


@app.get("/api/gli/fed-net-liquidity")
async def get_gli_fed_net():
    """Get Fed net liquidity components and net value."""
    data = _cache.get("gli_fed_net")
    if data is None:
        return safe_json_response({"cached": False, "message": "No GLI Fed data yet. Click Refresh."})
    return safe_json_response(data)


@app.get("/api/gli/central-banks")
async def get_gli_central_banks():
    """Get central bank balance sheets in USD with z-scores."""
    data = _cache.get("gli_cb_sheets")
    if data is None:
        return safe_json_response({"cached": False, "message": "No GLI CB data yet. Click Refresh."})
    return safe_json_response(data)


@app.get("/api/gli/bis-credit")
async def get_gli_bis_credit():
    """Get BIS total credit data with diffusion index."""
    data = _cache.get("gli_bis_credit")
    if data is None:
        return safe_json_response({"cached": False, "message": "No GLI BIS data yet. Click Refresh."})
    return safe_json_response(data)


@app.get("/api/ticker-overlay")
async def get_ticker_overlay(ticker: str = Query(...), start: str = Query(default="2005-01-01")):
    """Fetch price data + z-score normalized for chart overlay."""
    try:
        import yfinance as yf
        data = yf.download(ticker, start=start, progress=False)
        if data.empty:
            raise HTTPException(status_code=404, detail=f"No data for ticker '{ticker}'")
        close = data["Close"]
        if hasattr(close, "droplevel") and close.index.nlevels > 1:
            close = close.droplevel(1)
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = close.dropna()
        monthly = close.resample("MS").last().dropna()

        # Raw price points
        raw_points = [{"date": d.strftime("%Y-%m-%d"), "price": float(v)} for d, v in monthly.items()]

        # Z-score normalized: YoY return → rolling z-score → scale to -1..+1
        yoy_ret = monthly.pct_change(12) * 100
        roll_mean = yoy_ret.rolling(36, min_periods=12).mean()
        roll_std = yoy_ret.rolling(36, min_periods=12).std().replace(0, np.nan)
        z = ((yoy_ret - roll_mean) / roll_std).clip(-3, 3)
        z_scaled = (z / 3).fillna(0)  # -1 to +1 range
        zscore_points = [{"date": d.strftime("%Y-%m-%d"), "zscore": float(v)}
                         for d, v in z_scaled.dropna().items()]

        return safe_json_response({
            "ticker": ticker,
            "points": raw_points,
            "zscore_points": zscore_points,
            "latest": float(monthly.iloc[-1]),
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/gli/composite-backtest")
async def get_composite_backtest(
    mode: str = Query(default="sweep"),
    signal_type: str = Query(default="mom3"),
    regime_filter: str = Query(default="all"),
    model: str = Query(default="3fa"),
    n_factors: int = Query(default=None),
):
    """Backtest: mode=sweep runs full 216-config sweep, mode=detail runs single config."""
    try:
        import yfinance as yf
        from .models.backtest_engine import run_sweep, run_detail

        bis_data = _cache.get("gli_bis_credit")
        if not bis_data or not bis_data.get("debt_ratio"):
            return safe_json_response({"cached": False, "message": "No BIS data. Refresh first."})

        ratio_series = bis_data["debt_ratio"].get("ratio_series", [])
        if len(ratio_series) < 60:
            return safe_json_response({"error": "Not enough data"})

        spy = yf.download("SPY", start="2003-01-01", progress=False)
        if spy.empty:
            return safe_json_response({"error": "Failed to fetch SPY"})
        spy_close = spy["Close"]
        if hasattr(spy_close, "droplevel") and spy_close.index.nlevels > 1:
            spy_close = spy_close.droplevel(1)
        if isinstance(spy_close, pd.DataFrame):
            spy_close = spy_close.iloc[:, 0]
        spy_m = spy_close.resample("MS").last().dropna()

        vix = None
        yahoo = _cache.get("yahoo_data")
        if yahoo is not None and isinstance(yahoo, pd.DataFrame) and "^VIX" in yahoo.columns:
            vix = yahoo["^VIX"].dropna()
        fred = _cache.get("fred_data")
        fred_df = fred if isinstance(fred, pd.DataFrame) else None

        if mode == "detail":
            result = run_detail(ratio_series, spy_m, signal_type, regime_filter,
                                fred_data=fred_df, vix_data=vix, model=model, n_factors=n_factors)
        else:
            result = run_sweep(ratio_series, spy_m, fred_data=fred_df, vix_data=vix, model=model, n_factors=n_factors)

        return safe_json_response(result)
    except Exception as e:
        print(f"[BACKTEST] Error: {e}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.api_route("/api/gli/refresh", methods=["POST"])
async def refresh_gli(layer: str = Query(default="fed"), fred_api_key: str = Query(default=None)):
    """Refresh GLI data for a specific layer (fed, cb, bis, all)."""
    from .data.gli_fetcher import fetch_gli_fed
    from .models.gli_engine import compute_fed_net_liquidity

    api_key = fred_api_key or FRED_API_KEY
    if not api_key:
        raise HTTPException(status_code=400, detail="FRED_API_KEY not set.")

    results = {}
    errors = {}
    layers = ["fed", "cb", "bis"] if layer == "all" else [layer]

    for lyr in layers:
        try:
            if lyr == "fed":
                fed_df, fed_errors = fetch_gli_fed(api_key=api_key)
                if fed_errors:
                    errors["fed_series"] = fed_errors
                fed_result = compute_fed_net_liquidity(fed_df)
                # Add SPX overlay from Yahoo cache
                try:
                    yahoo = _cache.get("yahoo_data")
                    if yahoo is not None and "^GSPC" in yahoo.columns:
                        spx = yahoo["^GSPC"].dropna().resample("W-WED").last().dropna()
                        fed_result["spx"] = [{"date": d.strftime("%Y-%m-%d"), "spx": float(v)} for d, v in spx.items()]
                except Exception:
                    pass
                fed_result["updated_at"] = datetime.now().isoformat()
                _cache["gli_fed_net"] = fed_result
                _save_gli_cache("fed", fed_result)
                results["fed"] = {
                    "status": "ok",
                    "records": len(fed_result.get("components", [])),
                    "latest": fed_result.get("latest", {}),
                }
            elif lyr == "cb":
                # Delegate to main refresh logic by calling the same code path
                # (avoid duplicating 60+ lines)
                from .data.gli_fetcher import fetch_gli_cb_fred, fetch_gli_fx, fetch_ecb_balance_sheet, fetch_pboc_balance_sheet
                from .models.gli_engine import convert_cb_to_usd, compute_zscore_momentum, compute_howell_sine_wave

                cb_df, cb_errors = fetch_gli_cb_fred(api_key=api_key)
                if cb_errors:
                    errors["cb_fred"] = cb_errors
                fx_df, fx_errors = fetch_gli_fx(api_key=api_key)
                if fx_errors:
                    errors["cb_fx"] = fx_errors
                try:
                    ecb = fetch_ecb_balance_sheet()
                    cb_df["ECB"] = ecb.reindex(cb_df.index, method="nearest")
                except Exception as e:
                    errors["ecb"] = str(e)
                _pboc_ok = False
                try:
                    pboc = fetch_pboc_balance_sheet()
                    cb_df["PBoC"] = pboc.reindex(cb_df.index, method="nearest")
                    _pboc_ok = True
                except Exception as e:
                    errors["pboc"] = str(e)

                cb_monthly = cb_df.resample("MS").last().ffill()
                fx_monthly = fx_df.resample("MS").last().ffill()
                cb_usd = convert_cb_to_usd(cb_monthly, fx_monthly)
                z_scores = {}
                for col in cb_usd.columns:
                    s = cb_usd[col].dropna()
                    if len(s) > 12:
                        z_scores[col] = compute_zscore_momentum(s)
                cb_series = []
                for date, row in cb_usd.iterrows():
                    entry = {"date": date.strftime("%Y-%m-%d")}
                    for col in cb_usd.columns:
                        entry[col] = row[col] if pd.notna(row[col]) else None
                    entry["total"] = sum(v for v in row.values if pd.notna(v))
                    cb_series.append(entry)
                latest_row = cb_usd.dropna(how="all").iloc[-1] if not cb_usd.empty else pd.Series()
                cb_summary = {}
                for col in cb_usd.columns:
                    val = latest_row.get(col)
                    cb_summary[col] = {
                        "usd_billions": float(val) if pd.notna(val) else None,
                        "momentum_score": z_scores.get(col, {}).get("momentum_score"),
                    }
                sine_wave = compute_howell_sine_wave(cb_usd.index)
                cb_result = {
                    "series": cb_series, "z_scores": z_scores,
                    "summary": cb_summary, "sine_wave": sine_wave,
                    "warnings": [] if _pboc_ok else ["PBoC: Data unavailable"],
                    "pboc_available": _pboc_ok,
                    "updated_at": datetime.now().isoformat(),
                }
                _cache["gli_cb_sheets"] = cb_result
                _save_gli_cache("cb", cb_result)
                results["cb"] = {
                    "status": "ok",
                    "banks": list(cb_usd.columns),
                    "records": len(cb_series),
                    "summary": cb_summary,
                }
            elif lyr == "bis":
                from .data.gli_fetcher import fetch_bis_credit
                from .models.gli_engine import interpolate_quarterly_to_monthly, compute_zscore_momentum, compute_diffusion_index

                bis_df, bis_errors = fetch_bis_credit()
                if bis_errors:
                    errors["bis_countries"] = bis_errors

                # Interpolate quarterly to monthly
                bis_monthly = interpolate_quarterly_to_monthly(bis_df)

                # Compute z-scores per country
                country_zscores = {}
                for col in bis_monthly.columns:
                    s = bis_monthly[col].dropna()
                    if len(s) > 24:
                        country_zscores[col] = compute_zscore_momentum(s, window=40)

                # Compute diffusion index
                diffusion = compute_diffusion_index(country_zscores)

                # Build time series
                bis_series = []
                for date, row in bis_monthly.iterrows():
                    entry = {"date": date.strftime("%Y-%m-%d")}
                    for col in bis_monthly.columns:
                        entry[col] = float(row[col]) if pd.notna(row[col]) else None
                    total = sum(v for v in row.values if pd.notna(v))
                    entry["total"] = total
                    bis_series.append(entry)

                # Summary with latest values
                latest_row = bis_monthly.dropna(how="all").iloc[-1] if not bis_monthly.empty else pd.Series()
                country_summary = {}
                for col in bis_monthly.columns:
                    val = latest_row.get(col)
                    country_summary[col] = {
                        "usd_billions": float(val) if pd.notna(val) else None,
                        "momentum_score": country_zscores.get(col, {}).get("momentum_score"),
                    }

                # Debt/liquidity ratio
                _debt_ratio = None
                try:
                    from .models.gli_engine import compute_debt_liquidity_ratio
                    from .data.gli_fetcher import fetch_bis_private_nf_credit
                    if "All reporting countries" in bis_monthly.columns:
                        _all = bis_monthly["All reporting countries"].dropna()
                        _pnf = fetch_bis_private_nf_credit()
                        _pnf.index = pd.to_datetime(_pnf.index)
                        _pnf_m = interpolate_quarterly_to_monthly(pd.DataFrame({"pnf": _pnf}))["pnf"].dropna()
                        if len(_all) > 0 and len(_pnf_m) > 0:
                            _pr = None
                            _fred = _cache.get("fred_data")
                            if _fred is not None and isinstance(_fred, pd.DataFrame):
                                for _rc in ["DFF", "FEDFUNDS"]:
                                    if _rc in _fred.columns:
                                        _pr = _fred[_rc].dropna()
                                        break
                            _hy = _yc = _m2 = None
                            if _fred is not None and isinstance(_fred, pd.DataFrame):
                                if "BAMLH0A0HYM2" in _fred.columns: _hy = _fred["BAMLH0A0HYM2"].dropna()
                                if "T10Y2Y" in _fred.columns: _yc = _fred["T10Y2Y"].dropna()
                                if "M2SL" in _fred.columns: _m2 = _fred["M2SL"].dropna()
                            _debt_ratio = compute_debt_liquidity_ratio(_all, _pnf_m, policy_rate=_pr, hy_spread=_hy, yield_curve=_yc, m2_supply=_m2)
                except Exception as _e:
                    print(f"[BIS POST] debt ratio error: {_e}")

                bis_result = {
                    "series": bis_series,
                    "z_scores": country_zscores,
                    "diffusion": diffusion,
                    "country_summary": country_summary,
                    "debt_ratio": _debt_ratio,
                    "updated_at": datetime.now().isoformat(),
                }
                _cache["gli_bis_credit"] = bis_result
                _save_gli_cache("bis", bis_result)
                results["bis"] = {
                    "status": "ok",
                    "countries": list(bis_monthly.columns),
                    "records": len(bis_series),
                }
        except Exception as e:
            errors[lyr] = str(e)
            results[lyr] = {"status": "error", "error": str(e)}

    return safe_json_response({
        "status": "ok",
        "layers": results,
        "errors": errors,
    })


# --- Serve built frontend as static files ---
_static_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
_assets_dir = _static_dir / "assets"

print(f"[STATIC] Looking for frontend at: {_static_dir}")
print(f"[STATIC] Exists: {_static_dir.exists()}")
if _static_dir.exists():
    print(f"[STATIC] Files: {list(_static_dir.iterdir())}")
    if _assets_dir.exists():
        print(f"[STATIC] Assets: {list(_assets_dir.iterdir())}")
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")
    else:
        print(f"[STATIC] WARNING: assets dir not found at {_assets_dir}")

    _no_cache = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the React SPA for any non-API route."""
        file_path = _static_dir / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_static_dir / "index.html"), headers=_no_cache)
else:
    print(f"[STATIC] WARNING: frontend dist not found at {_static_dir}")
    # Try alternate path for Render
    _alt_dir = Path("/opt/render/project/src/frontend/dist")
    if _alt_dir.exists():
        print(f"[STATIC] Found at alternate path: {_alt_dir}")
        _alt_assets = _alt_dir / "assets"
        if _alt_assets.exists():
            app.mount("/assets", StaticFiles(directory=str(_alt_assets)), name="assets")

        _no_cache_alt = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}

        @app.get("/{full_path:path}")
        async def serve_spa_alt(full_path: str):
            file_path = _alt_dir / full_path
            if file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(_alt_dir / "index.html"), headers=_no_cache_alt)
