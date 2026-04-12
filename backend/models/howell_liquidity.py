"""Howell Liquidity Reverse-Engineering — Phase 1 (Debt Numerator) + Phase 2 (Anchor Points).

Builds Advanced Economy total debt from BIS data and establishes
Howell's implied liquidity series from publicly stated anchor points.
"""

import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline


# Advanced Economy countries (BIS country codes → names)
ADVANCED_ECONOMY_CODES = {
    "US": "United States",
    "JP": "Japan",
    "GB": "United Kingdom",
    "DE": "Germany",
    "FR": "France",
    "IT": "Italy",
    "ES": "Spain",
    "CA": "Canada",
    "AU": "Australia",
    "KR": "Korea",
    "NL": "Netherlands",
    "CH": "Switzerland",
    "SE": "Sweden",
}

# Howell's publicly stated anchor points with confidence levels
HOWELL_ANCHORS = [
    {"date": "2008-09-01", "ratio": 2.9, "liquidity": None, "confidence": "stated",
     "source": "Capital Wars book, multiple interviews — exact figure repeated"},
    {"date": "2011-06-01", "ratio": 3.0, "liquidity": None, "confidence": "inferred",
     "source": "Howell said Eurozone crisis 'peaked' above 2008 — 3.0 is estimate"},
    {"date": "2021-06-01", "ratio": 1.6, "liquidity": None, "confidence": "inferred",
     "source": "Howell said 'well below 2.0x' during Everything Bubble — 1.6 is midpoint of 1.5-1.7"},
    {"date": "2024-06-01", "ratio": None, "liquidity": 175, "confidence": "stated",
     "source": "Great Wall of Debt Substack Oct 2024 — '$175 trillion'"},
    {"date": "2024-12-01", "ratio": None, "liquidity": 190, "confidence": "stated",
     "source": "TFTC interview Feb 2026, FNArena Mar 2026 — '$188-190 trillion'"},
    {"date": "2025-09-01", "ratio": None, "liquidity": 190, "confidence": "stated",
     "source": "Capital Wars 'Risks' post Apr 2026 — '$190 trillion, peak growth rate'"},
]

# Long-run average constraint (not an anchor — a distributional property)
LONG_RUN_AVERAGE_RATIO = 2.5  # Howell: ~2.5x since 1980


def _fetch_bis_country(country_code, borrowing_sector="A"):
    """Fetch BIS total credit for one country with specified borrowing sector.

    BIS WS_TC key: Q.{country}.{sector}.A.M.USD.A
    Sector codes:
      A = All sectors (total economy) — government + households + corporates
      C = Total credit to non-financial sector
      P = Private non-financial sector only
      G = General government
      H = Households + NPISHs
    """
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
                series = df.set_index("date")["value"].dropna().sort_index()
                return series
    except Exception as e:
        print(f"[HOWELL BIS] {country_code} sector={borrowing_sector}: {e}")
    return pd.Series(dtype=float)


