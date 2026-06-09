"""FastAPI backend for the Macro Regime Dashboard."""

# ⚠️ IMPORTANT: Never use `if data and isinstance(data, ...)` when data might be a pandas DataFrame or Series.
# pandas objects throw ValueError on boolean evaluation. Always use `if data is not None and isinstance(data, ...)` instead.
# This has caused repeated 500 errors on /api/gli/component-detail.

import os
import json
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, Query, HTTPException, UploadFile, File, Request
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
from .data.tic_parser import load_tic_data, compute_tic_summary, apply_supplemental
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
    compute_single_stock_decomposition,
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
    "gli_prod_5f": None,
    "gli_prod_3fa_eq": None,
    "gli_prod_3fa": None,
    "gli_prod_4f": None,
    "gli_prod_2f": None,
    "gli_validation": None,
    "dollar_stress_swaps": None,
    "dollar_stress_index": None,
}

# ── Credit Quality Filter state ──────────────────────────────────────
_filter_state = {
    "enabled": os.getenv("GLI_FILTER_ENABLED", "true").lower() == "true",
    "toggle_history": [],
}


# ── Refresh health tracking ─────────────────────────────────────────
# Tracks whether each refresh cycle successfully recomputed all five
# production-signal variants. Surfaced via /api/health/refresh so the
# dashboard's HealthBanner can warn on silent staleness. This exists
# specifically because commit 8434e9c broke compute_production_signal
# silently — caches served pre-regression data with no visible warning.
_refresh_health = {
    "last_successful_refresh": None,
    "last_attempted_refresh": None,
    "last_refresh_status": "unknown",   # success | partial | failed | unknown
    "last_error": None,
    "consecutive_failures": 0,
    "last_5f_compute_at": None,
    "last_5f_data_current_as_of": None,
    "per_model_status": {
        m: {"last_success": None, "last_error": None, "status": "unknown"}
        for m in ("5f", "3fa_eq", "3fa", "4f", "2f")
    },
}


def _update_refresh_health_from_cache():
    """Inspect per-model caches and update _refresh_health in place.

    Called at the end of every refresh cycle. Classifies each model as
    success (cache has 'current', no 'error' key) or failed, then sets
    overall status:
        success = all 5 models ok
        partial = primary (5f) ok but one or more secondary failed
        failed  = primary (5f) not ok — dashboard will be serving stale
                  cached data from a previous refresh
    """
    from datetime import timezone as _tz
    now_iso = datetime.now(_tz.utc).isoformat()
    all_ok = True
    for m in ("5f", "3fa_eq", "3fa", "4f", "2f"):
        cached = _cache.get(f"gli_prod_{m}")
        is_ok = (
            isinstance(cached, dict)
            and "error" not in cached
            and "current" in cached
        )
        if is_ok:
            _refresh_health["per_model_status"][m] = {
                "last_success": now_iso,
                "last_error": None,
                "status": "success",
            }
            if m == "5f":
                _refresh_health["last_5f_compute_at"] = now_iso
                _refresh_health["last_5f_data_current_as_of"] = (
                    cached.get("current", {}).get("data_current_as_of")
                )
        else:
            all_ok = False
            err = cached.get("error") if isinstance(cached, dict) else None
            _refresh_health["per_model_status"][m]["status"] = "failed"
            _refresh_health["per_model_status"][m]["last_error"] = err or "No valid data"

    primary_ok = _refresh_health["per_model_status"]["5f"]["status"] == "success"
    if all_ok:
        _refresh_health["last_refresh_status"] = "success"
        _refresh_health["last_successful_refresh"] = now_iso
        _refresh_health["consecutive_failures"] = 0
        _refresh_health["last_error"] = None
    elif primary_ok:
        _refresh_health["last_refresh_status"] = "partial"
        _refresh_health["last_successful_refresh"] = now_iso
        _refresh_health["consecutive_failures"] = 0
    else:
        _refresh_health["last_refresh_status"] = "failed"
        _refresh_health["consecutive_failures"] += 1


def _classify_staleness(hours_since_success, consecutive_failures):
    """Staleness level per the alerting spec. Thresholds on time since
    the last successful 5F compute, escalated by consecutive failures."""
    if hours_since_success is None:
        return "critical", "No successful refresh recorded"
    if consecutive_failures >= 5 or hours_since_success > 24 * 7:
        return "critical", f"Signal is {hours_since_success/24:.1f} days old and {consecutive_failures} refreshes have failed"
    if consecutive_failures >= 2 or hours_since_success > 72:
        return "stale", f"Signal is {hours_since_success/24:.1f} days old"
    if hours_since_success > 24:
        return "aging", f"Signal is {hours_since_success:.1f} hours old"
    return "fresh", "Signal is current"


def _extract_hy_oas(fred):
    """Return HY OAS (BAMLH0A0HYM2) series from cache, handling both DataFrame and dict."""
    if fred is None:
        return None
    if isinstance(fred, pd.DataFrame):
        if "BAMLH0A0HYM2" in fred.columns:
            return fred["BAMLH0A0HYM2"].dropna()
        return None
    if isinstance(fred, dict):
        s = fred.get("BAMLH0A0HYM2")
        return s.dropna() if s is not None else None
    return None


def _build_source_freshness():
    """Return {factor_key: 'YYYY-MM-DD'} mapping each factor to its raw
    upstream last-observation date, computed BEFORE monthly resampling
    and BEFORE BIS cubic-spline interpolation.

    Used by compute_production_signal's freshness audit so the dashboard
    reports honest per-factor staleness (e.g. daily FRED series read
    ~1d stale, not 16d; BIS reads the real quarterly publication lag,
    not the interpolated-monthly ghost-freshness).

    Each lookup is wrapped in try/except — a missing cache key must
    never break the refresh cycle. Keys that can't be resolved are
    simply absent from the dict; the audit falls back to the resampled
    label for those.
    """
    sf = {}

    # Daily FRED factors — last date in the raw daily DataFrame column
    fred = _cache.get("fred_data")
    if isinstance(fred, pd.DataFrame):
        daily_map = {
            "rate_signal":   ["DFF", "FEDFUNDS"],
            "spread_signal": ["BAMLH0A0HYM2"],
            "m2_signal":     ["M2SL"],
        }
        for key, candidates in daily_map.items():
            for col in candidates:
                if col in fred.columns:
                    try:
                        last = fred[col].dropna().index[-1]
                        sf[key] = pd.Timestamp(last).strftime("%Y-%m-%d")
                    except Exception:
                        pass
                    break

    # Dollar stress — latest date across the six raw basis-swap pairs
    # (before build_dollar_stress_index resamples to month-start)
    raw_swaps = _cache.get("dollar_stress_swaps")
    if raw_swaps:
        try:
            candidates = []
            for ccy, series in raw_swaps.items():
                try:
                    v = series.dropna()
                    if len(v) > 0:
                        candidates.append(v.index[-1])
                except Exception:
                    continue
            if candidates:
                sf["dollar_stress_signal"] = pd.Timestamp(max(candidates)).strftime("%Y-%m-%d")
        except Exception:
            pass

    # quantity_signal (BIS) — the RAW quarterly observation date of the
    # credit ratio, not the cubic-spline-interpolated monthly. This is
    # the metric that has been masked as "fresh 16 days" when in reality
    # the underlying BIS quarterly publication is 9+ months old.
    # Stored as _cache["bis_raw_last_obs"] by the refresh path.
    bis_raw = _cache.get("bis_raw_last_obs")
    if bis_raw:
        try:
            sf["quantity_signal"] = pd.Timestamp(bis_raw).strftime("%Y-%m-%d")
        except Exception:
            pass

    return sf


def get_filter_enabled():
    """Check if credit quality filter is enabled."""
    return _filter_state["enabled"]


def set_filter_enabled(enabled, source="dashboard"):
    """Set filter state and log the change."""
    from datetime import timezone
    _filter_state["enabled"] = bool(enabled)
    _filter_state["toggle_history"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": "enabled" if enabled else "disabled",
        "source": source,
    })
    # Keep last 50 entries
    _filter_state["toggle_history"] = _filter_state["toggle_history"][-50:]


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


