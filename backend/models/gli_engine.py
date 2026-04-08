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
    # Accept either CURRCIR or WCURCIR
    currcir_col = "WCURCIR" if "WCURCIR" in df.columns else "CURRCIR"
    required = ["WALCL", "WTREGEN", "RRPONTSYD", currcir_col]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    # Normalize column name for downstream
    if currcir_col != "CURRCIR":
        df = df.rename(columns={currcir_col: "CURRCIR"})

    # UNIT ALIGNMENT:
    # WALCL: Millions USD (weekly)
    # WTREGEN: Millions USD (weekly)
    # RRPONTSYD: Billions USD (daily) — multiply by 1000 to get millions
    # WCURCIR/CURRCIR: Millions USD (weekly)
    df["RRPONTSYD"] = df["RRPONTSYD"] * 1000  # B → M to match others

    # Resample everything to weekly (Wednesday) and forward-fill
    df = df.resample("W-WED").last()
    df = df.ffill().bfill()

    # Log for debugging
    for col in ["WALCL", "WTREGEN", "RRPONTSYD", "CURRCIR"]:
        valid = df[col].dropna()
        if len(valid) > 0:
            print(f"[GLI Engine] {col}: {len(valid)} valid, latest={valid.iloc[-1]:.0f} ($M)")
        else:
            print(f"[GLI Engine] {col}: ALL NaN!")

    # Net liquidity = Total Assets - drains (all in $M now)
    df["net_liquidity"] = (
        df["WALCL"] - df["CURRCIR"] - df["RRPONTSYD"] - df["WTREGEN"]
    )

    # Drop rows where net can't be computed
    df = df.dropna(subset=["net_liquidity"])

    if df.empty:
        return {"components": [], "net_liquidity": [], "latest": {}}

    # Convert from $M to $B for readability
    for col in ["WALCL", "WTREGEN", "RRPONTSYD", "CURRCIR", "net_liquidity"]:
        df[col] = df[col] / 1e3

    # Build output series
    dates = df.index.strftime("%Y-%m-%d").tolist()
    components = []
    for _, row in df.iterrows():
        components.append({
            "date": row.name.strftime("%Y-%m-%d"),
            "WALCL": float(row["WALCL"]) if pd.notna(row["WALCL"]) else None,
            "WTREGEN": float(row["WTREGEN"]) if pd.notna(row["WTREGEN"]) else None,
            "RRPONTSYD": float(row["RRPONTSYD"]) if pd.notna(row["RRPONTSYD"]) else None,
            "CURRCIR": float(row["CURRCIR"]) if pd.notna(row["CURRCIR"]) else None,
            "net_liquidity": float(row["net_liquidity"]) if pd.notna(row["net_liquidity"]) else None,
        })

    # Latest stats — use the last component entry (which is already computed and valid)
    last_comp = components[-1] if components else {}
    prev_comp = components[-2] if len(components) >= 2 else last_comp
    month_comp = components[-5] if len(components) >= 5 else components[0] if components else last_comp

    latest_stats = {
        "net_liquidity": last_comp.get("net_liquidity"),
        "walcl": last_comp.get("WALCL"),
        "tga": last_comp.get("WTREGEN"),
        "rrp": last_comp.get("RRPONTSYD"),
        "currcir": last_comp.get("CURRCIR"),
        "wow_change": (last_comp.get("net_liquidity") or 0) - (prev_comp.get("net_liquidity") or 0),
        "mom_change": (last_comp.get("net_liquidity") or 0) - (month_comp.get("net_liquidity") or 0),
        "date": last_comp.get("date", ""),
    }
    print(f"[GLI Engine] latest_stats: {latest_stats}")

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


# Approximate GDP weights (% of global GDP, ~2024)
GDP_WEIGHTS = {
    "United States": 25.0,
    "China": 18.0,
    "Germany": 4.5,
    "Japan": 5.0,
    "United Kingdom": 3.0,
    "France": 3.5,
    "Italy": 2.5,
    "Spain": 2.0,
    "Canada": 2.0,
    "Australia": 1.5,
    "Korea": 2.0,
    "Brazil": 2.5,
    "India": 4.0,
    "Netherlands": 1.2,
    "Switzerland": 1.0,
    "Sweden": 0.7,
    "Mexico": 1.8,
    "Turkey": 1.2,
}


