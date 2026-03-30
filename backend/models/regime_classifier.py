"""Cross-asset regime classification engine."""

import pandas as pd
import numpy as np
from ..config import REGIME_DEFINITIONS


def get_regime_key(spx_up: bool, rates_up: bool, dxy_up: bool) -> str:
    """Map boolean states to regime key R1-R8."""
    idx = (int(spx_up) << 2) | (int(rates_up) << 1) | int(dxy_up)
    # Map: 111=R1, 110=R2, 101=R3, 100=R4, 011=R5, 010=R6, 001=R7, 000=R8
    mapping = {7: "R1", 6: "R2", 5: "R3", 4: "R4", 3: "R5", 2: "R6", 1: "R7", 0: "R8"}
    return mapping[idx]


def get_regime_description(regime: str) -> str:
    """Get human-readable description."""
    defn = REGIME_DEFINITIONS[regime]
    parts = []
    parts.append(f"Stocks {defn['spx']}")
    parts.append(f"Rates {defn['rates']}")
    parts.append(f"Dollar {defn['dxy']}")
    return " / ".join(parts)


def classify_regimes(
    spx: pd.Series,
    rates_10y: pd.Series,
    dxy: pd.Series,
    lookback: int = 21,
    vol_window: int = 21,
    vol_scaled: bool = True,
) -> pd.DataFrame:
    """
    Classify each day into one of 8 regimes based on SPX, 10Y, DXY movements.

    Parameters:
        spx: S&P 500 price series
        rates_10y: 10Y Treasury yield series
        dxy: Dollar index series
        lookback: rolling return lookback window in days
        vol_window: rolling volatility window for z-score denominator
        vol_scaled: if True, use vol-scaled returns; if False, use raw z-score
    """
    result = pd.DataFrame(index=spx.index)

    for name, series in [("spx", spx), ("rates", rates_10y), ("dxy", dxy)]:
        returns = series.pct_change()
        rolling_ret = returns.rolling(lookback).sum()

        if vol_scaled:
            rolling_std = returns.rolling(vol_window).std() * np.sqrt(lookback)
            metric = rolling_ret / rolling_std
            metric = metric.replace([np.inf, -np.inf], np.nan)
        else:
            mean = rolling_ret.rolling(252, min_periods=63).mean()
            std = rolling_ret.rolling(252, min_periods=63).std()
            metric = (rolling_ret - mean) / std
            metric = metric.replace([np.inf, -np.inf], np.nan)

        result[f"{name}_metric"] = metric
        result[f"{name}_signal"] = (metric > 0).astype(int)

    # Drop rows where any metric is NaN
    result = result.dropna()

    # Classify regime
    result["regime"] = result.apply(
        lambda row: get_regime_key(
            bool(row["spx_signal"]),
            bool(row["rates_signal"]),
            bool(row["dxy_signal"]),
        ),
        axis=1,
    )

    return result


def compute_regime_stats(regime_df: pd.DataFrame, spx: pd.Series, rates_10y: pd.Series, dxy: pd.Series) -> list:
    """
    Compute per-regime statistics: frequency, avg duration, median returns.
    """
    total_days = len(regime_df)
    daily_spx_ret = spx.pct_change() * 100
    daily_rates_chg = rates_10y.diff() * 100  # in bp
    daily_dxy_ret = dxy.pct_change() * 100

    stats = []
    for regime_key in ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]:
        mask = regime_df["regime"] == regime_key
        count = mask.sum()
        freq = (count / total_days * 100) if total_days > 0 else 0

        # Average duration: count consecutive runs
        runs = (mask != mask.shift()).cumsum()
        runs_in_regime = runs[mask]
        if len(runs_in_regime) > 0:
            durations = runs_in_regime.groupby(runs_in_regime).count()
            avg_dur = durations.mean()
        else:
            avg_dur = 0

        # Median returns while in regime
        regime_dates = regime_df.index[mask]
        spx_med = daily_spx_ret.reindex(regime_dates).median() if count > 0 else 0
        rates_med = daily_rates_chg.reindex(regime_dates).median() if count > 0 else 0
        dxy_med = daily_dxy_ret.reindex(regime_dates).median() if count > 0 else 0

        defn = REGIME_DEFINITIONS[regime_key]
        stats.append({
            "regime": regime_key,
            "description": get_regime_description(regime_key),
            "color": defn["color"],
            "spx_dir": defn["spx"],
            "rates_dir": defn["rates"],
            "dxy_dir": defn["dxy"],
            "freq": round(freq, 1),
            "avg_dur": round(avg_dur, 1) if not np.isnan(avg_dur) else 0,
            "spx_median": round(spx_med, 3) if not np.isnan(spx_med) else 0,
            "rates_median": round(rates_med, 3) if not np.isnan(rates_med) else 0,
            "dxy_median": round(dxy_med, 3) if not np.isnan(dxy_med) else 0,
            "count": int(count),
        })

    return stats


