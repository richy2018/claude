"""Yield curve regime classification engine."""

import pandas as pd
import numpy as np


# Spread pair definitions: (label, short_series, long_series)
SPREAD_PAIRS = {
    "10Y-2Y": ("DGS2", "DGS10"),
    "10Y-3M": ("DGS3MO", "DGS10"),
    "30Y-2Y": ("DGS2", "DGS30"),
    "30Y-3M": ("DGS3MO", "DGS30"),
    "30Y-10Y": ("DGS10", "DGS30"),
    "5Y-2Y": ("DGS2", "DGS5"),
    "5Y-3M": ("DGS3MO", "DGS5"),
    "2Y-3M": ("DGS3MO", "DGS2"),
}

CURVE_REGIMES = {
    "Bull Steepener": {"color": "#00cc44", "desc": "Both rates falling, spread widening"},
    "Bear Steepener": {"color": "#ff4444", "desc": "Both rates rising, spread widening"},
    "Steepener Twist": {"color": "#ffaa00", "desc": "Spread widening, rates diverging"},
    "Bull Flattener": {"color": "#00cccc", "desc": "Both rates falling, spread narrowing"},
    "Bear Flattener": {"color": "#cc44aa", "desc": "Both rates rising, spread narrowing"},
    "Flattener Twist": {"color": "#8844cc", "desc": "Spread narrowing, rates diverging"},
}


def classify_curve_regimes(
    short_yields: pd.Series,
    long_yields: pd.Series,
    lookback: int = 21,
) -> pd.DataFrame:
    """
    Classify each day into one of 6 yield curve regimes.

    Parameters:
        short_yields: short tenor yield series (e.g., DGS2)
        long_yields: long tenor yield series (e.g., DGS10)
        lookback: rolling window for change calculation
    """
    spread = long_yields - short_yields

    delta_short = short_yields.diff(lookback)
    delta_long = long_yields.diff(lookback)
    delta_spread = delta_long - delta_short  # positive = steepening

    result = pd.DataFrame({
        "short_yield": short_yields,
        "long_yield": long_yields,
        "spread": spread,
        "spread_bp": spread * 100,
        "delta_short": delta_short,
        "delta_long": delta_long,
        "delta_spread": delta_spread,
    })

    def _classify(row):
        ds = row["delta_spread"]
        d_short = row["delta_short"]
        d_long = row["delta_long"]

        if pd.isna(ds) or pd.isna(d_short) or pd.isna(d_long):
            return None

        if ds > 0:  # Steepening
            if d_short < 0 and d_long < 0:
                return "Bull Steepener"
            elif d_short > 0 and d_long > 0:
                return "Bear Steepener"
            else:
                return "Steepener Twist"
        else:  # Flattening
            if d_short < 0 and d_long < 0:
                return "Bull Flattener"
            elif d_short > 0 and d_long > 0:
                return "Bear Flattener"
            else:
                return "Flattener Twist"

    result["regime"] = result.apply(_classify, axis=1)
    result = result.dropna(subset=["regime"])

    return result


def compute_curve_regime_stats(
    regime_df: pd.DataFrame,
    short_yields: pd.Series,
    long_yields: pd.Series,
) -> list:
    """Compute per-regime statistics."""
    total_days = len(regime_df)
    daily_short_chg = short_yields.diff() * 100  # bp
    daily_long_chg = long_yields.diff() * 100
    spread = long_yields - short_yields
    daily_spread_chg = spread.diff() * 100

    regime_names = list(CURVE_REGIMES.keys())
    stats = []

    for name in regime_names:
        mask = regime_df["regime"] == name
        count = mask.sum()
        freq = (count / total_days * 100) if total_days > 0 else 0

        # Average duration
        if count > 0:
            runs = (mask != mask.shift()).cumsum()
            runs_in = runs[mask]
            durations = runs_in.groupby(runs_in).count()
            avg_dur = float(durations.mean()) if len(durations) > 0 else 0
        else:
            avg_dur = 0

        dates = regime_df.index[mask]
        short_med = float(daily_short_chg.reindex(dates).median()) if count > 0 else 0
        long_med = float(daily_long_chg.reindex(dates).median()) if count > 0 else 0
        spread_med = float(daily_spread_chg.reindex(dates).median()) if count > 0 else 0

        info = CURVE_REGIMES[name]
        stats.append({
            "regime": name,
            "color": info["color"],
            "description": info["desc"],
            "freq": round(freq, 1),
            "avg_dur": round(avg_dur, 1) if not np.isnan(avg_dur) else 0,
            "short_chg": round(short_med, 2) if not np.isnan(short_med) else 0,
            "long_chg": round(long_med, 2) if not np.isnan(long_med) else 0,
            "spread_chg": round(spread_med, 2) if not np.isnan(spread_med) else 0,
            "count": int(count),
        })

    return stats
