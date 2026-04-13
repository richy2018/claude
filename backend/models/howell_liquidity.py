"""Howell Liquidity — BIS Advanced Economy Debt Context.

Fetches BIS total credit (C+G sectors) for 13 advanced economies.
Provides structural debt context for the GLI production signal.
"""

import numpy as np
import pandas as pd


ADVANCED_ECONOMY_CODES = {
    "US": "United States", "JP": "Japan", "GB": "United Kingdom",
    "DE": "Germany", "FR": "France", "IT": "Italy", "ES": "Spain",
    "CA": "Canada", "AU": "Australia", "KR": "Korea",
    "NL": "Netherlands", "CH": "Switzerland", "SE": "Sweden",
}


def _fetch_bis_country(country_code, borrowing_sector="C"):
    """Fetch BIS total credit for one country."""
    import requests
    from io import StringIO

    headers = {"User-Agent": "Mozilla/5.0"}
    base_url = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_TC/2.0"
    key = f"Q.{country_code}.{borrowing_sector}.A.M.USD.A"
    url = f"{base_url}/{key}?format=csv"

    try:
        resp = requests.get(url, headers=headers, timeout=60)
        if resp.status_code == 200 and len(resp.text) > 100:
            df = pd.read_csv(StringIO(resp.text))
            time_col = val_col = None
            for c in df.columns:
                cl = c.lower()
                if time_col is None and ("time_period" in cl or "period" in cl):
                    time_col = c
                if val_col is None and ("obs_value" in cl or cl == "value"):
                    val_col = c
            if time_col and val_col:
                df["date"] = pd.to_datetime(df[time_col])
                df["value"] = pd.to_numeric(df[val_col], errors="coerce")
                return df.set_index("date")["value"].dropna().sort_index()
    except Exception as e:
        print(f"[HOWELL BIS] {country_code} sector={borrowing_sector}: {e}")
    return pd.Series(dtype=float)


def build_debt_numerator():
    """Fetch BIS Advanced Economy total debt (C+G sectors, 13 countries).

    Returns quarterly series in USD trillions.
    """
    print("[DEBT CONTEXT] Fetching BIS total credit (sector C + G)...")
    country_data = {}
    for code, name in ADVANCED_ECONOMY_CODES.items():
        series_c = _fetch_bis_country(code, "C")
        series_g = _fetch_bis_country(code, "G")
        if len(series_c) > 10:
            total = series_c.copy()
            if len(series_g) > 10:
                common = series_c.index.intersection(series_g.index)
                ratio = float((series_c.reindex(common) + series_g.reindex(common)).iloc[-1] / series_c.reindex(common).iloc[-1])
                if ratio > 1.2:
                    total = series_c.reindex(common) + series_g.reindex(common)
            country_data[name] = total

    if len(country_data) < 5:
        return None, "Not enough countries"

    combined = pd.DataFrame(country_data)
    combined.index = pd.to_datetime(combined.index)
    total_debt = combined.sum(axis=1).dropna().sort_index() / 1000  # B → T
    print(f"[DEBT CONTEXT] AE debt: ${total_debt.iloc[-1]:.1f}T ({len(country_data)} countries)")
    return total_debt, None


def get_debt_context(debt_series=None, gli_regime=None, m2_value=None):
    """Build debt context card data.

    Args:
        debt_series: Quarterly AE total debt in $T (from build_debt_numerator)
        gli_regime: Current GLI regime string ("BULLISH"/"NEUTRAL"/"BEARISH")
        m2_value: Current US M2 in $T (from FRED cache)
    """
    if debt_series is None or len(debt_series) < 5:
        return None

    current_debt = float(debt_series.iloc[-1])

    # YoY growth
    if len(debt_series) > 4:
        prev_year = float(debt_series.iloc[-5]) if len(debt_series) >= 5 else current_debt
        yoy_growth = round((current_debt / prev_year - 1) * 100, 1) if prev_year > 0 else 0
    else:
        yoy_growth = 0

    # Debt/M2 ratio
    debt_m2 = round(current_debt / m2_value, 1) if m2_value and m2_value > 0 else None

    # Interpretation
    gli_positive = gli_regime in ("BULLISH",)
    gli_negative = gli_regime in ("BEARISH",)
    debt_accelerating = yoy_growth > 3.0

    if gli_positive and not debt_accelerating:
        interp = "Adequate liquidity for current debt levels"
    elif gli_positive and debt_accelerating:
        interp = "Rising debt but liquidity supportive — monitor"
    elif gli_negative and not debt_accelerating:
        interp = "Tightening liquidity against elevated debt stock"
    elif gli_negative and debt_accelerating:
        interp = "Debt growth into tightening liquidity — highest stress"
    else:
        interp = "Neutral liquidity conditions with moderate debt burden"

    return {
        "ae_debt_T": round(current_debt, 1),
        "yoy_growth_pct": yoy_growth,
        "debt_m2_ratio": debt_m2,
        "as_of": debt_series.index[-1].strftime("%Y-%m-%d"),
        "n_countries": len(ADVANCED_ECONOMY_CODES),
        "interpretation": interp,
    }