@app.get("/api/health/refresh")
async def health_refresh():
    """Refresh-health snapshot consumed by the dashboard HealthBanner.

    Returns the last refresh outcome, per-model status, and a classified
    staleness level so the UI can warn on silent backend failures. Must
    respond in <100ms — reads only from in-memory state, no recompute.
    """
    from datetime import timezone as _tz
    now = datetime.now(_tz.utc)

    last_success_iso = _refresh_health.get("last_successful_refresh")
    last_5f_iso = _refresh_health.get("last_5f_compute_at")
    hours_since = None
    # Prefer the 5F-specific timestamp for staleness — that's the signal
    # the trader is looking at, not the overall refresh timestamp.
    ref_iso = last_5f_iso or last_success_iso
    if ref_iso:
        try:
            ref_dt = datetime.fromisoformat(ref_iso.replace("Z", "+00:00"))
            if ref_dt.tzinfo is None:
                ref_dt = ref_dt.replace(tzinfo=_tz.utc)
            hours_since = (now - ref_dt).total_seconds() / 3600.0
        except Exception:
            hours_since = None

    staleness_level, staleness_message = _classify_staleness(
        hours_since, _refresh_health["consecutive_failures"],
    )

    # Overall status combines the last refresh outcome with staleness.
    # If the last refresh was successful but time has elapsed past the
    # aging threshold, escalate to stale/critical per staleness_level.
    refresh_status = _refresh_health["last_refresh_status"]
    if refresh_status == "success" and staleness_level in ("stale", "critical"):
        overall = staleness_level
    elif refresh_status == "failed":
        overall = staleness_level if staleness_level != "fresh" else "failed"
    else:
        overall = refresh_status  # success | partial | unknown

    return {
        "status": overall,
        "last_successful_refresh": last_success_iso,
        "hours_since_last_success": round(hours_since, 2) if hours_since is not None else None,
        "last_attempted_refresh": _refresh_health["last_attempted_refresh"],
        "consecutive_failures": _refresh_health["consecutive_failures"],
        "last_error": _refresh_health["last_error"],
        "signal_age_hours": round(hours_since, 2) if hours_since is not None else None,
        "signal_data_current_as_of": _refresh_health["last_5f_data_current_as_of"],
        "staleness_level": staleness_level,
        "staleness_message": staleness_message,
        "per_model_status": _refresh_health["per_model_status"],
        "now": now.isoformat(),
    }


# ── Credit Quality Filter endpoints ─────────────────────────────────

