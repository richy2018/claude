"""Data loaders for GLI Signal Filter Research.

Fetches all required data:
  - GLI quintile signal (via full backend pipeline)
  - SPY price/returns (yfinance)
  - FRED macro series (fredapi or direct HTTP)
  - VIX, DXY (yfinance)

Supports two modes:
  1. Direct: Fetches from FRED/yfinance/BIS directly (needs network + API keys)
  2. API: Fetches from running Render backend (needs RENDER_URL env var)
"""

import sys
import os
import numpy as np
import pandas as pd

# Add backend to path for importing existing modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from research.config import FRED_API_KEY, FRED_SERIES as RESEARCH_FRED, START_DATE

# Render backend URL for API-based fallback
RENDER_URL = os.environ.get("RENDER_URL", "")


# ---------------------------------------------------------------------------
# FRED data
# ---------------------------------------------------------------------------

def _fetch_fred_http(series_id, api_key, start_date=START_DATE):
    """Fetch a single FRED series via HTTP API."""
    import requests
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
        "sort_order": "asc",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    obs = resp.json().get("observations", [])
    if not obs:
        return pd.Series(dtype=float, name=series_id)
    df = pd.DataFrame(obs)
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    s = df.set_index("date")["value"].dropna()
    s.name = series_id
    return s


def fetch_fred_data(api_key=None):
    """Fetch all FRED series needed for macro context + GLI signal.

    Returns dict of {series_id: pd.Series}.
    """
    key = api_key or FRED_API_KEY
    if not key:
        raise ValueError(
            "FRED_API_KEY required. Set via environment variable or pass directly.\n"
            "Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html"
        )

    # Merge research-specific series with GLI pipeline needs
    all_series = dict(RESEARCH_FRED)
    # GLI pipeline also needs these
    for sid in ["DFF", "FEDFUNDS", "BAMLH0A0HYM2", "T10Y2Y", "M2SL"]:
        all_series.setdefault(sid, sid)

    results = {}
    for sid in all_series:
        try:
            s = _fetch_fred_http(sid, key)
            results[sid] = s
            print(f"  [FRED] {sid}: {len(s)} obs, "
                  f"{s.index[0].strftime('%Y-%m')} to {s.index[-1].strftime('%Y-%m')}")
        except Exception as e:
            print(f"  [FRED] {sid}: FAILED ({e})")

    return results


# ---------------------------------------------------------------------------
# yfinance data
# ---------------------------------------------------------------------------

def fetch_yf_data():
    """Fetch SPY, VIX, DXY from yfinance.

    Returns dict of {ticker: pd.Series} with daily close prices.
    """
    import yfinance as yf
    results = {}

    for ticker, desc in [("SPY", "S&P 500 ETF"), ("^VIX", "VIX"), ("DX-Y.NYB", "DXY")]:
        try:
            df = yf.download(ticker, start=START_DATE, progress=False)
            # Handle MultiIndex columns from newer yfinance
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            col = "Adj Close" if "Adj Close" in df.columns else "Close"
            s = df[col].dropna()
            s.name = ticker
            # Flatten index timezone if present
            if hasattr(s.index, 'tz') and s.index.tz is not None:
                s.index = s.index.tz_localize(None)
            results[ticker] = s
            print(f"  [YF] {ticker} ({desc}): {len(s)} obs, "
                  f"{s.index[0].strftime('%Y-%m')} to {s.index[-1].strftime('%Y-%m')}")
        except Exception as e:
            print(f"  [YF] {ticker}: FAILED ({e})")

    return results


# ---------------------------------------------------------------------------
# Earnings data (multpl.com scraper + FRED CORPPROF fallback)
# ---------------------------------------------------------------------------