def build_debt_numerator(bis_credit_df=None):
    """Phase 1: Build Advanced Economy total debt from BIS total credit data.

    Fetches two BIS series per country and sums them:
    - Sector C: Total credit to non-financial sector (HH + Corp + Gov borrowing from all lenders)
    - Sector G: General government debt (if C doesn't include it fully)

    BIS WS_TC sector C should already include government. If the total
    is still ~$157T, we use the cached data which may be more complete.
    """
    print("[HOWELL] Fetching BIS total credit for advanced economies...")

    country_data = {}
    failed = []

    for code, name in ADVANCED_ECONOMY_CODES.items():
        # Try sector C first (total credit to non-financial sector — should include gov)
        series = _fetch_bis_country(code, borrowing_sector="C")
        if len(series) > 10:
            country_data[name] = series
            print(f"[HOWELL]   {code} ({name}): ${series.iloc[-1]:.1f}B ({len(series)} obs, sector C)")
        else:
            failed.append(f"{code} ({name})")
            print(f"[HOWELL]   {code} ({name}): FAILED")

    if len(country_data) < 5:
        return None, f"Only {len(country_data)} countries fetched. Failed: {failed}"

    # Combine and sum
    combined = pd.DataFrame(country_data)
    combined.index = pd.to_datetime(combined.index)
    nf_total = combined.sum(axis=1) / 1000  # billions → trillions
    nf_total = nf_total.dropna().sort_index()

    print(f"[HOWELL] Non-financial sector total: ${nf_total.iloc[-1]:.1f}T")

    # Now fetch general government debt separately to add
    print("[HOWELL] Fetching general government debt (sector G)...")
    gov_data = {}
    for code, name in ADVANCED_ECONOMY_CODES.items():
        series_g = _fetch_bis_country(code, borrowing_sector="G")
        if len(series_g) > 10:
            gov_data[name] = series_g
            print(f"[HOWELL]   {code} ({name}): Gov=${series_g.iloc[-1]:.1f}B")

    if gov_data:
        gov_combined = pd.DataFrame(gov_data)
        gov_combined.index = pd.to_datetime(gov_combined.index)
        gov_total = gov_combined.sum(axis=1) / 1000
        gov_total = gov_total.dropna().sort_index()
        print(f"[HOWELL] Government debt total: ${gov_total.iloc[-1]:.1f}T")

        # Total = NF sector + Government (avoid double-counting if C already includes G)
        # Check: if NF + Gov > 1.5 × NF, gov is likely separate; if close to NF, gov is already in C
        common = nf_total.index.intersection(gov_total.index)
        combined_total = nf_total.reindex(common) + gov_total.reindex(common)
        ratio_check = float(combined_total.iloc[-1] / nf_total.iloc[-1])
        print(f"[HOWELL] NF+Gov ratio: {ratio_check:.2f}x (if >1.3, gov is separate)")

        if ratio_check > 1.2:
            total_debt = combined_total
            print(f"[HOWELL] Using NF + Gov = ${total_debt.iloc[-1]:.1f}T")
        else:
            total_debt = nf_total
            print(f"[HOWELL] Gov likely already in NF, using NF only = ${total_debt.iloc[-1]:.1f}T")
    else:
        total_debt = nf_total
        print(f"[HOWELL] No gov data, using NF only = ${total_debt.iloc[-1]:.1f}T")

    if len(total_debt) < 10:
        return None, "Insufficient quarterly observations"

    print(f"[HOWELL] Final AE debt: ${total_debt.iloc[-1]:.1f}T ({len(country_data)} countries)")
    print(f"[HOWELL] Range: {total_debt.index[0].strftime('%Y-%m')} to {total_debt.index[-1].strftime('%Y-%m')}")

    return total_debt, None