def compute_diffusion_index(country_zscores: dict) -> list:
    """Compute diffusion index: unweighted and GDP-weighted.

    Unweighted: % of countries with z-score > 50.
    GDP-weighted: sum of GDP weights for countries with z-score > 50,
    divided by total GDP weight of countries with data.

    Args:
        country_zscores: Dict of country_name -> z_score_data (from compute_zscore_momentum).

    Returns:
        List of {date, diffusion, diffusion_weighted, improving_count, total_count}.
    """
    # Collect per-country z-scores by date
    date_map = {}
    for country, zdata in country_zscores.items():
        for point in zdata.get("z_scores", []):
            d = point["date"]
            if d not in date_map:
                date_map[d] = {}
            date_map[d][country] = point["value"]

    # Compute both indices
    raw = []
    for date in sorted(date_map.keys()):
        country_scores = date_map[date]
        if len(country_scores) < 3:
            continue

        # Unweighted
        improving = sum(1 for v in country_scores.values() if v > 50)
        diffusion_uw = (improving / len(country_scores)) * 100

        # GDP-weighted
        total_weight = 0
        improving_weight = 0
        for country, zscore in country_scores.items():
            w = GDP_WEIGHTS.get(country, 0.5)  # default 0.5% for unknown
            total_weight += w
            if zscore > 50:
                improving_weight += w
        diffusion_gw = (improving_weight / total_weight * 100) if total_weight > 0 else 0

        raw.append({
            "date": date,
            "diffusion": diffusion_uw,
            "diffusion_weighted": diffusion_gw,
            "improving_count": improving,
            "total_count": len(country_scores),
        })

    # Interpolate gaps
    if len(raw) > 2:
        dates = pd.to_datetime([r["date"] for r in raw])
        uw = pd.Series([r["diffusion"] for r in raw], index=dates)
        gw = pd.Series([r["diffusion_weighted"] for r in raw], index=dates)
        uw_m = uw.resample("MS").mean().interpolate(method="linear", limit=12).dropna()
        gw_m = gw.resample("MS").mean().interpolate(method="linear", limit=12).dropna()
        common = uw_m.index.intersection(gw_m.index)
        return [
            {"date": d.strftime("%Y-%m-%d"),
             "diffusion": float(uw_m[d]),
             "diffusion_weighted": float(gw_m[d]),
             "improving_count": 0, "total_count": 0}
            for d in common
        ]

    return raw