@app.api_route("/api/filter-toggle", methods=["POST"])
async def filter_toggle_post(request: Request):
    """Toggle the credit quality filter on/off."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    enabled = body.get("enabled", True)
    set_filter_enabled(bool(enabled), source="dashboard")
    print(f"[FILTER] Toggle: {'ENABLED' if enabled else 'DISABLED'}")
    return safe_json_response({
        "enabled": get_filter_enabled(),
        "updated_at": datetime.now().isoformat(),
    })


@app.get("/api/filter-toggle")
async def filter_toggle_get():
    """Get current filter toggle state."""
    return safe_json_response({
        "enabled": get_filter_enabled(),
    })


@app.get("/api/filter-status")
async def filter_status():
    """Return current filter state, metadata, and recent decisions."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from research.production_filter import get_filter_metadata

    # Compute current filter decision from cached data
    current_signal = None
    try:
        from research.production_filter import (
            apply_filter, compute_hy_oas_percentile, compute_hy_oas_3m_change,
        )
        import pandas as pd

        fred = _cache.get("fred_data")
        hy_oas_raw = _extract_hy_oas(fred)

        prod = _cache.get("gli_prod_5f")
        if prod and isinstance(prod, dict):
            ratio_series = prod.get("ratio_series", [])
            if ratio_series:
                last = ratio_series[-1]
                raw_q = last.get("quintile") or last.get("signal_quintile")
            else:
                raw_q = None
        else:
            raw_q = None

        if hy_oas_raw is not None and len(hy_oas_raw) > 3 and raw_q is not None:
            hy_monthly = hy_oas_raw.resample("MS").last().dropna()
            current_val = float(hy_monthly.iloc[-1])
            val_3m_ago = float(hy_monthly.iloc[-4]) if len(hy_monthly) >= 4 else current_val
            history = hy_monthly.iloc[-60:].values if len(hy_monthly) >= 60 else hy_monthly.values
            pctl = compute_hy_oas_percentile(current_val, history)
            chg_3m = compute_hy_oas_3m_change(current_val, val_3m_ago)
            fr = apply_filter(int(raw_q), pctl, chg_3m, get_filter_enabled())
            current_signal = {
                "raw_quintile": fr["raw_quintile"],
                "filtered_quintile": fr["filtered_quintile"],
                "filter_triggered": fr["filter_triggered"],
                "filter_reason": fr["filter_reason"],
                "hy_oas_current": round(current_val, 2),
                "hy_oas_percentile": fr["hy_oas_percentile"],
                "hy_oas_3m_change": fr["hy_oas_3m_change"],
            }
    except Exception as e:
        print(f"[FILTER-STATUS] Could not compute current signal: {e}")

    return safe_json_response({
        "enabled": get_filter_enabled(),
        "metadata": get_filter_metadata(),
        "current_signal": current_signal,
        "toggle_history": _filter_state.get("toggle_history", []),
    })


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
    from datetime import timezone as _tz
    _refresh_health["last_attempted_refresh"] = datetime.now(_tz.utc).isoformat()

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
                # Capture the TRUE BIS publication date (quarterly, pre-
                # interpolation) so the factor-freshness audit can report
                # real staleness rather than the cubic-spline-interpolated
                # monthly ghost date. Taking the older of the two series
                # since the ratio requires both. This is the single
                # source of truth for quantity_signal's real source date.
                try:
                    _bis_raw_last = min(private_nf.dropna().index[-1],
                                        bis_monthly.dropna(how="all").index[-1])
                    _cache["bis_raw_last_obs"] = _bis_raw_last.strftime("%Y-%m-%d")
                    print(f"[REFRESH] BIS raw quarterly last obs: {_cache['bis_raw_last_obs']}")
                except Exception as _bis_e:
                    print(f"[REFRESH] BIS raw-date capture failed: {_bis_e}")
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
                    # Fetch Dollar Stress from gist — cache raw swaps + index.
                    # Verbose diagnostics so operators can tell at-a-glance whether
                    # the gist was actually re-fetched this cycle or whether we're
                    # carrying forward an older cached value (the xccy basis gist
                    # is updated manually, so silent staleness is a real risk).
                    ds_series = None
                    prev_ds_index = _cache.get("dollar_stress_index")
                    prev_latest = None
                    if isinstance(prev_ds_index, pd.Series) and len(prev_ds_index) > 0:
                        try:
                            prev_latest = prev_ds_index.index[-1].strftime("%Y-%m-%d")
                        except Exception:
                            prev_latest = str(prev_ds_index.index[-1])
                    from datetime import timezone as _tz
                    ds_fetch_info = {
                        "attempted_at": datetime.now(_tz.utc).isoformat(),
                        "success": False,
                        "source": None,
                        "latest_obs_date": None,
                        "n_months": None,
                        "n_pairs": None,
                        "previous_latest_obs": prev_latest,
                        "unchanged_from_previous": None,
                        "error": None,
                    }
                    try:
                        from .data.dollar_stress import parse_basis_swaps, fetch_dollar_stress_gist, build_dollar_stress_index
                        gist_text = fetch_dollar_stress_gist()
                        raw_swaps = parse_basis_swaps(gist_text)
                        ds_series = build_dollar_stress_index(raw_swaps)
                        _cache["dollar_stress_swaps"] = raw_swaps
                        _cache["dollar_stress_index"] = ds_series
                        latest_str = ds_series.index[-1].strftime("%Y-%m-%d") if len(ds_series) > 0 else None
                        ds_fetch_info["success"] = True
                        ds_fetch_info["source"] = "gist"
                        ds_fetch_info["latest_obs_date"] = latest_str
                        ds_fetch_info["n_months"] = int(len(ds_series))
                        ds_fetch_info["n_pairs"] = int(len(raw_swaps)) if raw_swaps else None
                        unchanged = prev_latest is not None and latest_str == prev_latest
                        ds_fetch_info["unchanged_from_previous"] = unchanged
                        tag = "(UNCHANGED from previous refresh — gist not updated upstream)" if unchanged else (
                              f"(updated from previous latest {prev_latest})" if prev_latest else "(first refresh)")
                        print(f"[REFRESH] Dollar Stress: FETCHED OK from gist — {len(ds_series)} months, {len(raw_swaps)} pairs, latest obs {latest_str} {tag}")
                    except Exception as ds_e:
                        ds_fetch_info["success"] = False
                        ds_fetch_info["error"] = str(ds_e)
                        print(f"[REFRESH] Dollar Stress: FETCH FAILED — {ds_e}")
                        if isinstance(prev_ds_index, pd.Series) and prev_latest:
                            ds_series = prev_ds_index
                            ds_fetch_info["source"] = "cache_fallback"
                            ds_fetch_info["latest_obs_date"] = prev_latest
                            ds_fetch_info["n_months"] = int(len(prev_ds_index))
                            print(f"[REFRESH] Dollar Stress: falling back to previous cache (latest obs {prev_latest}) — THIS IS A STALE SIGNAL UNTIL NEXT SUCCESSFUL FETCH")
                        else:
                            print(f"[REFRESH] Dollar Stress: no cached fallback available — composite will be missing dollar_stress_signal this cycle")
                        import traceback as _tb; _tb.print_exc()
                    _cache["dollar_stress_fetch_info"] = ds_fetch_info
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
            "country_credit_df": bis_df,  # Raw quarterly DataFrame for Howell analysis
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

    # Cache production signals (4F and 2F) for instant serving
    try:
        from .models.backtest_engine import compute_production_signal
        import yfinance as yf
        spy_data = yf.download("SPY", start="2003-01-01", progress=False)
        if not spy_data.empty:
            spy_c = spy_data["Close"]
            if hasattr(spy_c, "droplevel") and spy_c.index.nlevels > 1:
                spy_c = spy_c.droplevel(1)
            if isinstance(spy_c, pd.DataFrame):
                spy_c = spy_c.iloc[:, 0]
            spy_m = spy_c.resample("MS").last().dropna()

            bis = _cache.get("gli_bis_credit") or {}
            # Defensive: dict.get(key, default) returns the stored value (including
            # None) when the key is present, so fall back to {} explicitly if the
            # stored debt_ratio is None (which happens when the ratio compute
            # crashed earlier in the refresh cycle).
            dr = (bis.get("debt_ratio") if isinstance(bis, dict) else None) or {}
            rs = dr.get("ratio_series", []) if isinstance(dr, dict) else []
            if len(rs) > 60:
                # Get VIX for vol scaling
                _vix = None
                _yahoo = _cache.get("yahoo_data")
                if _yahoo is not None and isinstance(_yahoo, pd.DataFrame) and "^VIX" in _yahoo.columns:
                    _vix = _yahoo["^VIX"].dropna()
                _fred_ref = _cache.get("fred_data")
                _hy_oas = _extract_hy_oas(_fred_ref)
                _src_fresh = _build_source_freshness()
                if _src_fresh:
                    print(f"[REFRESH] Source freshness map: {_src_fresh}")
                for model_key in ["5f", "3fa_eq", "3fa", "4f", "2f"]:
                    try:
                        prod = compute_production_signal(rs, spy_m, model=model_key, vix_data=_vix, hy_oas_data=_hy_oas, source_freshness=_src_fresh)
                        _cache[f"gli_prod_{model_key}"] = prod
                        print(f"[REFRESH] Production signal {model_key}: cached OK")
                    except Exception as pe:
                        print(f"[REFRESH] Production signal {model_key} error: {pe}")
    except Exception as e:
        print(f"[REFRESH] Production signal caching error: {e}")

    # Cache debt context (BIS advanced economy total credit)
    try:
        from .models.howell_liquidity import build_debt_numerator, get_debt_context
        debt, debt_err = build_debt_numerator()
        if debt is not None:
            # Get current GLI regime and M2 from cache
            prod_5f = _cache.get("gli_prod_5f")
            gli_regime = None
            if prod_5f and "current" in prod_5f:
                q = prod_5f["current"].get("level_quintile", 3)
                gli_regime = "BULLISH" if q <= 2 else "BEARISH" if q >= 4 else "NEUTRAL"
            # M2 from FRED cache
            m2_val = None
            fred = _cache.get("fred_data")
            if isinstance(fred, pd.DataFrame) and "M2SL" in fred.columns:
                m2_latest = fred["M2SL"].dropna()
                if len(m2_latest) > 0:
                    m2_val = float(m2_latest.iloc[-1]) / 1000  # billions → trillions
            ctx = get_debt_context(debt, gli_regime, m2_val)
            if ctx:
                _cache["debt_context"] = ctx
                print(f"[REFRESH] Debt context: ${ctx['ae_debt_T']}T, YoY={ctx['yoy_growth_pct']}%")
        else:
            print(f"[REFRESH] Debt context skipped: {debt_err}")
    except Exception as e:
        print(f"[REFRESH] Debt context error: {e}")

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

    # Update refresh health snapshot (per-model success/failure summary
    # for the /api/health/refresh endpoint and the dashboard banner).
    try:
        _update_refresh_health_from_cache()
        if errors:
            # Summarise the first fatal error so /api/health/refresh can
            # surface it directly in the banner.
            fatal = (errors.get("fred_fatal") or errors.get("yahoo_fatal")
                     or next((v for k, v in errors.items() if "error" in k.lower()), None))
            if fatal and _refresh_health["last_refresh_status"] != "success":
                _refresh_health["last_error"] = str(fatal)
    except Exception as _hh_e:
        print(f"[REFRESH] Health tracking update failed: {_hh_e}")

    return safe_json_response({
        "status": "ok",
        "last_refresh": _cache["last_refresh"],
        "fred_series_count": len(fred_df.columns) if not fred_df.empty else 0,
        "yahoo_series_count": len(yahoo_df.columns) if not yahoo_df.empty else 0,
        "gli": gli_status,
        "aligned": aligned_info,
        "errors": errors,
        "health": {
            "status": _refresh_health["last_refresh_status"],
            "consecutive_failures": _refresh_health["consecutive_failures"],
        },
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


# ── Reverse lookup: ticker → sector ──────────────────────────────────────────

def _detect_sector_for_ticker(ticker: str) -> tuple:
    """Try to detect which sector a ticker belongs to by checking sample holdings."""
    ticker_upper = ticker.upper()
    for sector_name in SECTOR_ETF_MAP:
        holdings = generate_sample_holdings(sector_name)
        if ticker_upper in holdings:
            etf = SECTOR_ETF_MAP[sector_name]
            return sector_name, etf
    # Default to SPY as both market and sector proxy
    return None, None


@app.get("/api/stock/lookup")
async def stock_lookup(
    ticker: str = Query(..., description="Stock ticker symbol"),
    lookback: int = Query(default=10, description="Lookback period in trading days"),
    benchmark: str = Query(default="SPY", description="Market benchmark ticker"),
):
    """Single-stock factor decomposition with historical daily contributions."""
    if _cache["yahoo_data"] is None:
        return safe_json_response({"cached": False, "message": "No data yet. Click Refresh to load."})

    yahoo_df = _cache["yahoo_data"]
    ticker_upper = ticker.upper().strip()

    # SPY (market benchmark)
    if benchmark not in yahoo_df.columns:
        raise HTTPException(status_code=400, detail=f"Benchmark {benchmark} data not available")
    spy = yahoo_df[benchmark].dropna()

    # Auto-detect sector
    detected_sector, detected_etf = _detect_sector_for_ticker(ticker_upper)

    # Determine sector ETF
    sector_etf_ticker = detected_etf
    if not sector_etf_ticker:
        # Fallback: try to find any sector ETF in cache
        for etf in SECTOR_ETF_MAP.values():
            if etf in yahoo_df.columns:
                sector_etf_ticker = etf
                break
    if not sector_etf_ticker or sector_etf_ticker not in yahoo_df.columns:
        sector_etf_ticker = "SPY"  # last resort

    sector_etf = yahoo_df[sector_etf_ticker].dropna()

    # Get stock prices
    if ticker_upper in yahoo_df.columns:
        stock_prices = yahoo_df[ticker_upper].dropna()
    else:
        # Generate synthetic data for demo
        np.random.seed(hash(ticker_upper) % 2**31)
        common = spy.index.intersection(sector_etf.index)
        spy_r = spy.reindex(common).pct_change().fillna(0)
        sec_r = sector_etf.reindex(common).pct_change().fillna(0)
        beta_mkt = np.random.uniform(0.8, 1.4)
        beta_sec = np.random.uniform(0.1, 0.5)
        noise = np.random.randn(len(common)) * 0.006
        stock_ret = beta_mkt * spy_r + beta_sec * (sec_r - spy_r) + noise
        stock_prices = ((1 + stock_ret).cumprod() * 100)
        stock_prices.name = ticker_upper

    result = compute_single_stock_decomposition(
        stock_prices=stock_prices,
        spy_prices=spy,
        sector_etf_prices=sector_etf,
        ticker=ticker_upper,
        lookback_days=lookback,
    )

    if "error" in result:
        return safe_json_response({"error": result["error"]})

    result["sector"] = detected_sector or "Unknown"
    result["sector_etf"] = sector_etf_ticker
    result["benchmark"] = benchmark
    result["lookback"] = lookback

    return safe_json_response(result)


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
    if cached is not None and cached.get('roe') is not None:
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
    tic = load_tic_data()
    if tic is None:
        raise HTTPException(status_code=400, detail="TIC data not available. Run fetch_tic.py first.")
    data = apply_supplemental(tic)

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
    # Exclude raw DataFrame from JSON response (kept in cache for Howell analysis)
    serializable = {k: v for k, v in data.items() if k != "country_credit_df"}
    return safe_json_response(serializable)


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


@app.api_route("/api/gli/run-validation", methods=["POST"])
async def run_validation(model: str = Query(default="all")):
    """Run validation for one model or all models. Caches results per model."""
    try:
        import yfinance as yf
        from .models.backtest_engine import run_signal_validation, PRODUCTION_MODELS

        bis_data = _cache.get("gli_bis_credit")
        if not bis_data or not bis_data.get("debt_ratio"):
            return safe_json_response({"error": "No BIS data. Click Refresh."})

        ratio_series = bis_data["debt_ratio"].get("ratio_series", [])
        spy = yf.download("SPY", start="2003-01-01", progress=False)
        if spy.empty:
            return safe_json_response({"error": "Failed to fetch SPY"})
        spy_close = spy["Close"]
        if hasattr(spy_close, "droplevel") and spy_close.index.nlevels > 1:
            spy_close = spy_close.droplevel(1)
        if isinstance(spy_close, pd.DataFrame):
            spy_close = spy_close.iloc[:, 0]
        spy_m = spy_close.resample("MS").last().dropna()

        # Log diagnostics
        from .data.dollar_stress import CURRENCY_WEIGHTS
        print(f"[VALIDATION] Currency weights: {CURRENCY_WEIGHTS}")

        # Get VIX for vol-scaled validation
        vix = None
        yahoo = _cache.get("yahoo_data")
        if yahoo is not None and isinstance(yahoo, pd.DataFrame) and "^VIX" in yahoo.columns:
            vix = yahoo["^VIX"].dropna()

        models_to_run = list(PRODUCTION_MODELS.keys()) if model == "all" else [model]
        all_results = {}
        model_summary = []

        for m in models_to_run:
            if m not in PRODUCTION_MODELS:
                continue
            print(f"[VALIDATION] Running model {m}...")
            try:
                _fred_df = _cache.get("fred_data") if isinstance(_cache.get("fred_data"), pd.DataFrame) else None
                result = run_signal_validation(ratio_series, spy_m, model=m, vix_data=vix, fred_data=_fred_df)
                all_results[m] = result
                # Summary row
                mc = result.get("monte_carlo", {})
                ec_m = result.get("equity_curve", {}).get("metrics", {})
                bs = result.get("bootstrap", {})
                ec_vs = result.get("equity_curve_vol_scaled", {})
                vs_m = ec_vs.get("metrics", {}) if ec_vs and "error" not in ec_vs else {}
                model_summary.append({
                    "model": m,
                    "mc_corr": mc.get("actual_corr"),
                    "p_value": mc.get("p_value"),
                    "sharpe_agg": ec_m.get("portfolio", {}).get("sharpe"),
                    "sortino_agg": ec_m.get("portfolio", {}).get("sortino"),
                    "sharpe_bh": ec_m.get("buyhold", {}).get("sharpe"),
                    "max_dd_agg": ec_m.get("portfolio", {}).get("max_drawdown"),
                    "max_dd_bh": ec_m.get("buyhold", {}).get("max_drawdown"),
                    "bootstrap_win": bs.get("outperformance_rate"),
                    "sharpe_vol_scaled": vs_m.get("portfolio", {}).get("sharpe"),
                    "sortino_vol_scaled": vs_m.get("portfolio", {}).get("sortino"),
                    "max_dd_vol_scaled": vs_m.get("portfolio", {}).get("max_drawdown"),
                    "calmar_vol_scaled": vs_m.get("portfolio", {}).get("calmar"),
                })
            except Exception as me:
                print(f"[VALIDATION] Model {m} failed: {me}")
                all_results[m] = {"error": str(me)}

        combined = {
            "models": all_results,
            "model_summary": model_summary,
            "default_model": model if model != "all" else "4f",
        }
        _cache["gli_validation"] = combined
        return safe_json_response(combined)
    except Exception as e:
        print(f"[VALIDATION] Error: {e}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/gli/signal-validation")
async def get_validation(model: str = Query(default=None)):
    """Serve cached validation results."""
    cached = _cache.get("gli_validation")
    if not cached:
        return safe_json_response({"error": "Run validation first (POST /api/gli/run-validation)"})
    # If specific model requested, return just that model's results
    if model and "models" in cached and model in cached["models"]:
        return safe_json_response(cached["models"][model])
    return safe_json_response(cached)


@app.api_route("/api/phase1-diagnostic", methods=["POST"])
async def phase1_diagnostic(force: str = Query(default="false")):
    """Run Phase 1 Q4/Q5 diagnostic. Cached for 24 hours unless force=true."""
    import traceback as tb

    force_refresh = force.lower() == "true"

    # Check cache (24h TTL) — skip if force refresh
    if not force_refresh:
        cached = _cache.get("phase1_diagnostic")
        if cached:
            cached_at = cached.get("summary", {}).get("generated_at", "")
            if cached_at:
                try:
                    from datetime import timezone
                    gen_time = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
                    age_hours = (datetime.now(timezone.utc) - gen_time).total_seconds() / 3600
                    if age_hours < 24:
                        cached["summary"]["from_cache"] = True
                        print(f"[PHASE1] Returning cached result ({age_hours:.1f}h old)")
                        return safe_json_response(cached)
                except Exception:
                    pass
    else:
        print("[PHASE1] Force refresh — clearing cache")
        _cache.pop("phase1_diagnostic", None)

    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from research.diagnostic_builder import run_diagnostic

        print("[PHASE1] Running diagnostic (cold)...")
        result = run_diagnostic(fred_api_key=FRED_API_KEY, use_cache=False)

        if "error" not in result:
            _cache["phase1_diagnostic"] = result
            print(f"[PHASE1] Done: {result['summary']['total_q4_q5_signals']} signals")
        else:
            print(f"[PHASE1] Error: {result['error']}")

        return safe_json_response(result)
    except Exception as e:
        print(f"[PHASE1] Exception: {e}")
        tb.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/phase1-diagnostic")
async def get_phase1_diagnostic():
    """Serve cached Phase 1 diagnostic results."""
    cached = _cache.get("phase1_diagnostic")
    if not cached:
        return safe_json_response({"error": "Run diagnostic first (POST /api/phase1-diagnostic)"})
    cached["summary"]["from_cache"] = True
    return safe_json_response(cached)


# ─── BIS Explorer ────────────────────────────────────────────────────────

import time as _time

def _bis_cache_get(group):
    """Return cached BIS group if < 24h old, else None."""
    entry = _cache.get(f"bis_explorer_{group}")
    if entry and (_time.time() - entry.get("_fetched_at", 0) < 86400):
        return entry["data"]
    return None


@app.get("/api/bis/{group}")
async def get_bis_group(group: str, force: str = Query(default="false")):
    """Fetch a BIS Explorer dataset group (credit/fx/property).

    On-demand with 24h in-memory cache. group ∈ {credit, fx, property}.
    """
    import traceback as tb

    if group not in ("credit", "fx", "property"):
        return safe_json_response({"error": f"Unknown group '{group}'"})

    if force.lower() != "true":
        cached = _bis_cache_get(group)
        if cached is not None:
            cached = dict(cached)
            cached["from_cache"] = True
            return safe_json_response(cached)

    try:
        from .data.bis_explorer import fetch_group
        print(f"[BIS-EXP] Fetching group '{group}'...")
        data = fetch_group(group)
        data["from_cache"] = False
        data["group"] = group
        _cache[f"bis_explorer_{group}"] = {"data": data, "_fetched_at": _time.time()}
        n = sum(len(v) for v in data.get("indicators", {}).values()) if "indicators" in data else 0
        print(f"[BIS-EXP] Group '{group}': {n} country-series across "
              f"{len(data.get('indicators', {}))} indicators")
        return safe_json_response(data)
    except Exception as e:
        print(f"[BIS-EXP] Error: {e}")
        tb.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.api_route("/api/phase2-analysis", methods=["POST"])
async def phase2_analysis(force: str = Query(default="false")):
    """Run Phase 2 filter analysis. Requires Phase 1 data. Cached 24h."""
    import traceback as tb

    force_refresh = force.lower() == "true"

    if not force_refresh:
        cached = _cache.get("phase2_analysis")
        if cached:
            cached_at = cached.get("generated_at", "")
            if cached_at:
                try:
                    from datetime import timezone
                    gen_time = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
                    age_hours = (datetime.now(timezone.utc) - gen_time).total_seconds() / 3600
                    if age_hours < 24:
                        cached["from_cache"] = True
                        print(f"[PHASE2] Returning cached result ({age_hours:.1f}h old)")
                        return safe_json_response(cached)
                except Exception:
                    pass
    else:
        _cache.pop("phase2_analysis", None)

    # Need Phase 1 result first
    p1 = _cache.get("phase1_diagnostic")
    if not p1 or "error" in p1:
        return safe_json_response({"error": "Run Phase 1 diagnostic first."})

    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from research.phase2_filter_analysis import run_phase2_analysis

        print("[PHASE2] Running filter analysis...")
        result = run_phase2_analysis(p1)

        if "error" not in result:
            _cache["phase2_analysis"] = result
            print(f"[PHASE2] Done. Winner: {result.get('winning_rule', '?')}")
        else:
            print(f"[PHASE2] Error: {result['error']}")

        return safe_json_response(result)
    except Exception as e:
        print(f"[PHASE2] Exception: {e}")
        tb.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/phase2-analysis")
async def get_phase2_analysis():
    """Serve cached Phase 2 analysis results."""
    cached = _cache.get("phase2_analysis")
    if not cached:
        return safe_json_response({"error": "Run Phase 2 analysis first (POST /api/phase2-analysis)"})
    cached["from_cache"] = True
    return safe_json_response(cached)


@app.api_route("/api/phase3-backtest", methods=["POST"])
async def phase3_backtest(force: str = Query(default="false")):
    """Run Phase 3 filtered signal backtest. Requires Phase 2 data. Cached 24h."""
    import traceback as tb

    force_refresh = force.lower() == "true"

    if not force_refresh:
        cached = _cache.get("phase3_backtest")
        if cached:
            cached_at = cached.get("summary", {}).get("generated_at", "")
            if cached_at:
                try:
                    from datetime import timezone
                    gen_time = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
                    age_hours = (datetime.now(timezone.utc) - gen_time).total_seconds() / 3600
                    if age_hours < 24:
                        cached["summary"]["from_cache"] = True
                        print(f"[PHASE3] Returning cached result ({age_hours:.1f}h old)")
                        return safe_json_response(cached)
                except Exception:
                    pass
    else:
        _cache.pop("phase3_backtest", None)

    # Need Phase 1 + Phase 2 results
    p1 = _cache.get("phase1_diagnostic")
    p2 = _cache.get("phase2_analysis")
    if not p2 or "error" in p2:
        return safe_json_response({"error": "Run Phase 2 analysis first."})

    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from research.phase3_backtest import run_phase3_backtest
        from research.data_loaders import build_gli_signal, fetch_fred_data, fetch_yf_data

        # Build GLI signal (uses app cache for ratio_series if available)
        print("[PHASE3] Building GLI signal...")
        fred_data = {}
        try:
            fred_data = fetch_fred_data()
        except Exception as e:
            print(f"[PHASE3] FRED fetch failed ({e}), trying without...")
        gli_data = build_gli_signal(fred_data)

        # SPY daily prices
        print("[PHASE3] Fetching SPY data...")
        yf_data = fetch_yf_data()
        spy_daily = yf_data.get("SPY")
        if spy_daily is None or len(spy_daily) < 100:
            return safe_json_response({"error": "Could not fetch SPY price data."})

        print("[PHASE3] Running Phase 3 + 3.5 backtest...")
        result = run_phase3_backtest(p2, gli_data, spy_daily, phase1_result=p1)

        if "error" not in result:
            _cache["phase3_backtest"] = result
            print(f"[PHASE3] Done. Recommendation: "
                  f"{result.get('recommendation', {}).get('recommended_rule', '?')}")
        else:
            print(f"[PHASE3] Error: {result['error']}")

        return safe_json_response(result)
    except Exception as e:
        print(f"[PHASE3] Exception: {e}")
        tb.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/phase3-backtest")
async def get_phase3_backtest():
    """Serve cached Phase 3 backtest results."""
    cached = _cache.get("phase3_backtest")
    if not cached:
        return safe_json_response({"error": "Run Phase 3 backtest first (POST /api/phase3-backtest)"})
    cached["summary"]["from_cache"] = True
    return safe_json_response(cached)


@app.api_route("/api/gli/run-regime-analysis", methods=["POST"])
async def run_regime_analysis_endpoint():
    """Run 2-regime and 3-regime analysis with Monte Carlo validation. Slow (~2-3 min)."""
    try:
        import yfinance as yf
        from .models.backtest_engine import run_regime_analysis

        bis_data = _cache.get("gli_bis_credit")
        if not bis_data or not bis_data.get("debt_ratio"):
            return safe_json_response({"error": "No BIS data. Click Refresh."})

        ratio_series = bis_data["debt_ratio"].get("ratio_series", [])
        spy = yf.download("SPY", start="2003-01-01", progress=False)
        if spy.empty:
            return safe_json_response({"error": "Failed to fetch SPY"})
        spy_close = spy["Close"]
        if hasattr(spy_close, "droplevel") and spy_close.index.nlevels > 1:
            spy_close = spy_close.droplevel(1)
        if isinstance(spy_close, pd.DataFrame):
            spy_close = spy_close.iloc[:, 0]
        spy_m = spy_close.resample("MS").last().dropna()

        # Get DGS10 from FRED cache
        fred = _cache.get("fred_data")
        if fred is None or not isinstance(fred, pd.DataFrame) or "DGS10" not in fred.columns:
            return safe_json_response({"error": "No DGS10 data. Click Refresh."})
        dgs10 = fred["DGS10"].dropna()
        dgs10_m = dgs10.resample("MS").last().dropna()

        # Get VIX for dynamic weight model
        vix_m = None
        yahoo = _cache.get("yahoo_data")
        if yahoo is not None and isinstance(yahoo, pd.DataFrame) and "^VIX" in yahoo.columns:
            vix_m = yahoo["^VIX"].dropna()

        result = run_regime_analysis(ratio_series, spy_m, dgs10_m, vix_monthly=vix_m)
        _cache["gli_regime_analysis"] = result
        return safe_json_response(result)
    except Exception as e:
        print(f"[REGIME] Error: {e}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/gli/regime-analysis")
async def get_regime_analysis():
    """Serve cached regime analysis results."""
    cached = _cache.get("gli_regime_analysis")
    if not cached:
        return safe_json_response({"error": "Run regime analysis first (POST /api/gli/run-regime-analysis)"})
    return safe_json_response(cached)


# ─── Model Improvement Study Endpoints ──────────────────────────────────────

@app.api_route("/api/gli/run-improvements", methods=["POST"])
async def run_improvements(track: str = Query(default="all")):
    """Run model improvement tracks. track=tail|proxy|timing|position|combination|all."""
    try:
        import yfinance as yf

        bis_data = _cache.get("gli_bis_credit")
        if not bis_data or not bis_data.get("debt_ratio"):
            return safe_json_response({"error": "No BIS data. Click Refresh."})
        ratio_series = bis_data["debt_ratio"].get("ratio_series", [])

        spy = yf.download("SPY", start="2003-01-01", progress=False)
        if spy.empty:
            return safe_json_response({"error": "Failed to fetch SPY"})
        spy_close = spy["Close"]
        if hasattr(spy_close, "droplevel") and spy_close.index.nlevels > 1:
            spy_close = spy_close.droplevel(1)
        if isinstance(spy_close, pd.DataFrame):
            spy_close = spy_close.iloc[:, 0]
        spy_m = spy_close.resample("MS").last().dropna()

        fred = _cache.get("fred_data")
        fred_df = fred if isinstance(fred, pd.DataFrame) else None
        vix = None
        yahoo = _cache.get("yahoo_data")
        if yahoo is not None and isinstance(yahoo, pd.DataFrame) and "^VIX" in yahoo.columns:
            vix = yahoo["^VIX"].dropna()

        results = _cache.get("gli_improvements") or {}

        if track in ("tail", "all"):
            from .models.gli_tail_analysis import run_tail_analysis
            results["tail"] = run_tail_analysis(ratio_series, spy_m)

        if track in ("proxy", "all") and fred_df is not None:
            from .models.gli_proxy_analysis import run_proxy_analysis
            results["proxy"] = run_proxy_analysis(ratio_series, spy_m, fred_df)

        if track in ("timing", "all"):
            from .models.gli_timing_analysis import run_timing_analysis
            results["timing"] = run_timing_analysis(ratio_series, spy_m, fred_data=fred_df)

        if track in ("position", "all"):
            from .models.gli_position_sizing import run_position_analysis
            results["position"] = run_position_analysis(ratio_series, spy_m, vix, fred_data=fred_df)

        if track in ("combination", "all"):
            from .models.gli_combination_methods import run_combination_analysis
            results["combination"] = run_combination_analysis(ratio_series, spy_m, fred_data=fred_df)

        if track in ("allocation", "all"):
            from .models.gli_allocation_optimizer import run_allocation_study
            results["allocation"] = run_allocation_study(ratio_series, spy_m, None, fred_df)

        if track in ("horizon", "all"):
            from .models.gli_horizon_analysis import run_horizon_analysis
            # Use Adj Close for total return (includes dividends)
            spy_adj = spy.get("Adj Close", spy["Close"])
            if hasattr(spy_adj, "droplevel") and spy_adj.index.nlevels > 1:
                spy_adj = spy_adj.droplevel(1)
            if isinstance(spy_adj, pd.DataFrame):
                spy_adj = spy_adj.iloc[:, 0]
            spy_adj_m = spy_adj.resample("MS").last().dropna()
            results["horizon"] = run_horizon_analysis(ratio_series, spy_adj_m, fred_df, None)

        if track in ("crash", "all"):
            from .models.gli_crash_robustness import run_crash_robustness
            results["crash"] = run_crash_robustness(ratio_series, spy_m)

        if track in ("crisis", "all"):
            from .models.gli_crisis_injection import run_crisis_injection
            results["crisis"] = run_crisis_injection(ratio_series, spy_m)

        if track in ("conviction", "all"):
            from .models.gli_conviction import run_conviction_analysis
            results["conviction"] = run_conviction_analysis(ratio_series, spy_m, vix, fred_data=fred_df)

        if track in ("probability", "all"):
            from .models.gli_crash_probability import run_crash_probability
            results["probability"] = run_crash_probability(ratio_series, spy_m, None, fred_df)

        if track in ("xsect", "all"):
            from .models.gli_cross_sectional import run_cross_sectional
            from .models.gli_cross_sectional_backtest import run_cross_sectional_backtest
            xsect_result = run_cross_sectional(ratio_series, spy_m, fred_df)
            results["xsect"] = xsect_result
            if xsect_result and "error" not in xsect_result:
                results["xsect_backtest"] = run_cross_sectional_backtest(
                    xsect_result, ratio_series, spy_m, fred_df)

        if track in ("realtime", "all"):
            from .models.gli_realtime_validation import run_realtime_validation
            results["realtime"] = run_realtime_validation(ratio_series, spy_m, vix, fred_data=fred_df)

        if track in ("validation", "all"):
            from .models.gli_validation_stack import run_validation_stack
            results["validation"] = run_validation_stack(ratio_series, spy_m, None, fred_df)

        _cache["gli_improvements"] = results
        return safe_json_response(results)
    except Exception as e:
        print(f"[IMPROVEMENTS] Error: {e}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/gli/debt-context")
async def get_debt_context_endpoint():
    """Get BIS advanced economy debt context (cached from REFRESH)."""
    cached = _cache.get("debt_context")
    if not cached:
        return safe_json_response({"error": "No debt context. Click REFRESH."})
    return safe_json_response(cached)


@app.get("/api/gli/improvements")
async def get_improvements():
    """Serve cached improvement study results."""
    cached = _cache.get("gli_improvements")
    if not cached:
        return safe_json_response({"error": "Run improvements first (POST /api/gli/run-improvements)"})
    return safe_json_response(cached)


@app.api_route("/api/gli/run-defensive-study", methods=["POST"])
async def run_defensive_study_endpoint():
    """Run full defensive rotation study. Slow (~2-3 min, downloads 17 tickers + MC)."""
    try:
        import yfinance as yf
        from .models.gli_defensive_integration import run_defensive_study

        bis_data = _cache.get("gli_bis_credit")
        if not bis_data or not bis_data.get("debt_ratio"):
            return safe_json_response({"error": "No BIS data. Click Refresh."})
        ratio_series = bis_data["debt_ratio"].get("ratio_series", [])

        spy = yf.download("SPY", start="2003-01-01", progress=False)
        if spy.empty:
            return safe_json_response({"error": "Failed to fetch SPY"})
        spy_close = spy["Close"]
        if hasattr(spy_close, "droplevel") and spy_close.index.nlevels > 1:
            spy_close = spy_close.droplevel(1)
        if isinstance(spy_close, pd.DataFrame):
            spy_close = spy_close.iloc[:, 0]
        spy_m = spy_close.resample("MS").last().dropna()

        fred = _cache.get("fred_data")
        fred_df = fred if isinstance(fred, pd.DataFrame) else None
        vix = None
        yahoo = _cache.get("yahoo_data")
        if yahoo is not None and isinstance(yahoo, pd.DataFrame) and "^VIX" in yahoo.columns:
            vix = yahoo["^VIX"].dropna()

        result = run_defensive_study(ratio_series, spy_m, fred_data=fred_df, vix_data=vix)
        _cache["gli_defensive"] = result
        return safe_json_response(result)
    except Exception as e:
        print(f"[DEFENSIVE] Error: {e}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/gli/defensive-study")
async def get_defensive_study():
    """Serve cached defensive rotation study results."""
    cached = _cache.get("gli_defensive")
    if not cached:
        return safe_json_response({"error": "Run defensive study first"})
    return safe_json_response(cached)


@app.get("/api/gli/optimize-currency-weights")
async def optimize_currency_weights_endpoint():
    """Optimize Dollar Stress currency weights against SPY 6M forward returns."""
    try:
        import yfinance as yf
        from .data.dollar_stress import optimize_currency_weights, parse_basis_swaps, fetch_dollar_stress_gist

        # Get raw swaps
        text = fetch_dollar_stress_gist()
        swaps = parse_basis_swaps(text)

        # Get SPY
        spy = yf.download("SPY", start="2003-01-01", progress=False)
        if spy.empty:
            return safe_json_response({"error": "Failed to fetch SPY"})
        spy_close = spy["Close"]
        if hasattr(spy_close, "droplevel") and spy_close.index.nlevels > 1:
            spy_close = spy_close.droplevel(1)
        if isinstance(spy_close, pd.DataFrame):
            spy_close = spy_close.iloc[:, 0]
        spy_m = spy_close.resample("MS").last().dropna()

        result = optimize_currency_weights(swaps, spy_m, signal_type="mom6")
        return safe_json_response(result)
    except Exception as e:
        print(f"[CCY OPT] Error: {e}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _enrich_with_filter(result):
    """Apply credit quality filter to a production signal result (in-place)."""
    if not isinstance(result, dict) or "current" not in result:
        return result
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from research.production_filter import (
            apply_filter, compute_hy_oas_percentile, compute_hy_oas_3m_change,
            get_filter_metadata, log_filter_decision,
        )

        fred = _cache.get("fred_data")
        hy_oas_raw = _extract_hy_oas(fred)

        current = result["current"]
        raw_q = current.get("level_quintile")

        if hy_oas_raw is not None and len(hy_oas_raw) > 3 and raw_q is not None:
            hy_monthly = hy_oas_raw.resample("MS").last().dropna()
            current_val = float(hy_monthly.iloc[-1])
            val_3m_ago = float(hy_monthly.iloc[-4]) if len(hy_monthly) >= 4 else current_val
            history = hy_monthly.iloc[-60:].values if len(hy_monthly) >= 60 else hy_monthly.values

            pctl = compute_hy_oas_percentile(current_val, history)
            chg_3m = compute_hy_oas_3m_change(current_val, val_3m_ago)

            fr = apply_filter(int(raw_q), pctl, chg_3m, get_filter_enabled())

            current["filtered_quintile"] = fr["filtered_quintile"]
            current["filter_triggered"] = fr["filter_triggered"]
            current["filter_reason"] = fr["filter_reason"]
            current["filter_enabled"] = fr["filter_enabled"]
            current["hy_oas_current"] = round(current_val, 2)
            current["hy_oas_percentile"] = fr["hy_oas_percentile"]
            current["hy_oas_3m_change"] = fr["hy_oas_3m_change"]

            log_filter_decision(
                current.get("date", "unknown"), raw_q, fr["filtered_quintile"],
                fr["filter_triggered"], fr["filter_reason"], pctl, chg_3m,
            )
        else:
            current["filtered_quintile"] = raw_q
            current["filter_triggered"] = False
            current["filter_reason"] = None
            current["filter_enabled"] = get_filter_enabled()

        result["filter_metadata"] = get_filter_metadata()

        # Backfill historical filter outputs on caches built before this feature
        if "quintile_context_filtered" not in result and "chart" in result:
            try:
                from research.production_filter import (
                    HY_OAS_PERCENTILE_THRESHOLD, HY_OAS_3M_CHANGE_THRESHOLD,
                    PERCENTILE_LOOKBACK_MONTHS, DOWNGRADE_FROM, DOWNGRADE_TO,
                )
                chart = result["chart"]
                if hy_oas_raw is not None and chart:
                    hy_m = hy_oas_raw.resample("MS").last().dropna()
                    n_trig = 0
                    for e in chart:
                        d = pd.Timestamp(e["date"])
                        hist = hy_m.loc[:d]
                        if len(hist) < 4:
                            e["filter_triggered"] = False
                            e["q_filtered"] = e.get("q")
                            e["comp_z_filtered"] = e.get("comp_z")
                            continue
                        cur = float(hist.iloc[-1])
                        chg = (cur - float(hist.iloc[-4])) * 100
                        window = hist.iloc[-PERCENTILE_LOOKBACK_MONTHS:]
                        pctl = float((window.values <= cur).sum() / len(window) * 100)
                        q_raw = e.get("q")
                        triggered = (pctl < HY_OAS_PERCENTILE_THRESHOLD
                                     and chg < HY_OAS_3M_CHANGE_THRESHOLD
                                     and q_raw is not None
                                     and (q_raw + 1) in DOWNGRADE_FROM)
                        e["filter_triggered"] = bool(triggered)
                        e["q_filtered"] = (DOWNGRADE_TO - 1) if triggered else q_raw
                        if triggered:
                            n_trig += 1
                        e["comp_z_filtered"] = e.get("comp_z")  # no cap without breakpoint
                    print(f"[FILTER] Backfill historical: {n_trig} triggers on {len(chart)} chart months")
            except Exception as be:
                print(f"[FILTER] Backfill error: {be}")
    except Exception as e:
        print(f"[FILTER] Enrichment error: {e}")
    return result


@app.get("/api/gli/production-signal")
async def get_production_signal(model: str = Query(default="5f")):
    """Get production composite signal — serve from cache if available."""
    # Serve from cache first (fast path)
    cached = _cache.get(f"gli_prod_{model}")
    if cached is not None and isinstance(cached, dict) and "current" in cached:
        return safe_json_response(_enrich_with_filter(cached))

    # Compute on demand if not cached
    try:
        import yfinance as yf
        from .models.backtest_engine import compute_production_signal

        bis_data = _cache.get("gli_bis_credit")
        if not bis_data or not bis_data.get("debt_ratio"):
            return safe_json_response({"cached": False, "message": "No BIS data. Click Refresh."})

        ratio_series = bis_data["debt_ratio"].get("ratio_series", [])
        spy = yf.download("SPY", start="2003-01-01", progress=False)
        if spy.empty:
            return safe_json_response({"error": "Failed to fetch SPY"})
        spy_close = spy["Close"]
        if hasattr(spy_close, "droplevel") and spy_close.index.nlevels > 1:
            spy_close = spy_close.droplevel(1)
        if isinstance(spy_close, pd.DataFrame):
            spy_close = spy_close.iloc[:, 0]
        spy_m = spy_close.resample("MS").last().dropna()

        # Get VIX for vol scaling
        vix = None
        yahoo = _cache.get("yahoo_data")
        if yahoo is not None and isinstance(yahoo, pd.DataFrame) and "^VIX" in yahoo.columns:
            vix = yahoo["^VIX"].dropna()

        fred_ref = _cache.get("fred_data")
        hy_oas_ref = _extract_hy_oas(fred_ref)
        src_fresh = _build_source_freshness()
        result = compute_production_signal(ratio_series, spy_m, model=model, vix_data=vix, hy_oas_data=hy_oas_ref, source_freshness=src_fresh)
        # Cache for future fast serving
        _cache[f"gli_prod_{model}"] = result
        return safe_json_response(_enrich_with_filter(result))
    except Exception as e:
        print(f"[PROD SIGNAL] Error: {e}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/gli/reoptimize")
async def reoptimize_weights(models: str = Query(default="3fa,4f,3fb,2f")):
    """Run sweep for specified models and return optimized weights.

    Call this after REFRESH to re-derive production weights when the
    underlying data (e.g. Dollar Stress parser) has changed.
    """
    try:
        import yfinance as yf
        from .models.backtest_engine import run_sweep, MODEL_CONFIGS, PRODUCTION_MODELS

        bis_data = _cache.get("gli_bis_credit")
        if not bis_data or not bis_data.get("debt_ratio"):
            return safe_json_response({"cached": False, "message": "No BIS data. Click Refresh first."})

        ratio_series = bis_data["debt_ratio"].get("ratio_series", [])
        if len(ratio_series) < 60:
            return safe_json_response({"error": "Not enough data for optimization"})

        spy = yf.download("SPY", start="2003-01-01", progress=False)
        if spy.empty:
            return safe_json_response({"error": "Failed to fetch SPY"})
        spy_close = spy["Close"]
        if hasattr(spy_close, "droplevel") and spy_close.index.nlevels > 1:
            spy_close = spy_close.droplevel(1)
        if isinstance(spy_close, pd.DataFrame):
            spy_close = spy_close.iloc[:, 0]
        spy_m = spy_close.resample("MS").last().dropna()

        model_list = [m.strip() for m in models.split(",") if m.strip() in MODEL_CONFIGS]
        results = {}

        for model_name in model_list:
            print(f"[REOPT] Running sweep for {model_name}...")
            sweep = run_sweep(ratio_series, spy_m, model=model_name)
            if "error" in sweep:
                results[model_name] = {"error": sweep["error"]}
                continue

            lb = sweep.get("leaderboard", [])
            # Find best config with walk-forward weights
            best = None
            for entry in lb[:10]:
                if entry.get("fw_fixed_weights"):
                    best = entry
                    break

            if best:
                results[model_name] = {
                    "signal": best["signal"],
                    "filter": best["filter"],
                    "oos_corr_6m": best.get("oos_corr_6m"),
                    "fw_fixed_mean": best.get("fw_fixed_mean"),
                    "fw_fixed_std": best.get("fw_fixed_std"),
                    "n": best.get("n"),
                    "optimized_weights": best["fw_fixed_weights"],
                    "spread_6m": best.get("spread_6m"),
                    "monotonicity": best.get("monotonicity"),
                }
                # Also show current production weights for comparison
                if model_name in PRODUCTION_MODELS:
                    results[model_name]["current_weights"] = PRODUCTION_MODELS[model_name]["weights"]
            else:
                results[model_name] = {"error": "No config produced walk-forward weights"}

        return safe_json_response({
            "models": results,
            "note": "Update PRODUCTION_MODELS in backtest_engine.py with optimized_weights, then restart.",
        })
    except Exception as e:
        print(f"[REOPT] Error: {e}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/gli/component-detail")
async def get_component_detail():
    """Return detailed basis swap + HY OAS data for the Component Detail panel."""
    try:
        return await _get_component_detail_impl()
    except Exception as e:
        import traceback as tb
        return safe_json_response({"error": str(e), "traceback": tb.format_exc()})

async def _get_component_detail_impl():
    from .data.dollar_stress import CURRENCY_WEIGHTS, CURRENCIES, chain_link_pairs

    result = {"basis_swaps": {}, "dollar_stress_index": [], "hy_oas": {}, "alert": {}}

    # ── 1. Basis Swaps ──────────────────────────────────────────────────────
    raw_swaps = _cache.get("dollar_stress_swaps")
    ds_index = _cache.get("dollar_stress_index")

    # If cache is empty, try fetching on-demand
    if not raw_swaps:
        try:
            from .data.dollar_stress import fetch_dollar_stress_gist, parse_basis_swaps, build_dollar_stress_index
            gist_text = fetch_dollar_stress_gist()
            raw_swaps = parse_basis_swaps(gist_text)
            ds_index = build_dollar_stress_index(raw_swaps)
            _cache["dollar_stress_swaps"] = raw_swaps
            _cache["dollar_stress_index"] = ds_index
            print(f"[COMPONENT-DETAIL] On-demand dollar stress fetch: {len(raw_swaps)} pairs, {len(ds_index)} months")
        except Exception as e:
            print(f"[COMPONENT-DETAIL] On-demand dollar stress fetch failed: {e}")
            import traceback as _tb; _tb.print_exc()

    if raw_swaps:
        pairs_data = []
        for ccy in CURRENCIES:
            s = raw_swaps.get(ccy)
            if s is None or len(s) < 2:
                continue

            # Handle both list-of-dicts format and pandas Series
            if isinstance(s, list):
                valid = [p for p in s if p.get("value") is not None]
                if len(valid) < 2:
                    continue
                current = float(valid[-1]["value"])
                def _chg(n):
                    if len(valid) > n:
                        return round(float(valid[-1]["value"] - valid[-1 - n]["value"]), 1)
                    return None
            else:
                current = float(s.iloc[-1])
                def _chg(n):
                    if len(s) > n:
                        return round(float(s.iloc[-1] - s.iloc[-1 - n]), 1)
                    return None

            chg_1w = _chg(1)   # weekly data, so 1 obs = ~1 week
            chg_1m = _chg(4)
            chg_3m = _chg(13)
            chg_6m = _chg(26)

            # Trend: based on 3M change (structural funding metric, not trading signal)
            # Positive 3M change = basis less negative = loosening
            # Negative 3M change = basis more negative = tightening
            if chg_3m is not None:
                if chg_3m > 1:
                    trend = "loosening"
                elif chg_3m < -1:
                    trend = "tightening"
                else:
                    trend = "stable"
            else:
                trend = "unknown"

            # Stress level: percentile rank of current value vs pair's full history
            # More negative = more stress, so rank by how extreme the current level is
            linked = chain_link_pairs(raw_swaps)
            hist = linked.get(ccy)
            if hist is not None and len(hist.dropna()) > 12:
                h = hist.dropna()
                # % of history where basis was LESS negative (higher) than current
                # High percentile = current is unusually negative = high stress
                pct = float((h > current).mean() * 100)
                if pct < 25:
                    stress = "LOW"
                elif pct < 50:
                    stress = "MODERATE"
                elif pct < 75:
                    stress = "ELEVATED"
                else:
                    stress = "HIGH"
            else:
                stress = "LOW"

            pairs_data.append({
                "pair": ccy,
                "current": round(current, 1),
                "chg_1w": chg_1w,
                "chg_1m": chg_1m,
                "chg_3m": chg_3m,
                "chg_6m": chg_6m,
                "trend": trend,
                "stress": stress,
                "weight": CURRENCY_WEIGHTS[ccy],
            })

        # Historical time series — use raw weekly data for charts
        pairs_history = []
        if raw_swaps:
            all_dates_set = set()
            for ccy in CURRENCIES:
                s = raw_swaps.get(ccy)
                if s is None:
                    continue
                if isinstance(s, list):
                    for p in s:
                        if p.get("value") is not None:
                            all_dates_set.add(p["date"])
                else:
                    # pandas Series
                    for dt in s.dropna().index:
                        all_dates_set.add(dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt))
            last_known = {ccy: None for ccy in CURRENCIES}
            for dt_str in sorted(all_dates_set):
                entry = {"date": dt_str}
                for ccy in CURRENCIES:
                    s = raw_swaps.get(ccy)
                    if s is None:
                        entry[ccy] = last_known[ccy]
                        continue
                    val = None
                    if isinstance(s, list):
                        match = next((p for p in s if p["date"] == dt_str and p.get("value") is not None), None)
                        if match:
                            val = round(float(match["value"]), 1)
                    else:
                        try:
                            ts = pd.Timestamp(dt_str)
                            if ts in s.index and pd.notna(s[ts]):
                                val = round(float(s[ts]), 1)
                        except (ValueError, KeyError):
                            pass
                    if val is not None:
                        last_known[ccy] = val
                    entry[ccy] = last_known[ccy]  # forward-fill from last known
                pairs_history.append(entry)

        result["basis_swaps"] = {
            "pairs": pairs_data,
            "history": pairs_history,
        }

    # Dollar Stress Index time series
    if ds_index is not None and len(ds_index) > 0:
        # Handle both list-of-dicts and pandas Series formats
        if isinstance(ds_index, list):
            ds_history = [{"date": p["date"], "value": round(float(p["value"]), 2)} for p in ds_index if p.get("value") is not None]
            latest_ds = float(ds_index[-1]["value"]) if ds_index[-1].get("value") is not None else 0
            prev_ds = float(ds_index[-2]["value"]) if len(ds_index) > 1 and ds_index[-2].get("value") is not None else latest_ds
        else:
            ds_history = [{"date": dt.strftime("%Y-%m-%d"), "value": round(float(val), 2)} for dt, val in ds_index.items()]
            latest_ds = float(ds_index.iloc[-1])
            prev_ds = float(ds_index.iloc[-2]) if len(ds_index) > 1 else latest_ds
        result["dollar_stress_index"] = {
            "history": ds_history,
            "current": round(latest_ds, 2),
            "direction": "loosening" if latest_ds < prev_ds else "tightening",
        }

    # ── 2. HY OAS ───────────────────────────────────────────────────────────
    fred = _cache.get("fred_data")
    if fred is not None and isinstance(fred, pd.DataFrame) and "BAMLH0A0HYM2" in fred.columns:
        hy = fred["BAMLH0A0HYM2"].dropna() * 100  # FRED reports in %, convert to basis points
        if len(hy) > 0:
            current_hy = float(hy.iloc[-1])

            def _hy_chg(days):
                if len(hy) > days:
                    return round(float(hy.iloc[-1] - hy.iloc[-1 - days]), 0)
                return None

            # 52-week high/low
            hy_1y = hy.iloc[-252:] if len(hy) > 252 else hy
            hy_5y = hy.iloc[-1260:] if len(hy) > 1260 else hy

            # Percentile (5Y)
            pct_5y = float((hy_5y < current_hy).mean() * 100) if len(hy_5y) > 20 else None

            # Time series (last 5 years for chart)
            hy_chart = []
            for dt, val in hy.iloc[-1260:].items():
                hy_chart.append({
                    "date": dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt),
                    "value": round(float(val), 0),
                })

            result["hy_oas"] = {
                "current": round(current_hy, 0),
                "chg_1w": _hy_chg(5),
                "chg_1m": _hy_chg(21),
                "chg_3m": _hy_chg(63),
                "chg_6m": _hy_chg(126),
                "high_52w": round(float(hy_1y.max()), 0),
                "low_52w": round(float(hy_1y.min()), 0),
                "percentile_5y": round(pct_5y, 0) if pct_5y is not None else None,
                "history": hy_chart,
            }

    # ── 3. Alert Status ──────────────────────────────────────────────────────
    pairs = result["basis_swaps"].get("pairs", [])
    ds_info = result.get("dollar_stress_index", {})
    hy_info = result.get("hy_oas", {})

    # Dollar funding alert: percentile of Dollar Stress Index vs full history
    avg_basis = np.mean([p["current"] for p in pairs]) if pairs else 0
    ds_idx_raw = _cache.get("dollar_stress_index")
    if ds_idx_raw is not None and hasattr(ds_idx_raw, 'iloc') and len(ds_idx_raw) > 12:
        ds_current = float(ds_idx_raw.iloc[-1])
        ds_pct = float((ds_idx_raw.dropna() < ds_current).mean() * 100)
        if ds_pct < 25:
            dollar_alert = {"level": "LOW", "color": "green"}
        elif ds_pct < 50:
            dollar_alert = {"level": "MODERATE", "color": "amber"}
        elif ds_pct < 75:
            dollar_alert = {"level": "ELEVATED", "color": "amber"}
        else:
            dollar_alert = {"level": "HIGH", "color": "red"}
    else:
        avg_basis = np.mean([p["current"] for p in pairs]) if pairs else 0
        dollar_alert = {"level": "LOW" if avg_basis > -15 else "ELEVATED" if avg_basis > -35 else "HIGH", "color": "green" if avg_basis > -15 else "amber" if avg_basis > -35 else "red"}

    # Credit alert
    hy_current = hy_info.get("current", 0)
    if hy_current < 400:
        credit_alert = {"level": "LOW", "color": "green"}
    elif hy_current < 500:
        credit_alert = {"level": "ELEVATED", "color": "amber"}
    elif hy_current < 700:
        credit_alert = {"level": "HIGH", "color": "red"}
    else:
        credit_alert = {"level": "CRISIS", "color": "red"}

    # Generate alert text
    alert_parts = []
    widening = [p for p in pairs if p.get("trend") == "tightening"]
    loosening = [p for p in pairs if p.get("trend") == "loosening"]
    if widening:
        names = ", ".join(p["pair"] for p in widening)
        alert_parts.append(f"{names} basis tightening — monitor for dollar stress contagion.")
    if loosening and not widening:
        alert_parts.append("All basis swaps loosening or stable.")
    if hy_current > 500:
        alert_parts.append(f"HY OAS at {hy_current:.0f}bp — elevated credit stress.")
    elif hy_current > 400:
        alert_parts.append(f"HY OAS at {hy_current:.0f}bp — modestly elevated but not alarming.")
    else:
        alert_parts.append("HY spreads contained. No immediate credit deterioration.")
    if not alert_parts:
        alert_parts.append("All clear. Dollar funding and credit conditions both stable.")

    result["alert"] = {
        "dollar_funding": dollar_alert,
        "credit": credit_alert,
        "text": " ".join(alert_parts),
        "avg_basis": round(avg_basis, 1),
        "hy_current": hy_current,
    }

    return safe_json_response(result)


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