def fetch_earnings_data():
    """Unified earnings loader: try multpl.com, fallback to FRED CP.

    Returns (pd.Series, source_name) or (None, None) on failure.
    """
    # Try 1: multpl.com scraping
    try:
        import requests
        from bs4 import BeautifulSoup

        url = "https://www.multpl.com/s-p-500-earnings/table/by-quarter"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; Research/1.0)"}
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.content, "html.parser")
        table = soup.find("table", id="datatable")
        if table:
            rows = []
            for tr in table.find_all("tr")[1:]:
                cells = tr.find_all("td")
                if len(cells) >= 2:
                    date_str = cells[0].text.strip()
                    val_str = cells[1].text.strip().replace("$", "").replace(",", "")
                    try:
                        dt = pd.to_datetime(date_str)
                        val = float(val_str)
                        rows.append((dt, val))
                    except (ValueError, TypeError):
                        continue
            if len(rows) > 50:
                s = pd.DataFrame(rows, columns=["date", "eps"]).set_index("date")["eps"]
                s = s.sort_index().resample("MS").last().ffill()
                s.name = "sp500_eps_ttm"
                print(f"  [EARNINGS] multpl.com: {len(s)} obs, "
                      f"{s.index[0].strftime('%Y-%m')} to {s.index[-1].strftime('%Y-%m')}")
                return s, "sp500_eps_ttm"
    except Exception as e:
        print(f"  [EARNINGS] multpl.com failed: {e}")

    # Try 2: FRED CP (Corporate Profits) as proxy
    # Already fetched in the main FRED loop — caller can extract from fred_data
    print("  [EARNINGS] Will use FRED CP (corporate profits) as proxy")
    return None, "corporate_profits_proxy"


# ---------------------------------------------------------------------------
# GLI quintile signal
# ---------------------------------------------------------------------------