def build_implied_liquidity(debt_series):
    """Phase 2: Build implied liquidity series from Howell's anchor points.

    Where ratio is known: liquidity = debt / ratio
    Where liquidity level is known: use directly
    Interpolate between points with cubic spline.

    Returns:
        dict with anchors (enriched), implied_liquidity (interpolated series),
        debt_at_anchors, and validation info.
    """
    if debt_series is None or len(debt_series) < 10:
        return {"error": "Insufficient debt data"}

    # Ensure proper DatetimeIndex
    debt_series.index = pd.to_datetime(debt_series.index)
    print(f"[HOWELL] build_implied_liquidity: {len(debt_series)} pts, index dtype={debt_series.index.dtype}")

    enriched_anchors = []
    for anchor in HOWELL_ANCHORS:
      try:
        d = pd.Timestamp(anchor["date"])
        print(f"[HOWELL]   Processing anchor {d.strftime('%Y-%m')}...")
        # Find nearest quarterly date in debt series
        pos = debt_series.index.searchsorted(d, side='left')
        pos = min(pos, len(debt_series.index) - 1)
        # Check both pos and pos-1 for true nearest
        if pos > 0:
            before = debt_series.index[pos - 1]
            after = debt_series.index[pos]
            nearest_idx = before if abs((d - before).days) < abs((d - after).days) else after
        else:
            nearest_idx = debt_series.index[pos]
        if abs((nearest_idx - d).days) > 180:
            print(f"[HOWELL] Anchor {d.strftime('%Y-%m')} too far from nearest data ({nearest_idx.strftime('%Y-%m')}), skipping")
            continue

        debt_at_date = float(debt_series[nearest_idx])

        if anchor["ratio"] is not None:
            implied_liq = debt_at_date / anchor["ratio"]
        elif anchor["liquidity"] is not None:
            implied_liq = anchor["liquidity"]
        else:
            continue

        # Compute the complementary value
        implied_ratio = debt_at_date / implied_liq if implied_liq > 0 else None

        enriched_anchors.append({
            "date": anchor["date"],
            "ratio": anchor.get("ratio"),
            "liquidity": anchor.get("liquidity"),
            "confidence": anchor["confidence"],
            "source": anchor["source"],
            "date_aligned": nearest_idx.strftime("%Y-%m-%d"),
            "debt_at_date": round(debt_at_date, 1),
            "implied_liquidity": round(implied_liq, 1),
            "implied_ratio": round(implied_ratio, 2) if implied_ratio else None,
            "confidence_weight": 1.0 if anchor["confidence"] == "stated" else 0.5,
        })
      except Exception as e:
        print(f"[HOWELL] Anchor processing error for {anchor.get('date')}: {e}")
        import traceback; traceback.print_exc()
        continue

    if len(enriched_anchors) < 3:
        return {"error": f"Only {len(enriched_anchors)} usable anchors (need 3+)"}

    # Build interpolated implied liquidity series via cubic spline
    anchor_dates = [pd.Timestamp(a["date_aligned"]) for a in enriched_anchors]
    anchor_values = [a["implied_liquidity"] for a in enriched_anchors]

    # Convert to numeric for spline
    t_numeric = np.array([(d - anchor_dates[0]).days for d in anchor_dates], dtype=float)
    try:
        spline = CubicSpline(t_numeric, anchor_values, extrapolate=True)
    except Exception as e:
        return {"error": f"Spline interpolation failed: {e}"}

    # Generate interpolated series at quarterly frequency
    quarterly_dates = debt_series.index
    t_all = np.array([(d - anchor_dates[0]).days for d in quarterly_dates], dtype=float)
    implied_values = spline(t_all)

    # Clip to reasonable range (can't be negative or absurdly large)
    implied_values = np.clip(implied_values, 20, 500)

    implied_liquidity = pd.Series(implied_values, index=quarterly_dates, name="implied_liquidity")

    # Compute ratio series
    ratio_series = debt_series / implied_liquidity

    # Validation: long-run average ratio
    avg_ratio = float(ratio_series.mean())
    avg_check = "PASS" if 2.3 <= avg_ratio <= 2.7 else "WARN"

    print(f"[HOWELL] Implied liquidity: {len(implied_liquidity)} quarters, "
          f"current=${implied_liquidity.iloc[-1]:.1f}T, "
          f"avg ratio={avg_ratio:.2f}x ({avg_check})")

    # Build chart data
    chart = []
    for d in quarterly_dates:
        chart.append({
            "date": d.strftime("%Y-%m-%d"),
            "debt": round(float(debt_series[d]), 1),
            "implied_liquidity": round(float(implied_liquidity[d]), 1),
            "ratio": round(float(ratio_series[d]), 2),
        })

    # Anchor validation dots
    anchor_chart = []
    for a in enriched_anchors:
        anchor_chart.append({
            "date": a["date_aligned"],
            "implied_liquidity": a["implied_liquidity"],
            "ratio": a["implied_ratio"],
            "confidence": a["confidence"],
            "source": a["source"],
        })

    return {
        "anchors": enriched_anchors,
        "anchor_chart": anchor_chart,
        "chart": chart,
        "current_debt": round(float(debt_series.iloc[-1]), 1),
        "current_implied_liquidity": round(float(implied_liquidity.iloc[-1]), 1),
        "current_ratio": round(float(ratio_series.iloc[-1]), 2),
        "avg_ratio": round(avg_ratio, 2),
        "avg_ratio_check": avg_check,
        "n_quarters": len(chart),
        "n_countries": len(ADVANCED_ECONOMY_CODES),
    }


def run_howell_phase1_2(bis_credit_df=None):
    """Run Phase 1 (debt numerator) + Phase 2 (anchor points + implied liquidity).

    Fetches BIS total credit directly with borrowing_sector=A (all sectors).
    The bis_credit_df parameter is ignored — we fetch independently.
    """
    print("[HOWELL] === Phase 1: Build Debt Numerator ===")
    debt, err = build_debt_numerator()
    if err:
        return {"error": f"Phase 1 failed: {err}"}

    print("\n[HOWELL] === Phase 2: Anchor Points + Implied Liquidity ===")
    try:
        print(f"[HOWELL] Debt index type: {type(debt.index)}, len={len(debt)}, first={debt.index[0]}, last={debt.index[-1]}")
        result = build_implied_liquidity(debt)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": f"Phase 2 crashed: {str(e)}"}
    if "error" in result:
        return {"error": f"Phase 2 failed: {result['error']}"}

    result["debt_numerator"] = {
        "latest": round(float(debt.iloc[-1]), 1),
        "start": debt.index[0].strftime("%Y-%m-%d"),
        "end": debt.index[-1].strftime("%Y-%m-%d"),
        "n_quarters": len(debt),
    }

    return result
