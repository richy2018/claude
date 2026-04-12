"""Howell Liquidity Reverse-Engineering — Phase 1 (Debt Numerator) + Phase 2 (Anchor Points).

Builds Advanced Economy total debt from BIS data and establishes
Howell's implied liquidity series from publicly stated anchor points.
"""

import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline


# Advanced Economy countries from BIS (exclude EM: China, Brazil, India, Mexico, Turkey)
ADVANCED_ECONOMIES = [
    "United States", "Japan", "United Kingdom", "Germany", "France",
    "Italy", "Spain", "Canada", "Australia", "Korea",
    "Netherlands", "Switzerland", "Sweden",
]

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


def build_debt_numerator(bis_credit_df):
    """Phase 1: Build Advanced Economy total debt from BIS credit data.

    Args:
        bis_credit_df: DataFrame from fetch_bis_credit() — columns are country names,
                       index is quarterly dates, values in USD billions.

    Returns:
        pd.Series: Quarterly total debt in USD trillions for advanced economies.
    """
    if bis_credit_df is None or bis_credit_df.empty:
        return None, "No BIS credit data available"

    # Filter to advanced economies only
    available = [c for c in ADVANCED_ECONOMIES if c in bis_credit_df.columns]
    missing = [c for c in ADVANCED_ECONOMIES if c not in bis_credit_df.columns]

    if len(available) < 5:
        return None, f"Only {len(available)} advanced economies available (need 5+). Missing: {missing}"

    if missing:
        print(f"[HOWELL] Missing advanced economies: {missing}")

    # Diagnostic: print per-country latest values
    print(f"[HOWELL] BIS columns available: {list(bis_credit_df.columns)}")
    print(f"[HOWELL] BIS series code: Q.XX.C.A.M.USD.A (C=total credit to non-financial sector)")
    for c in available:
        latest = bis_credit_df[c].dropna()
        if len(latest) > 0:
            print(f"[HOWELL]   {c}: ${latest.iloc[-1]:.1f}B (as of {latest.index[-1].strftime('%Y-%m')})")

    # Also check if "All reporting countries" aggregate exists
    if "All reporting countries" in bis_credit_df.columns:
        agg = bis_credit_df["All reporting countries"].dropna()
        if len(agg) > 0:
            print(f"[HOWELL]   ALL REPORTING: ${agg.iloc[-1]:.1f}B (includes EM)")

    # Sum in USD billions, convert to trillions
    total_debt = bis_credit_df[available].sum(axis=1) / 1000  # billions → trillions
    total_debt = total_debt.dropna()

    # Also try using the BIS aggregate if available and larger
    if "All reporting countries" in bis_credit_df.columns:
        agg_total = bis_credit_df["All reporting countries"].dropna() / 1000
        if len(agg_total) > 0:
            print(f"[HOWELL] All-reporting aggregate: ${agg_total.iloc[-1]:.1f}T vs sum of AE: ${total_debt.iloc[-1]:.1f}T")

    print(f"[HOWELL] Advanced Economy debt: {len(total_debt)} quarters, "
          f"latest=${total_debt.iloc[-1]:.1f}T ({len(available)} countries)")

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

    enriched_anchors = []
    for anchor in HOWELL_ANCHORS:
        d = pd.Timestamp(anchor["date"])
        # Find nearest quarterly date in debt series (manual — side='nearest' not supported)
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
            **anchor,
            "date_aligned": nearest_idx.strftime("%Y-%m-%d"),
            "debt_at_date": round(debt_at_date, 1),
            "implied_liquidity": round(implied_liq, 1),
            "implied_ratio": round(implied_ratio, 2) if implied_ratio else None,
            "confidence_weight": 1.0 if anchor["confidence"] == "stated" else 0.5,
        })

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
        "n_countries": len([c for c in ADVANCED_ECONOMIES if c in ([] if debt_series is None else ADVANCED_ECONOMIES)]),
    }


def run_howell_phase1_2(bis_credit_df):
    """Run Phase 1 (debt numerator) + Phase 2 (anchor points + implied liquidity).

    Args:
        bis_credit_df: DataFrame from fetch_bis_credit() cache.
    """
    print("[HOWELL] === Phase 1: Build Debt Numerator ===")
    debt, err = build_debt_numerator(bis_credit_df)
    if err:
        return {"error": f"Phase 1 failed: {err}"}

    print("\n[HOWELL] === Phase 2: Anchor Points + Implied Liquidity ===")
    result = build_implied_liquidity(debt)
    if "error" in result:
        return {"error": f"Phase 2 failed: {result['error']}"}

    result["debt_numerator"] = {
        "latest": round(float(debt.iloc[-1]), 1),
        "start": debt.index[0].strftime("%Y-%m-%d"),
        "end": debt.index[-1].strftime("%Y-%m-%d"),
        "n_quarters": len(debt),
    }

    return result
