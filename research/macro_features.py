"""Macro feature computation for GLI Signal Filter Research.

Computes derived features, regime classifications, percentiles,
and changes from raw FRED and yfinance data.

All functions take monthly-resampled data and a signal_date,
returning the value as of that date (no look-ahead).
"""

import numpy as np
import pandas as pd


def resample_to_monthly(s, method="last"):
    """Resample a daily series to month-start, using last observation."""
    if s is None or len(s) == 0:
        return pd.Series(dtype=float)
    m = s.resample("MS").last()
    # Forward-fill up to 3 months max
    return m.ffill(limit=3)


def rolling_percentile(s, value, window_years=5):
    """Percentile of value within trailing window (no look-ahead)."""
    window = window_years * 12
    if len(s) < 12:
        return np.nan
    trailing = s.iloc[-min(window, len(s)):]
    valid = trailing.dropna()
    if len(valid) < 12:
        return np.nan
    return float((valid < value).sum()) / len(valid) * 100


def compute_monetary_features(fred_data, date, monthly_cache):
    """Compute monetary/policy regime features as of date.

    Uses: FEDFUNDS
    Lag: none (reported same month)
    """
    ff = monthly_cache.get("FEDFUNDS")
    if ff is None:
        return {}

    ff_at = ff.loc[:date]
    if len(ff_at) == 0:
        return {}

    current = float(ff_at.iloc[-1])
    change_3m = float(ff_at.iloc[-1] - ff_at.iloc[-4]) * 100 if len(ff_at) >= 4 else np.nan  # bps

    # Fed regime
    if pd.notna(change_3m):
        if change_3m < -25:
            regime = "cutting"
        elif change_3m > 25:
            regime = "hiking"
        else:
            regime = "hold"
    else:
        regime = np.nan

    return {
        "fed_funds_rate": current,
        "fed_funds_3m_change": change_3m,
        "fed_regime": regime,
    }


def compute_credit_features(fred_data, date, monthly_cache):
    """Compute credit features as of date.

    Uses: BAMLH0A0HYM2 (HY OAS)
    Lag: none (daily market data)
    """
    hy = monthly_cache.get("BAMLH0A0HYM2")
    if hy is None:
        return {}

    hy_at = hy.loc[:date]
    if len(hy_at) == 0:
        return {}

    current = float(hy_at.iloc[-1])
    change_3m = float(hy_at.iloc[-1] - hy_at.iloc[-4]) * 100 if len(hy_at) >= 4 else np.nan  # bps
    change_6m = float(hy_at.iloc[-1] - hy_at.iloc[-7]) * 100 if len(hy_at) >= 7 else np.nan  # bps

    # Percentile vs trailing 5 years
    pct_5y = rolling_percentile(hy_at, current, window_years=5)

    return {
        "hy_oas": current,
        "hy_oas_3m_change": change_3m,
        "hy_oas_6m_change": change_6m,
        "hy_oas_level_percentile": pct_5y,
    }


def compute_curve_features(fred_data, date, monthly_cache):
    """Compute yield curve features as of date.

    Uses: DGS10, DGS2, T10Y2Y
    Lag: none (daily market data)
    """
    dgs10 = monthly_cache.get("DGS10")
    dgs2 = monthly_cache.get("DGS2")
    t10y2y = monthly_cache.get("T10Y2Y")

    result = {}

    if dgs10 is not None:
        at = dgs10.loc[:date]
        if len(at) > 0:
            result["treasury_10y"] = float(at.iloc[-1])

    if dgs2 is not None:
        at = dgs2.loc[:date]
        if len(at) > 0:
            result["treasury_2y"] = float(at.iloc[-1])

    # Use T10Y2Y directly if available, otherwise compute
    if t10y2y is not None:
        at = t10y2y.loc[:date]
        if len(at) > 0:
            spread_pct = float(at.iloc[-1])
            result["curve_10y_2y"] = spread_pct * 100  # convert to bps
    elif "treasury_10y" in result and "treasury_2y" in result:
        result["curve_10y_2y"] = (result["treasury_10y"] - result["treasury_2y"]) * 100

    # Curve regime
    spread_bps = result.get("curve_10y_2y")
    if spread_bps is not None:
        if spread_bps < 0:
            result["curve_regime"] = "inverted"
        elif spread_bps < 50:
            result["curve_regime"] = "flat"
        elif spread_bps < 150:
            result["curve_regime"] = "normal"
        else:
            result["curve_regime"] = "steep"

    return result


def compute_real_rate_features(fred_data, date, monthly_cache):
    """Compute real rate features as of date.

    Uses: DFII10 (10Y TIPS yield)
    Lag: none (daily market data)
    Note: DFII10 starts ~2003, so early dates will be NaN.
    """
    tips = monthly_cache.get("DFII10")
    if tips is None:
        return {}

    at = tips.loc[:date]
    if len(at) == 0:
        return {}

    current = float(at.iloc[-1])
    change_3m = float(at.iloc[-1] - at.iloc[-4]) if len(at) >= 4 else np.nan

    return {
        "real_10y": current,
        "real_10y_3m_change": change_3m,
    }