def build_gli_signal(fred_data):
    """Build the full GLI 5F production signal and quintile series.

    When running inside the backend process (Render), reads ratio_series
    from the app's in-memory cache. When running standalone, fetches
    BIS credit + FRED + Dollar Stress and builds from scratch.

    Args:
        fred_data: dict of {series_id: pd.Series} from fetch_fred_data()

    Returns:
        dict with keys:
          - 'signal': pd.Series (mom6 transformed composite)
          - 'composite': pd.Series (raw composite level)
          - 'quintiles': pd.Series (1-5, expanding window)
          - 'ratio_series': list of dicts (for debugging)
    """
    print("\n[GLI] Building 5F production signal...")

    ratio_series = None

    # Try 1: Read from the running app's cache (when called from FastAPI)
    # Try multiple import paths since this module can be called from different contexts
    for import_path in ["backend.main", "main"]:
        try:
            mod = __import__(import_path, fromlist=["_cache"])
            app_cache = getattr(mod, "_cache", None)
            if app_cache:
                bis_data = app_cache.get("gli_bis_credit")
                if bis_data and isinstance(bis_data, dict):
                    rs = bis_data.get("debt_ratio", {}).get("ratio_series", [])
                    if len(rs) > 60:
                        ratio_series = rs
                        print(f"  [GLI] Using cached ratio_series: {len(rs)} months")
                        break
        except Exception:
            continue

    # Try 2: Build from scratch using backend modules directly
    if ratio_series is None:
        try:
            # These imports use relative imports within the backend package,
            # so they only work when backend/ is properly on sys.path as a package
            from data.gli_fetcher import fetch_bis_credit, fetch_bis_private_nf_credit
            from models.gli_engine import (
                interpolate_quarterly_to_monthly, compute_debt_liquidity_ratio,
            )
            from data.dollar_stress import (
                fetch_dollar_stress_gist, parse_basis_swaps, build_dollar_stress_index,
            )

            print("  [GLI] Fetching BIS credit data...")
            bis_raw, bis_errors = fetch_bis_credit()
            bis_monthly = bis_raw.resample("MS").last().ffill()

            if "All reporting countries" not in bis_monthly.columns:
                raise RuntimeError(f"BIS 'All reporting countries' not found")
            all_sector = bis_monthly["All reporting countries"].dropna()

            private_nf = fetch_bis_private_nf_credit()
            private_nf.index = pd.to_datetime(private_nf.index)
            private_nf_monthly = interpolate_quarterly_to_monthly(
                pd.DataFrame({"pnf": private_nf})
            )["pnf"].dropna()

            policy_rate = fred_data.get("DFF") or fred_data.get("FEDFUNDS")
            hy_spread = fred_data.get("BAMLH0A0HYM2")
            yield_curve = fred_data.get("T10Y2Y")
            m2_supply = fred_data.get("M2SL")

            print("  [GLI] Fetching Dollar Stress...")
            gist_text = fetch_dollar_stress_gist()
            raw_swaps = parse_basis_swaps(gist_text)
            ds_series = build_dollar_stress_index(raw_swaps)

            print("  [GLI] Computing debt/liquidity ratio...")
            result = compute_debt_liquidity_ratio(
                all_sector, private_nf_monthly,
                policy_rate=policy_rate, hy_spread=hy_spread,
                yield_curve=yield_curve, m2_supply=m2_supply,
                dollar_stress=ds_series,
            )
            ratio_series = result.get("ratio_series", [])
        except ImportError as e:
            raise RuntimeError(
                f"Cannot build GLI signal: backend imports failed ({e}). "
                "Run REFRESH first so cached data is available, or use API mode."
            )

    if not ratio_series or len(ratio_series) < 60:
        raise RuntimeError(f"Not enough ratio_series data: {len(ratio_series) if ratio_series else 0}")

    print(f"  [GLI] Ratio series: {len(ratio_series)} months")

    # Build 5F composite and mom6 signal
    from research.config import GLI_5F_KEYS, GLI_5F_WEIGHTS

    components = {}
    all_keys = list(set(["quantity_signal", "rate_signal", "spread_signal",
                         "curve_signal", "m2_signal", "dollar_stress_signal"]))
    for key in all_keys:
        s = pd.Series(
            {pd.Timestamp(r["date"]): r.get(key) for r in ratio_series},
            dtype=float).dropna().sort_index()
        if len(s) > 0:
            components[key] = s

    missing = [k for k in GLI_5F_KEYS if k not in components]
    if missing:
        raise RuntimeError(f"Missing GLI components: {missing}")

    # Intersection of all component dates
    date_sets = [set(components[k].dropna().index) for k in GLI_5F_KEYS]
    common_dates = sorted(set.intersection(*date_sets))
    base_idx = pd.DatetimeIndex(common_dates)

    composite = pd.Series(0.0, index=base_idx)
    for k in GLI_5F_KEYS:
        composite += GLI_5F_WEIGHTS[k] * components[k].reindex(base_idx, method="ffill").fillna(0)

    # Mom6 transformation
    signal = composite.diff(6).dropna()
    print(f"  [GLI] Composite: {len(composite)} pts, Signal (mom6): {len(signal)} pts")
    print(f"  [GLI] Signal range: {signal.index[0].strftime('%Y-%m')} to {signal.index[-1].strftime('%Y-%m')}")

    # Step 6: Expanding-window quintiles (no look-ahead)
    # For each month t, quintile is based on percentile of signal[t] within signal[:t]
    min_window = 36  # 3 years warmup — balance between stable quintile
                     # boundaries and sample coverage (captures 2003+)
    quintiles = pd.Series(np.nan, index=signal.index, dtype=float)

    for i in range(min_window, len(signal)):
        history = signal.iloc[:i+1].values
        current = signal.iloc[i]
        pct = float((history < current).sum()) / len(history) * 100
        q = 1 if pct < 20 else 2 if pct < 40 else 3 if pct < 60 else 4 if pct < 80 else 5
        quintiles.iloc[i] = q

    quintiles = quintiles.dropna().astype(int)
    print(f"  [GLI] Quintiles: {len(quintiles)} months (after {min_window}-month warmup)")
    print(f"  [GLI] Quintile distribution: {dict(quintiles.value_counts().sort_index())}")

    return {
        "signal": signal,
        "composite": composite,
        "quintiles": quintiles,
        "ratio_series": ratio_series,
        "components": components,
    }


# ---------------------------------------------------------------------------
# API-based fallback (fetches from running Render backend)
# ---------------------------------------------------------------------------

def _api_get(path):
    """GET from Render backend API."""
    import requests
    url = f"{RENDER_URL}{path}"
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return resp.json()


def _api_post(path):
    """POST to Render backend API."""
    import requests
    url = f"{RENDER_URL}{path}"
    resp = requests.post(url, timeout=300)
    resp.raise_for_status()
    return resp.json()


