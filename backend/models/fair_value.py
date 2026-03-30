"""Fair Value Model computations — inflation projections, base effects, growth metrics."""

import pandas as pd
import numpy as np
from datetime import datetime


def compute_inflation_model(
    index_series: pd.Series,
    series_name: str = "CPI",
    projection_months: int = 12,
) -> dict:
    """
    Compute full inflation model data for a given index series.
    Returns YoY, MoM, projections, and base effects.
    """
    s = index_series.dropna().sort_index()
    if len(s) < 13:
        return {"error": f"Not enough data for {series_name}"}

    # Basic MoM and YoY
    mom_pct = s.pct_change() * 100
    yoy_pct = s.pct_change(12) * 100

    # Latest values
    latest_date = s.index[-1]
    latest_index = float(s.iloc[-1])
    latest_mom = float(mom_pct.iloc[-1]) if not np.isnan(mom_pct.iloc[-1]) else 0
    latest_yoy = float(yoy_pct.iloc[-1]) if not np.isnan(yoy_pct.iloc[-1]) else 0

    # MoM moving averages
    mom_1m = float(mom_pct.iloc[-1]) if len(mom_pct) > 0 else 0
    mom_2m = float(mom_pct.iloc[-2:].mean()) if len(mom_pct) > 1 else mom_1m
    mom_3m = float(mom_pct.iloc[-3:].mean()) if len(mom_pct) > 2 else mom_1m

    # --- Projections ---
    projections = _compute_projections(s, mom_1m, mom_2m, mom_3m, projection_months)

    # --- MoM historical data ---
    mom_history = []
    for dt, val in mom_pct.items():
        if not np.isnan(val):
            mom_history.append({
                "date": dt.strftime("%Y-%m-%d"),
                "mom": round(val, 4),
            })

    # MoM moving average series
    mom_ma_1m = mom_pct.rolling(1).mean()
    mom_ma_2m = mom_pct.rolling(2).mean()
    mom_ma_3m = mom_pct.rolling(3).mean()

    # --- YoY historical data ---
    yoy_history = []
    for dt, val in yoy_pct.items():
        if not np.isnan(val):
            yoy_history.append({
                "date": dt.strftime("%Y-%m-%d"),
                "yoy": round(val, 4),
            })

    # --- Base effects ---
    base_effects = _compute_base_effects(s, mom_pct, mom_1m, mom_2m, mom_3m, projection_months)

    return {
        "series_name": series_name,
        "latest_date": latest_date.strftime("%Y-%m-%d"),
        "latest_date_label": latest_date.strftime("%b %y"),
        "latest_index": round(latest_index, 3),
        "latest_mom": round(latest_mom, 2),
        "latest_yoy": round(latest_yoy, 2),
        "mom_1m_pace": round(mom_1m, 4),
        "mom_2m_pace": round(mom_2m, 4),
        "mom_3m_pace": round(mom_3m, 4),
        "yoy_history": yoy_history[-120:],  # last 10 years of monthly
        "mom_history": mom_history[-120:],
        "projections": projections,
        "base_effects": base_effects,
    }


def _compute_projections(
    index_series: pd.Series,
    mom_1m: float,
    mom_2m: float,
    mom_3m: float,
    months_forward: int = 12,
) -> dict:
    """
    Project YoY inflation forward using different MoM pace assumptions.
    Model: grow current index at assumed MoM pace, compare to actual index 12 months prior.
    """
    s = index_series.sort_index()
    current_index = float(s.iloc[-1])
    latest_date = s.index[-1]

    results = {"1m_pace": [], "2m_pace": [], "3m_pace": []}

    for pace_name, pace in [("1m_pace", mom_1m), ("2m_pace", mom_2m), ("3m_pace", mom_3m)]:
        projected_index = current_index
        for m in range(1, months_forward + 1):
            projected_index *= (1 + pace / 100)
            # Date of projection
            proj_date = latest_date + pd.DateOffset(months=m)
            # Actual index 12 months prior to projection date
            target_date = proj_date - pd.DateOffset(months=12)
            # Find closest actual index value
            prior_index = _get_nearest_value(s, target_date)

            if prior_index and prior_index > 0:
                projected_yoy = (projected_index / prior_index - 1) * 100
            else:
                projected_yoy = None

            results[pace_name].append({
                "date": proj_date.strftime("%Y-%m-%d"),
                "projected_yoy": round(projected_yoy, 4) if projected_yoy is not None else None,
                "projected_index": round(projected_index, 3),
            })

    return results


