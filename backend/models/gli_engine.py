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

    # Resample everything to weekly (Wednesday) and forward-fill
    # This aligns the daily RRP/TGA with the weekly WALCL
    df = df.resample("W-WED").last()
    df = df.ffill()
    # Also backward-fill to handle the very first rows
    df = df.bfill()

    # Log for debugging
    for col in required:
        valid = df[col].dropna()
        if len(valid) > 0:
            print(f"[GLI Engine] {col}: {len(valid)} valid, latest={valid.iloc[-1]:.0f}")
        else:
            print(f"[GLI Engine] {col}: ALL NaN!")

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


def compute_howell_sine_wave(dates: pd.DatetimeIndex, cycle_months: int = 65) -> list:
    """Compute Howell's 65-month liquidity sine wave overlay.

    Calibrated with known cycle points:
    - Trough: December 2022 (most recent liquidity bottom)
    - Peak: ~September 2025 (≈32.5 months later, half cycle)

    Args:
        dates: DatetimeIndex of the z-score series.
        cycle_months: Howell's empirical cycle length (default 65).

    Returns:
        List of {date, sine_value} dicts, scaled 0-100.
    """
    if len(dates) == 0:
        return []

    # Calibrate phase: trough at Dec 2022
    # sin(x) has trough at x = -π/2 (i.e., 3π/2)
    # So at Dec 2022, we want: freq * t_trough + phase = -π/2
    trough_date = pd.Timestamp("2022-12-01")
    freq = 2 * np.pi / cycle_months

    output = []
    for date in dates:
        # Months from trough
        months_from_trough = (date.year - trough_date.year) * 12 + (date.month - trough_date.month)
        # At trough, sin should be -1 (minimum), so use sin(freq*t - π/2)
        wave_val = np.sin(freq * months_from_trough - np.pi / 2)
        # Scale to 0-100
        scaled = (wave_val + 1) / 2 * 100
        output.append({
            "date": date.strftime("%Y-%m-%d"),
            "sine_value": float(scaled),
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

    # JPNASSETS is in 100 million JPY (億円) from FRED
    # e.g. 7,578,930 = ¥757.893 trillion
    # Convert: JPNASSETS * 100 (→ JPY millions) / DEXJPUS (JPY per USD) / 1000 (→ USD B)
    # Simplified: JPNASSETS / DEXJPUS / 10
    if "JPNASSETS" in cb_df.columns and "DEXJPUS" in fx_monthly.columns:
        fx_aligned = fx_monthly["DEXJPUS"].reindex(cb_df.index, method="ffill")
        result["BoJ"] = cb_df["JPNASSETS"] / fx_aligned / 10

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

    # Only include dates with at least 3 countries reporting
    raw = []
    for date in sorted(date_map.keys()):
        values = date_map[date]
        if len(values) >= 3:
            improving = sum(1 for v in values if v > 50)
            raw.append({
                "date": date,
                "diffusion": (improving / len(values)) * 100,
                "improving_count": improving,
                "total_count": len(values),
            })

    # Interpolate any gaps (missing months) using linear interpolation
    if len(raw) > 2:
        dates = pd.to_datetime([r["date"] for r in raw])
        values = pd.Series([r["diffusion"] for r in raw], index=dates)
        # Resample to monthly, interpolate gaps
        monthly = values.resample("MS").mean()
        monthly = monthly.interpolate(method="linear", limit=12)
        monthly = monthly.dropna()
        result = [
            {"date": d.strftime("%Y-%m-%d"), "diffusion": float(v),
             "improving_count": 0, "total_count": 0}
            for d, v in monthly.items()
        ]
        return result

    return raw


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