def compute_dollar_features(date, monthly_cache):
    """Compute dollar features as of date.

    Uses: DX-Y.NYB (DXY) from yfinance
    Lag: none (daily market data)
    """
    dxy = monthly_cache.get("DXY")
    if dxy is None:
        return {}

    at = dxy.loc[:date]
    if len(at) == 0:
        return {}

    current = float(at.iloc[-1])
    # 12-month % change
    if len(at) >= 13:
        change_12m = (current / float(at.iloc[-13]) - 1) * 100
    else:
        change_12m = np.nan

    # Regime
    if pd.notna(change_12m):
        if change_12m > 5:
            regime = "strong"
        elif change_12m < -5:
            regime = "weak"
        else:
            regime = "neutral"
    else:
        regime = np.nan

    return {
        "dxy_level": current,
        "dxy_12m_change": change_12m,
        "dxy_regime": regime,
    }


def compute_growth_features(fred_data, date, monthly_cache):
    """Compute growth features as of date.

    Uses: NAPM (ISM Manufacturing PMI)
    Lag: 1 month (ISM reported with ~1 month delay).
          We use the value from the PRIOR month to avoid look-ahead.
    """
    ism = monthly_cache.get("NAPM")
    if ism is None:
        return {}

    # Apply 1-month lag: at date t, we only know ISM for t-1
    at = ism.loc[:date]
    if len(at) < 2:
        return {}

    current = float(at.iloc[-2])  # prior month's value (lag)
    if len(at) >= 5:
        change_3m = float(at.iloc[-2] - at.iloc[-5])  # 3m change using lagged values
    else:
        change_3m = np.nan

    # Growth regime
    if pd.notna(change_3m):
        if current > 50 and change_3m > 0:
            regime = "expansion"
        elif current < 50 and change_3m < 0:
            regime = "contraction"
        else:
            regime = "transition"
    else:
        regime = np.nan

    return {
        "ism_mfg": current,
        "ism_mfg_3m_change": change_3m,
        "growth_regime": regime,
    }


def compute_market_features(date, monthly_cache, daily_cache):
    """Compute market internal features as of date.

    Uses: SPY (price, returns), VIX
    Lag: none
    """
    result = {}

    spy_m = monthly_cache.get("SPY")
    spy_d = daily_cache.get("SPY")
    vix_m = monthly_cache.get("VIX")

    # SPY trailing 12m return
    if spy_m is not None:
        at = spy_m.loc[:date]
        if len(at) >= 13:
            result["spy_trailing_12m_return"] = (float(at.iloc[-1]) / float(at.iloc[-13]) - 1) * 100

    # SPY % from 52-week high (use daily data for accuracy)
    if spy_d is not None:
        daily_at = spy_d.loc[:date]
        if len(daily_at) >= 252:
            high_52w = float(daily_at.iloc[-252:].max())
            current_price = float(daily_at.iloc[-1])
            result["spy_pct_from_52w_high"] = (current_price / high_52w - 1) * 100
        elif len(daily_at) > 20:
            high = float(daily_at.max())
            current_price = float(daily_at.iloc[-1])
            result["spy_pct_from_52w_high"] = (current_price / high - 1) * 100

    # VIX
    if vix_m is not None:
        at = vix_m.loc[:date]
        if len(at) > 0:
            current = float(at.iloc[-1])
            result["vix_level"] = current
            result["vix_percentile_5y"] = rolling_percentile(at, current, window_years=5)

    return result


def compute_valuation_features(date, monthly_cache):
    """Compute valuation features as of date.

    Uses: Shiller CAPE from pre-loaded data.
    Lag: ~1 quarter (earnings data lags)
    """
    cape = monthly_cache.get("CAPE")
    if cape is None:
        return {}

    at = cape.loc[:date]
    if len(at) == 0:
        return {}

    current = float(at.iloc[-1])
    # Percentile vs full available history
    pct = float((at.dropna() < current).sum()) / len(at.dropna()) * 100

    return {
        "sp500_cape": current,
        "cape_percentile_history": pct,
    }


def compute_earnings_features(date, monthly_cache):
    """Compute earnings features as of date.

    Uses: Shiller earnings data (E12 = trailing 12m EPS).
    Lag: ~1 quarter (earnings reported with lag). We use value as-of which
         already reflects the publication lag in Shiller's dataset.
    """
    eps = monthly_cache.get("EPS_12M")
    if eps is None:
        return {}

    at = eps.loc[:date]
    if len(at) < 13:
        return {}

    current = float(at.iloc[-1])
    prev_year = float(at.iloc[-13])

    if prev_year > 0 and current > 0:
        yoy = (current / prev_year - 1) * 100
    elif prev_year < 0 and current > 0:
        yoy = 100.0  # recovery from negative earnings
    else:
        yoy = np.nan

    # Earnings regime
    if pd.notna(yoy):
        # Check if accelerating (yoy > 10 and rising)
        if len(at) >= 16:
            prev_yoy = (float(at.iloc[-4]) / float(at.iloc[-16]) - 1) * 100 if float(at.iloc[-16]) > 0 else 0
        else:
            prev_yoy = 0

        if yoy > 10 and yoy > prev_yoy:
            regime = "accelerating"
        elif yoy < 0 and yoy < prev_yoy:
            regime = "decelerating"
        else:
            regime = "stable"
    else:
        regime = np.nan

    return {
        "sp500_eps_yoy": yoy,
        "earnings_regime": regime,
    }