def _compute_base_effects(
    index_series: pd.Series,
    mom_pct: pd.Series,
    mom_1m: float,
    mom_2m: float,
    mom_3m: float,
    months_forward: int = 12,
) -> dict:
    """
    Compute base effects for each future month.
    For each projected month, identify which old MoM rolls off the 12-month window.
    Favorable (green) = hot month exits; Unfavorable (red) = cool month exits.
    """
    s = index_series.sort_index()
    latest_date = s.index[-1]
    mom = mom_pct.dropna()

    results = {"1m_pace": [], "2m_pace": [], "3m_pace": []}

    for pace_name, pace in [("1m_pace", mom_1m), ("2m_pace", mom_2m), ("3m_pace", mom_3m)]:
        annualized_pace = ((1 + pace / 100) ** 12 - 1) * 100

        for m in range(1, months_forward + 1):
            proj_date = latest_date + pd.DateOffset(months=m)
            # The month that drops off: 12 months before the projection month
            drop_date = proj_date - pd.DateOffset(months=12)

            # Find the MoM that happened at the drop-off date
            drop_mom = _get_nearest_value(mom, drop_date)

            if drop_mom is not None:
                # Base effect = difference between projected pace and the dropping-off MoM
                # If dropping off a hot (high) MoM and replacing with current pace: favorable
                # If dropping off a cool (low) MoM: unfavorable
                effect = drop_mom - pace  # positive = favorable (hot month exits)
                favorable = effect > 0

                results[pace_name].append({
                    "date": proj_date.strftime("%Y-%m-%d"),
                    "drop_off_mom": round(drop_mom, 4),
                    "replacement_pace": round(pace, 4),
                    "base_effect": round(effect, 4),
                    "favorable": favorable,
                    "annualized_pace": round(annualized_pace, 2),
                })
            else:
                results[pace_name].append({
                    "date": proj_date.strftime("%Y-%m-%d"),
                    "drop_off_mom": None,
                    "replacement_pace": round(pace, 4),
                    "base_effect": None,
                    "favorable": None,
                    "annualized_pace": round(annualized_pace, 2),
                })

    return results


def compute_growth_model(
    payrolls: pd.Series = None,
    claims: pd.Series = None,
    gdp: pd.Series = None,
) -> dict:
    """
    Compute growth model data — 3-month changes, YoY, projections.
    Uses payrolls (PAYEMS) as the primary growth proxy.
    """
    result = {}

    if payrolls is not None and len(payrolls.dropna()) > 3:
        s = payrolls.dropna().sort_index()
        mom_chg = s.diff()  # monthly change in thousands
        yoy_pct = s.pct_change(12) * 100
        chg_3m = s.diff(3)

        # 3-month change history
        chg_3m_history = []
        for dt, val in chg_3m.items():
            if not np.isnan(val):
                chg_3m_history.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "value": round(float(val), 1),
                })

        # YoY history
        yoy_history = []
        for dt, val in yoy_pct.items():
            if not np.isnan(val):
                yoy_history.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "yoy": round(float(val), 4),
                })

        # MoM change history
        mom_history = []
        for dt, val in mom_chg.items():
            if not np.isnan(val):
                mom_history.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "mom": round(float(val), 1),
                })

        # Latest values
        latest = {
            "date": s.index[-1].strftime("%Y-%m-%d"),
            "level": round(float(s.iloc[-1]), 1),
            "mom_chg": round(float(mom_chg.iloc[-1]), 1) if not np.isnan(mom_chg.iloc[-1]) else 0,
            "yoy_pct": round(float(yoy_pct.iloc[-1]), 2) if not np.isnan(yoy_pct.iloc[-1]) else 0,
            "chg_3m": round(float(chg_3m.iloc[-1]), 1) if not np.isnan(chg_3m.iloc[-1]) else 0,
        }

        # Projections using same methodology as inflation model
        mom_pct_series = s.pct_change() * 100
        mom_1m = float(mom_pct_series.iloc[-1]) if len(mom_pct_series) > 0 else 0
        mom_2m = float(mom_pct_series.iloc[-2:].mean()) if len(mom_pct_series) > 1 else mom_1m
        mom_3m = float(mom_pct_series.iloc[-3:].mean()) if len(mom_pct_series) > 2 else mom_1m

        projections = _compute_projections(s, mom_1m, mom_2m, mom_3m, 12)
        base_effects = _compute_base_effects(s, mom_pct_series, mom_1m, mom_2m, mom_3m, 12)

        result["payrolls"] = {
            "latest": latest,
            "chg_3m_history": chg_3m_history[-120:],
            "yoy_history": yoy_history[-120:],
            "mom_history": mom_history[-120:],
            "projections": projections,
            "base_effects": base_effects,
            "mom_1m_pace": round(mom_1m, 4),
            "mom_2m_pace": round(mom_2m, 4),
            "mom_3m_pace": round(mom_3m, 4),
        }

    if claims is not None and len(claims.dropna()) > 4:
        s = claims.dropna().sort_index()
        # Resample to monthly for consistency
        s_monthly = s.resample("MS").mean()
        chg_3m = s_monthly.diff(3)

        chg_3m_history = []
        for dt, val in chg_3m.items():
            if not np.isnan(val):
                chg_3m_history.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "value": round(float(val), 1),
                })

        result["claims"] = {
            "latest": {
                "date": s.index[-1].strftime("%Y-%m-%d"),
                "level": round(float(s.iloc[-1]), 0),
            },
            "chg_3m_history": chg_3m_history[-120:],
        }

    return result


def _get_nearest_value(series: pd.Series, target_date) -> float:
    """Get the nearest value in a series to a target date."""
    if len(series) == 0:
        return None
    idx = series.index.get_indexer([target_date], method="nearest")
    if idx[0] >= 0 and idx[0] < len(series):
        val = float(series.iloc[idx[0]])
        return val if not np.isnan(val) else None
    return None