def compute_debt_liquidity_ratio(total_credit: pd.Series, cb_total: pd.Series,
                                  policy_rate: pd.Series = None,
                                  hy_spread: pd.Series = None,
                                  yield_curve: pd.Series = None,
                                  m2_supply: pd.Series = None) -> dict:
    """Compute debt/liquidity ratio + 5-component composite tightening indicator.

    Composite weights:
      25% Quantity (balance sheet RoC)
      25% Price (policy rate changes)
      20% Credit (HY OAS spread changes)
      15% Structure (yield curve slope changes)
      15% Money (M2 growth vs trend)

    Args:
        total_credit: BIS all-sector credit in USD.
        cb_total: BIS private NF credit in USD.
        policy_rate: Fed Funds rate (DFF/FEDFUNDS).
        hy_spread: HY OAS spread (BAMLH0A0HYM2).
        yield_curve: 2s10s spread (T10Y2Y). Negative = inverted.
        m2_supply: M2 money supply (M2SL).
    """
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

    def _zscore(s, window=36, min_periods=12):
        m = s.rolling(window, min_periods=min_periods).mean()
        st = s.rolling(window, min_periods=min_periods).std().replace(0, np.nan)
        return ((s - m) / st).clip(-3, 3)

    def _align(z_raw):
        return z_raw.reindex(ratio.index, method="ffill").fillna(0)

    # 1. Quantity signal (25%): YoY RoC of ratio — rising = tightening
    qty_z = _zscore(ratio.diff(12))

    # 2. Price signal (25%): 6-month rate change — hiking = tightening
    rate_z = pd.Series(0.0, index=ratio.index)
    if policy_rate is not None and len(policy_rate) > 12:
        rm = policy_rate.resample("MS").last().ffill()
        rate_z = _align(_zscore(rm.diff(6), window=36))

    # 3. Credit signal (20%): HY OAS YoY change — widening = tightening
    spread_z = pd.Series(0.0, index=ratio.index)
    if hy_spread is not None and len(hy_spread) > 12:
        sm = hy_spread.resample("MS").last().ffill()
        spread_z = _align(_zscore(sm.diff(12), window=36))

    # 4. Yield curve signal (15%): YoY change in 2s10s — flattening/inversion = tightening
    # Inverted: negative change = tightening, so we NEGATE it
    curve_z = pd.Series(0.0, index=ratio.index)
    if yield_curve is not None and len(yield_curve) > 12:
        cm = yield_curve.resample("MS").last().ffill()
        curve_chg = cm.diff(12) * -1  # negate: flattening (negative change) = positive (tightening)
        curve_z = _align(_zscore(curve_chg, window=36))

    # 5. M2 signal (15%): YoY growth rate — below trend = tightening
    # Low growth = tightening, so we NEGATE
    m2_z = pd.Series(0.0, index=ratio.index)
    if m2_supply is not None and len(m2_supply) > 12:
        mm = m2_supply.resample("MS").last().ffill()
        m2_yoy = mm.pct_change(12) * 100
        m2_z = _align(_zscore(m2_yoy, window=36) * -1)  # negate: low growth = tightening

    # Composite: 25% + 25% + 20% + 15% + 15%
    composite_z = (0.25 * qty_z.fillna(0) + 0.25 * rate_z.fillna(0) +
                   0.20 * spread_z.fillna(0) + 0.15 * curve_z.fillna(0) +
                   0.15 * m2_z.fillna(0))

    # Scale all to -1 to +1
    scale = lambda z: (z / 3).fillna(0)
    qty_s, rate_s, spread_s, curve_s, m2_s, comp_s = (
        scale(qty_z), scale(rate_z), scale(spread_z),
        scale(curve_z), scale(m2_z), scale(composite_z))

    # Percentile
    comp_valid = comp_s.dropna()
    current_comp = float(comp_valid.iloc[-1]) if len(comp_valid) > 0 else None
    pct = float(scipy_stats.percentileofscore(comp_valid.values, current_comp)) if current_comp is not None and len(comp_valid) > 20 else None

    # Regime transitions
    transitions = []
    prev_sign = None
    for d, v in comp_s.items():
        if pd.isna(v): continue
        sign = "T" if v > 0 else "L"
        if prev_sign is not None and sign != prev_sign:
            transitions.append({"date": d.strftime("%Y-%m-%d"), "direction": sign})
        prev_sign = sign

    interpretation = _generate_interpretation(current, zone, current_comp, pct)

    # Build series
    ratio_series = []
    for d, v in ratio.items():
        entry = {
            "date": d.strftime("%Y-%m-%d"),
            "ratio": float(v),
            "quantity_signal": float(qty_s[d]) if pd.notna(qty_s.get(d)) else None,
            "rate_signal": float(rate_s[d]) if pd.notna(rate_s.get(d)) else None,
            "spread_signal": float(spread_s[d]) if pd.notna(spread_s.get(d)) else None,
            "curve_signal": float(curve_s[d]) if pd.notna(curve_s.get(d)) else None,
            "m2_signal": float(m2_s[d]) if pd.notna(m2_s.get(d)) else None,
            "composite_signal": float(comp_s[d]) if pd.notna(comp_s.get(d)) else None,
        }
        ratio_series.append(entry)

    return {
        "ratio_series": ratio_series,
        "current_ratio": current,
        "current_composite": current_comp,
        "composite_percentile": pct,
        "composite_signal": "tightening" if (current_comp or 0) > 0 else "loosening",
        "transitions": transitions,
        "interpretation": interpretation,
        "zone": zone,
        "thresholds": {"stress": 2.0, "crisis": 2.3},
    }


def _generate_interpretation(ratio: float, zone: str, composite: float, percentile: float) -> str:
    if composite is None or percentile is None:
        return ""

    # Fixed leverage thresholds
    if ratio < 1.50:
        lev_label = "low"
    elif ratio < 1.60:
        lev_label = "moderate"
    else:
        lev_label = "high"

    ratio_high = ratio >= 1.60
    loosening = composite < 0

    pct_label = (
        "deeply loose" if percentile < 20 else
        "moderately loose" if percentile < 40 else
        "neutral" if percentile < 60 else
        "moderately tight" if percentile < 80 else
        "severely tight"
    )

    if ratio_high and loosening:
        outlook = "elevated leverage with improving conditions — watch for risk-on but stay cautious on position size"
    elif ratio_high and not loosening:
        outlook = "elevated leverage with tightening conditions — defensive positioning warranted"
    elif not ratio_high and loosening:
        outlook = "low leverage with loose conditions — most bullish regime"
    else:
        outlook = "low leverage but tightening — transitional, monitor closely"

    return f"Debt/Liquidity at {ratio:.2f}x ({lev_label} leverage) with composite {pct_label} at {percentile:.0f}th percentile — {outlook}"