def fetch_shiller_data():
    """Fetch Shiller CAPE and earnings data.

    Source: Robert Shiller's online dataset (Excel format).
    Returns dict with 'CAPE' and 'EPS_12M' monthly series.
    """
    import requests
    from io import BytesIO

    url = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
    print("  [SHILLER] Fetching Shiller data...")

    try:
        resp = requests.get(url, timeout=60,
                           headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        xls = pd.read_excel(BytesIO(resp.content), sheet_name="Data",
                           header=None, skiprows=7)

        # Columns: 0=Date, 1=S&P Comp, 2=Dividend, 3=Earnings, 4=CPI,
        #          5=Date Fraction, 6=Long Interest Rate, 7=Real Price,
        #          8=Real Dividend, 9=Real Total Return Price, 10=Real Earnings,
        #          11=Real TR Scaled Earnings, 12=CAPE, ...
        # Date is like 2024.01 for Jan 2024
        dates = xls.iloc[:, 0]
        cape_col = xls.iloc[:, 12] if xls.shape[1] > 12 else None
        earnings_col = xls.iloc[:, 3]  # Trailing 12m earnings

        # Parse dates (format: YYYY.MM as float)
        parsed_dates = []
        cape_vals = []
        eps_vals = []

        for i in range(len(dates)):
            try:
                d = float(dates.iloc[i])
                year = int(d)
                month = round((d - year) * 12) + 1
                if month > 12:
                    month = 12
                if month < 1:
                    month = 1
                dt = pd.Timestamp(year=year, month=month, day=1)
                parsed_dates.append(dt)

                if cape_col is not None:
                    cape_vals.append(pd.to_numeric(cape_col.iloc[i], errors="coerce"))
                eps_vals.append(pd.to_numeric(earnings_col.iloc[i], errors="coerce"))
            except (ValueError, TypeError):
                continue

        result = {}
        if cape_vals:
            cape_s = pd.Series(cape_vals, index=parsed_dates, dtype=float).dropna()
            result["CAPE"] = cape_s
            print(f"  [SHILLER] CAPE: {len(cape_s)} obs, "
                  f"{cape_s.index[0].strftime('%Y-%m')} to {cape_s.index[-1].strftime('%Y-%m')}, "
                  f"latest={cape_s.iloc[-1]:.1f}")

        if eps_vals:
            eps_s = pd.Series(eps_vals, index=parsed_dates, dtype=float).dropna()
            result["EPS_12M"] = eps_s
            print(f"  [SHILLER] EPS_12M: {len(eps_s)} obs, latest={eps_s.iloc[-1]:.2f}")

        return result

    except Exception as e:
        print(f"  [SHILLER] FAILED: {e}")
        return {}


def build_monthly_cache(fred_data, yf_data, shiller_data):
    """Build monthly-resampled cache of all series.

    Returns dict of {name: pd.Series} all at month-start frequency.
    """
    cache = {}

    # FRED series (most are daily, resample to monthly)
    for sid, s in fred_data.items():
        cache[sid] = resample_to_monthly(s)

    # yfinance — SPY, VIX, DXY
    if "SPY" in yf_data:
        cache["SPY"] = resample_to_monthly(yf_data["SPY"])
    if "^VIX" in yf_data:
        cache["VIX"] = resample_to_monthly(yf_data["^VIX"])
    if "DX-Y.NYB" in yf_data:
        cache["DXY"] = resample_to_monthly(yf_data["DX-Y.NYB"])

    # Shiller
    for key, s in shiller_data.items():
        cache[key] = s  # already monthly

    return cache


def compute_all_features(date, monthly_cache, daily_cache, fred_data):
    """Compute all macro context features for a single signal_date.

    Returns dict of feature values. No look-ahead: uses only data <= date.
    """
    features = {}
    features.update(compute_monetary_features(fred_data, date, monthly_cache))
    features.update(compute_credit_features(fred_data, date, monthly_cache))
    features.update(compute_curve_features(fred_data, date, monthly_cache))
    features.update(compute_real_rate_features(fred_data, date, monthly_cache))
    features.update(compute_dollar_features(date, monthly_cache))
    features.update(compute_growth_features(fred_data, date, monthly_cache))
    features.update(compute_market_features(date, monthly_cache, daily_cache))
    features.update(compute_valuation_features(date, monthly_cache))
    features.update(compute_earnings_features(date, monthly_cache))
    return features
