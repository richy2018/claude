"""GLI computation engine — Fed net liquidity, z-scores, diffusion, sine wave."""

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats


def compute_fed_net_liquidity(df: pd.DataFrame) -> dict:
    """Compute Fed net liquidity = WALCL - CURRCIR - RRPONTSYD - WTREGEN.

    Args:
        df: DataFrame with columns WALCL, WTREGEN, RRPONTSYD, CURRCIR (all in $M).

    Returns:
        Dict with components list, net_liquidity list, and latest stats.
    """
    required = ["WALCL", "WTREGEN", "RRPONTSYD", "CURRCIR"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    # Forward-fill to align weekly series that report on different days
    df = df.ffill()

    # Net liquidity = Total Assets - drains
    df["net_liquidity"] = (
        df["WALCL"] - df["CURRCIR"] - df["RRPONTSYD"] - df["WTREGEN"]
    )

    # Drop rows where net can't be computed
    df = df.dropna(subset=["net_liquidity"])

    if df.empty:
        return {"components": [], "net_liquidity": [], "latest": {}}

    # Convert to $B for readability
    for col in required + ["net_liquidity"]:
        df[col] = df[col] / 1e3  # FRED reports in $M, convert to $B

    # Build output series
    dates = df.index.strftime("%Y-%m-%d").tolist()
    components = []
    for _, row in df.iterrows():
        components.append({
            "date": row.name.strftime("%Y-%m-%d"),
            "WALCL": row["WALCL"],
            "WTREGEN": row["WTREGEN"],
            "RRPONTSYD": row["RRPONTSYD"],
            "CURRCIR": row["CURRCIR"],
            "net_liquidity": row["net_liquidity"],
        })

    # Latest stats
    latest = df.iloc[-1]
    prev_week = df.iloc[-2] if len(df) >= 2 else latest
    # Find value ~4 weeks ago
    month_ago_idx = max(0, len(df) - 5)
    prev_month = df.iloc[month_ago_idx]

    latest_stats = {
        "net_liquidity": latest["net_liquidity"],
        "walcl": latest["WALCL"],
        "tga": latest["WTREGEN"],
        "rrp": latest["RRPONTSYD"],
        "currcir": latest["CURRCIR"],
        "wow_change": latest["net_liquidity"] - prev_week["net_liquidity"],
        "mom_change": latest["net_liquidity"] - prev_month["net_liquidity"],
        "date": latest.name.strftime("%Y-%m-%d"),
    }

    return {
        "components": components,
        "latest": latest_stats,
    }


def compute_zscore_momentum(series: pd.Series, window: int = 60) -> dict:
    """Compute z-score momentum for a CB balance sheet series.

    Args:
        series: Monthly balance sheet values in USD.
        window: Rolling window in months for z-score (default 60 = 5 years).

    Returns:
        Dict with z_scores (0-100 scale), yoy_growth, raw values.
    """
    if len(series) < window:
        return {"z_scores": [], "yoy_growth": [], "momentum_score": None}

    # YoY growth rate
    yoy = series.pct_change(12) * 100

    # Rolling z-score of YoY growth
    rolling_mean = yoy.rolling(window).mean()
    rolling_std = yoy.rolling(window).std()
    z_raw = (yoy - rolling_mean) / rolling_std.replace(0, np.nan)

    # Convert z-score to 0-100 via normal CDF
    z_score_pct = pd.Series(
        scipy_stats.norm.cdf(z_raw) * 100,
        index=z_raw.index,
    )

    # Current momentum score
    latest_z = z_score_pct.dropna()
    momentum_score = float(latest_z.iloc[-1]) if len(latest_z) > 0 else None

    # Build output
    z_out = []
    for date, val in z_score_pct.dropna().items():
        z_out.append({"date": date.strftime("%Y-%m-%d"), "value": val})

    yoy_out = []
    for date, val in yoy.dropna().items():
        yoy_out.append({"date": date.strftime("%Y-%m-%d"), "value": val})

    return {
        "z_scores": z_out,
        "yoy_growth": yoy_out,
        "momentum_score": momentum_score,
    }


def compute_howell_sine_wave(z_scores: pd.Series, cycle_months: int = 65) -> list:
    """Compute Howell's 65-month liquidity sine wave overlay.

    Fits a sine wave to the aggregate z-score to identify cycle phase.
    """
    if len(z_scores) < cycle_months:
        return []

    # Generate idealized sine wave at the cycle frequency
    n = len(z_scores)
    t = np.arange(n)
    freq = 2 * np.pi / cycle_months

    # Find best phase alignment via correlation
    best_phase = 0
    best_corr = -1
    for phase in np.linspace(0, 2 * np.pi, 360):
        wave = np.sin(freq * t + phase)
        corr = np.corrcoef(z_scores.values, wave)[0, 1]
        if not np.isnan(corr) and corr > best_corr:
            best_corr = corr
            best_phase = phase

    # Generate the fitted wave
    fitted = np.sin(freq * t + best_phase)
    # Scale to 0-100 range to match z-score percentile
    fitted_scaled = (fitted + 1) / 2 * 100

    output = []
    for i, (date, _) in enumerate(z_scores.items()):
        output.append({
            "date": date.strftime("%Y-%m-%d"),
            "sine_value": float(fitted_scaled[i]),
        })

    return output


def convert_cb_to_usd(cb_df: pd.DataFrame, fx_df: pd.DataFrame) -> pd.DataFrame:
    """Convert non-USD CB balance sheets to USD using FX rates.

    Args:
        cb_df: DataFrame with columns like WALCL (already USD), JPNASSETS (JPY), ECB (EUR), PBoC (CNY).
        fx_df: DataFrame with DEXUSEU, DEXJPUS, DEXCHUS.

    Returns:
        DataFrame with all values in USD billions.
    """
    # Resample FX to monthly and forward-fill to align with CB data
    fx_monthly = fx_df.resample("MS").last().ffill()

    result = pd.DataFrame(index=cb_df.index)

    # WALCL is already in USD millions from FRED
    if "WALCL" in cb_df.columns:
        result["Fed"] = cb_df["WALCL"] / 1e3  # $M → $B

    # JPNASSETS is in JPY billions from FRED
    if "JPNASSETS" in cb_df.columns and "DEXJPUS" in fx_monthly.columns:
        fx_aligned = fx_monthly["DEXJPUS"].reindex(cb_df.index, method="ffill")
        # DEXJPUS = JPY per USD, so divide to get USD
        result["BoJ"] = cb_df["JPNASSETS"] / fx_aligned / 1e3  # JPY B → USD B

    # ECB is in EUR millions from ECB SDMX
    if "ECB" in cb_df.columns and "DEXUSEU" in fx_monthly.columns:
        fx_aligned = fx_monthly["DEXUSEU"].reindex(cb_df.index, method="ffill")
        # DEXUSEU = USD per EUR, so multiply
        result["ECB"] = cb_df["ECB"] * fx_aligned / 1e3  # EUR M → USD B

    # PBoC is in CNY billions from IMF IFS
    if "PBoC" in cb_df.columns and "DEXCHUS" in fx_monthly.columns:
        fx_aligned = fx_monthly["DEXCHUS"].reindex(cb_df.index, method="ffill")
        # DEXCHUS = CNY per USD, so divide
        result["PBoC"] = cb_df["PBoC"] / fx_aligned  # CNY B → USD B

    return result.dropna(how="all")


def interpolate_quarterly_to_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Interpolate quarterly BIS credit data to monthly using cubic spline.

    Args:
        df: DataFrame with quarterly DatetimeIndex and country columns.

    Returns:
        Monthly interpolated DataFrame.
    """
    from scipy.interpolate import CubicSpline

    # Create monthly index spanning the quarterly range
    monthly_idx = pd.date_range(df.index.min(), df.index.max(), freq="MS")

    result = pd.DataFrame(index=monthly_idx)
    for col in df.columns:
        s = df[col].dropna()
        if len(s) < 4:
            continue
        # Convert dates to numeric for interpolation
        x = (s.index - s.index[0]).days.values.astype(float)
        y = s.values
        cs = CubicSpline(x, y, extrapolate=False)
        x_new = (monthly_idx - s.index[0]).days.values.astype(float)
        result[col] = cs(x_new)

    result.index.name = "date"
    return result


def compute_diffusion_index(country_zscores: dict) -> list:
    """Compute diffusion index = % of countries with z-score > 50.

    Args:
        country_zscores: Dict of country_name -> z_score_data (from compute_zscore_momentum).

    Returns:
        List of {date, diffusion, improving_count, total_count}.
    """
    # Collect all z-score series by date
    date_map = {}
    for country, zdata in country_zscores.items():
        for point in zdata.get("z_scores", []):
            d = point["date"]
            if d not in date_map:
                date_map[d] = []
            date_map[d].append(point["value"])

    result = []
    for date in sorted(date_map.keys()):
        values = date_map[date]
        improving = sum(1 for v in values if v > 50)
        result.append({
            "date": date,
            "diffusion": (improving / len(values)) * 100 if values else 0,
            "improving_count": improving,
            "total_count": len(values),
        })

    return result


def compute_debt_liquidity_ratio(total_credit: pd.Series, cb_total: pd.Series) -> dict:
    """Compute debt/liquidity ratio = total credit / CB balance sheets.

    Thresholds (Howell framework):
    - < 2.0: Normal
    - 2.0-2.3: Stress zone
    - > 2.3: Crisis zone

    Args:
        total_credit: Total credit in USD (from BIS).
        cb_total: Combined CB balance sheets in USD.

    Returns:
        Dict with ratio series, current ratio, and zone classification.
    """
    # Align indices
    common = total_credit.index.intersection(cb_total.index)
    if len(common) == 0:
        return {"ratio_series": [], "current_ratio": None, "zone": "unknown"}

    tc = total_credit.reindex(common)
    cb = cb_total.reindex(common)
    ratio = (tc / cb).replace([np.inf, -np.inf], np.nan).dropna()

    if ratio.empty:
        return {"ratio_series": [], "current_ratio": None, "zone": "unknown"}

    current = float(ratio.iloc[-1])
    zone = "normal" if current < 2.0 else "stress" if current < 2.3 else "crisis"

    ratio_series = [
        {"date": d.strftime("%Y-%m-%d"), "ratio": float(v)}
        for d, v in ratio.items()
    ]

    return {
        "ratio_series": ratio_series,
        "current_ratio": current,
        "zone": zone,
        "thresholds": {"stress": 2.0, "crisis": 2.3},
    }
