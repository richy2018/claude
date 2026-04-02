"""Data processing and alignment module."""

import pandas as pd
import numpy as np


def align_daily_series(*dataframes: pd.DataFrame) -> pd.DataFrame:
    """Align multiple DataFrames to the same daily date index, forward-filling gaps."""
    if not dataframes:
        return pd.DataFrame()

    # Normalize all indexes: remove timezone, normalize to midnight
    normalized = []
    for df in dataframes:
        d = df.copy()
        # Strip timezone by extracting date only — works on all pandas versions
        d.index = pd.to_datetime(d.index.date)
        # Remove duplicate dates (keep last)
        d = d[~d.index.duplicated(keep='last')]
        normalized.append(d)

    combined = pd.concat(normalized, axis=1)

    # Create full business day index spanning all data
    start = combined.index.min()
    end = combined.index.max()
    full_index = pd.bdate_range(start=start, end=end)

    combined = combined.reindex(full_index)
    combined = combined.ffill()
    combined.index.name = "date"

    return combined


def compute_rolling_returns(df: pd.DataFrame, windows: list = None) -> dict:
    """Compute rolling returns for given windows."""
    if windows is None:
        windows = [1, 5, 10, 21, 63, 126, 252]

    results = {}
    for w in windows:
        results[f"ret_{w}d"] = df.pct_change(w) * 100

    return results


def compute_rolling_zscores(series: pd.Series, lookback: int = 21, vol_window: int = 21) -> pd.Series:
    """Compute rolling z-score: (rolling return) / (rolling std of returns)."""
    returns = series.pct_change()
    rolling_ret = returns.rolling(lookback).sum()
    rolling_std = returns.rolling(vol_window).std() * np.sqrt(lookback)

    zscore = rolling_ret / rolling_std
    zscore = zscore.replace([np.inf, -np.inf], np.nan)
    return zscore


def compute_rolling_correlations(df: pd.DataFrame, window: int = 63) -> pd.DataFrame:
    """Compute pairwise rolling correlations for columns in df."""
    returns = df.pct_change()
    cols = returns.columns.tolist()
    corr_data = {}

    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            key = f"{cols[i]}_vs_{cols[j]}"
            corr_data[key] = returns[cols[i]].rolling(window).corr(returns[cols[j]])

    return pd.DataFrame(corr_data)


def compute_linkage_metric(corr_df: pd.DataFrame) -> pd.Series:
    """Compute average of absolute pairwise correlations."""
    abs_corr = corr_df.abs()
    return abs_corr.mean(axis=1) * 100  # as percentage


def classify_linkage(linkage_value: float) -> str:
    """Classify linkage level."""
    if linkage_value > 60:
        return "STRONGLY LINKED"
    elif linkage_value >= 40:
        return "MODERATE"
    else:
        return "LOW LINKAGE"


def prepare_json_series(df: pd.DataFrame) -> list:
    """Convert a DataFrame to a list of dicts suitable for JSON serialization."""
    df = df.copy()
    df.index = df.index.strftime("%Y-%m-%d")
    records = df.reset_index().to_dict(orient="records")
    return records