def compute_transition_matrix(regime_series: pd.Series) -> dict:
    """
    Compute 8x8 transition probability matrix.
    Returns dict with 'matrix' (8x8 probabilities) and 'counts' (8x8 raw counts).
    """
    regimes = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
    counts = pd.DataFrame(0, index=regimes, columns=regimes, dtype=int)

    prev = regime_series.iloc[0] if len(regime_series) > 0 else None
    for curr in regime_series.iloc[1:]:
        if prev in regimes and curr in regimes:
            counts.loc[prev, curr] += 1
        prev = curr

    # Normalize rows to probabilities
    row_sums = counts.sum(axis=1)
    probs = counts.div(row_sums, axis=0).fillna(0)

    return {
        "matrix": probs.round(3).values.tolist(),
        "counts": counts.values.tolist(),
        "regimes": regimes,
    }


def compute_transition_from_current(regime_series: pd.Series, current_regime: str) -> list:
    """
    From the current regime, compute probability of transitioning to each other regime.
    Returns sorted list by probability descending.
    """
    regimes = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
    transitions = []

    mask = regime_series == current_regime
    indices = regime_series.index[mask]

    total = 0
    next_counts = {r: 0 for r in regimes}

    for idx in indices:
        pos = regime_series.index.get_loc(idx)
        if pos + 1 < len(regime_series):
            next_regime = regime_series.iloc[pos + 1]
            if next_regime in regimes:
                next_counts[next_regime] += 1
                total += 1

    for r in regimes:
        prob = (next_counts[r] / total * 100) if total > 0 else 0
        is_stay = r == current_regime
        transitions.append({
            "to": r,
            "to_label": f"{r} (stay)" if is_stay else r,
            "prob": round(prob, 1),
            "hist_obs": next_counts[r],
            "is_stay": is_stay,
            "description": get_regime_description(r),
            "color": REGIME_DEFINITIONS[r]["color"],
        })

    transitions.sort(key=lambda x: x["prob"], reverse=True)
    return transitions


def compute_regime_linkage(
    regime_df: pd.DataFrame,
    spx: pd.Series,
    rates_10y: pd.Series,
    dxy: pd.Series,
    corr_window: int = 63,
) -> dict:
    """Compute median linkage per regime and per-regime asset theme (which asset drives most)."""
    from ..data.processor import compute_rolling_correlations, compute_linkage_metric

    asset_df = pd.DataFrame({"SPX": spx, "10Y": rates_10y, "DXY": dxy}).reindex(regime_df.index).dropna()
    if len(asset_df) < corr_window + 10:
        return {}

    corr_df = compute_rolling_correlations(asset_df, window=corr_window)
    linkage = compute_linkage_metric(corr_df)

    regimes = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
    result = {}

    for r in regimes:
        mask = regime_df["regime"].reindex(linkage.index) == r
        regime_linkage = linkage[mask]
        if len(regime_linkage) > 0:
            median_linkage = float(regime_linkage.median())
        else:
            median_linkage = 0.0

        # Theme: which asset has highest absolute metric in this regime
        regime_rows = regime_df[regime_df["regime"] == r]
        if len(regime_rows) > 0:
            avg_abs = {
                "SPX": abs(regime_rows["spx_metric"].mean()),
                "10Y": abs(regime_rows["rates_metric"].mean()),
                "DXY": abs(regime_rows["dxy_metric"].mean()),
            }
            total = sum(avg_abs.values()) or 1
            theme = {k: round(v / total * 100, 1) for k, v in avg_abs.items()}
        else:
            theme = {"SPX": 33.3, "10Y": 33.3, "DXY": 33.3}

        result[r] = {
            "median_linkage": round(median_linkage, 1),
            "theme": theme,
        }

    return result