def fetch_fred_data_via_api():
    """Fetch FRED data from the Render backend's cached data.

    Returns dict of {series_id: pd.Series}.
    """
    print("  [API] Fetching FRED data from backend...")
    data = _api_get("/api/data/fred")

    results = {}
    for sid, records in data.items():
        if isinstance(records, list) and len(records) > 0:
            df = pd.DataFrame(records)
            if "date" in df.columns and "value" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df["value"] = pd.to_numeric(df["value"], errors="coerce")
                s = df.set_index("date")["value"].dropna()
                s.name = sid
                results[sid] = s
                print(f"    {sid}: {len(s)} obs")
        elif isinstance(records, dict) and "dates" in records:
            dates = pd.to_datetime(records["dates"])
            values = pd.to_numeric(pd.Series(records["values"]), errors="coerce")
            s = pd.Series(values.values, index=dates, name=sid).dropna()
            results[sid] = s
            print(f"    {sid}: {len(s)} obs")

    return results


def fetch_yf_data_via_api():
    """Fetch market data from the backend's cached yahoo data.

    Returns dict of {ticker: pd.Series} with daily close prices.
    """
    print("  [API] Fetching Yahoo data from backend...")
    results = {}

    for ticker in ["SPY", "^VIX", "DX-Y.NYB"]:
        try:
            data = _api_get(f"/api/data/yahoo?tickers={ticker}")
            if isinstance(data, dict) and ticker in data:
                records = data[ticker]
                if isinstance(records, list):
                    df = pd.DataFrame(records)
                    if "date" in df.columns:
                        df["date"] = pd.to_datetime(df["date"])
                        col = "adj_close" if "adj_close" in df.columns else "close"
                        if col in df.columns:
                            s = df.set_index("date")[col].dropna().astype(float)
                            s.name = ticker
                            results[ticker] = s
                            print(f"    {ticker}: {len(s)} obs")
        except Exception as e:
            print(f"    {ticker}: FAILED ({e})")

    return results


def build_gli_signal_via_api():
    """Build GLI signal from the backend's production signal endpoint.

    Returns same structure as build_gli_signal().
    """
    print("\n  [API] Fetching production signal from backend...")
    data = _api_get("/api/gli/production-signal?model=5f")

    if "error" in data:
        raise RuntimeError(f"Production signal error: {data['error']}")

    # Extract ratio_series from BIS credit endpoint
    print("  [API] Fetching BIS credit data from backend...")
    bis = _api_get("/api/gli/bis-credit")
    ratio_series = bis.get("debt_ratio", {}).get("ratio_series", [])

    # Build components from ratio_series
    from research.config import GLI_5F_KEYS, GLI_5F_WEIGHTS

    components = {}
    all_keys = list(set(["quantity_signal", "rate_signal", "spread_signal",
                         "curve_signal", "m2_signal", "dollar_stress_signal"]))
    for key in all_keys:
        s = pd.Series(
            {pd.Timestamp(r["date"]): r.get(key) for r in ratio_series},
            dtype=float).dropna().sort_index()
        if len(s) > 0:
            components[key] = s

    missing = [k for k in GLI_5F_KEYS if k not in components]
    if missing:
        raise RuntimeError(f"Missing GLI components: {missing}")

    # Build composite
    date_sets = [set(components[k].dropna().index) for k in GLI_5F_KEYS]
    common_dates = sorted(set.intersection(*date_sets))
    base_idx = pd.DatetimeIndex(common_dates)

    composite = pd.Series(0.0, index=base_idx)
    for k in GLI_5F_KEYS:
        composite += GLI_5F_WEIGHTS[k] * components[k].reindex(base_idx, method="ffill").fillna(0)

    signal = composite.diff(6).dropna()

    # Expanding-window quintiles
    min_window = 36
    quintiles = pd.Series(np.nan, index=signal.index, dtype=float)
    for i in range(min_window, len(signal)):
        history = signal.iloc[:i+1].values
        current = signal.iloc[i]
        pct = float((history < current).sum()) / len(history) * 100
        q = 1 if pct < 20 else 2 if pct < 40 else 3 if pct < 60 else 4 if pct < 80 else 5
        quintiles.iloc[i] = q

    quintiles = quintiles.dropna().astype(int)
    print(f"  [API] Signal: {len(signal)} pts, Quintiles: {len(quintiles)} pts")
    print(f"  [API] Quintile distribution: {dict(quintiles.value_counts().sort_index())}")

    return {
        "signal": signal,
        "composite": composite,
        "quintiles": quintiles,
        "ratio_series": ratio_series,
        "components": components,
    }
