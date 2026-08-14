"""Causal (point-in-time-safe) primitives for the GLI signal.

Every function here obeys one rule: the value produced for month `t` may only
depend on observations dated `<= t` that were also *published* by `t`.

This module exists because the original pipeline mixed two resampling
conventions for the same BIS release — the numerator used `resample().ffill()`
(causal) while the denominator used `CubicSpline` over the whole history
(acausal). See `quarterly_to_monthly_causal` below.

Nothing here fetches data. Fetch-side vintage handling lives in `pit_fred.py`.
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Publication lags
# ---------------------------------------------------------------------------

# Calendar days between the period a datapoint describes and the date it first
# becomes available. These are release-schedule facts, not tuning knobs.
#
#   BIS credit    quarterly, published ~4-5 months after quarter end. The BIS
#                 "long series on total credit" release calendar has run
#                 90-150d; we take the conservative end because a signal that
#                 assumes the fast end is untradeable in the slow quarters.
#   M2SL          monthly, released ~4 weeks after month end.
#   HY OAS / DFF  daily, effectively same-day.
#   xccy basis    weekly marks.
PUBLICATION_LAG_DAYS = {
    "quantity_signal": 150,
    "m2_signal": 30,
    "spread_signal": 1,
    "dollar_stress_signal": 7,
    "rate_signal": 1,
}

# Same thing in whole months, for month-indexed series where a day-level shift
# is meaningless. ceil(days/30) so a 150d lag costs 5 months, not 4.
PUBLICATION_LAG_MONTHS = {
    k: int(np.ceil(v / 30.0)) for k, v in PUBLICATION_LAG_DAYS.items()
}


def quarterly_to_monthly_causal(df, limit=None):
    """Expand a quarter-indexed frame to month-start using step (ffill) only.

    This is the causal counterpart to `gli_engine.interpolate_quarterly_to_monthly`,
    which fits a CubicSpline across the entire series. A spline's value at month
    `t` is a function of knots on BOTH sides of `t`, so it encodes quarters that
    had not yet occurred. Forward reach is roughly two knots (~6 months), with
    geometrically decaying influence beyond that.

    Step expansion loses the smoothness a spline gives you, and that is the
    point: the smoothness was manufactured out of future observations.

    Args:
        df: DataFrame or Series with a quarter-end (or quarter-start) DatetimeIndex.
        limit: optional max months to carry a stale value forward. None = unlimited.

    Returns:
        Month-start indexed object of the same type.
    """
    is_series = isinstance(df, pd.Series)
    frame = df.to_frame("value") if is_series else df

    if len(frame) == 0:
        return df

    idx = pd.date_range(frame.index.min(), frame.index.max(), freq="MS")
    out = frame.reindex(frame.index.union(idx)).ffill(limit=limit).reindex(idx)
    out.index.name = "date"

    return out["value"].rename(df.name) if is_series else out


def apply_publication_lag(series, key=None, months=None):
    """Shift a month-indexed series forward by its publication lag.

    After this, the value carried at month `t` is the one that had actually been
    released by `t`. `key` looks the lag up in PUBLICATION_LAG_MONTHS; `months`
    overrides it directly.
    """
    if months is None:
        if key is None:
            raise ValueError("apply_publication_lag needs either `key` or `months`")
        months = PUBLICATION_LAG_MONTHS.get(key, 0)
    return series.shift(months) if months > 0 else series


def expanding_quintiles(signal, min_window=36, one_based=True):
    """Quintile of each month within its own trailing history.

    Cutoffs are locked in as of each month, so appending new observations never
    re-buckets past months. This matches the existing production behaviour and
    is already correct — reimplemented here only so the causal path has no
    dependency back into `backtest_engine`.
    """
    q = pd.Series(np.nan, index=signal.index, dtype=float)
    vals = signal.to_numpy()
    base = 1 if one_based else 0

    for i in range(min_window, len(signal)):
        history = vals[: i + 1]
        pct = float((history < vals[i]).sum()) / len(history) * 100.0
        q.iloc[i] = base + (0 if pct < 20 else 1 if pct < 40 else
                            2 if pct < 60 else 3 if pct < 80 else 4)
    return q


def build_composite(components, keys, weights, index=None, require_all=True):
    """Weighted composite with honest handling of missing components.

    The original path did `comp += w * s.reindex(idx, method="ffill").fillna(0)`.
    That `fillna(0)` silently treats "this factor does not exist yet" as "this
    factor reads exactly neutral", so early history runs as a partial model
    wearing the full model's name — and because 0 is the centre of every
    component's range, the partial composite looks calm rather than unknown.

    Here, months where a required component is absent are dropped (require_all)
    or the surviving weights are renormalised (not require_all), and the count
    of contributing factors is returned so callers can gate on it.
    """
    if index is None:
        idx_sets = [set(components[k].dropna().index) for k in keys if k in components]
        if not idx_sets:
            raise ValueError("no components available")
        index = pd.DatetimeIndex(sorted(set.intersection(*idx_sets)))

    aligned = {}
    for k in keys:
        if k in components:
            aligned[k] = components[k].reindex(index, method="ffill")

    comp = pd.Series(0.0, index=index)
    used_w = pd.Series(0.0, index=index)
    n_present = pd.Series(0, index=index, dtype=int)

    for k, s in aligned.items():
        present = s.notna()
        comp = comp.add((weights[k] * s).where(present, 0.0), fill_value=0.0)
        used_w = used_w.add(pd.Series(weights[k], index=index).where(present, 0.0),
                            fill_value=0.0)
        n_present += present.astype(int)

    if require_all:
        full = n_present == len(keys)
        comp = comp.where(full)
    else:
        comp = comp / used_w.replace(0.0, np.nan)

    return comp.dropna(), n_present


def causal_zscore(series, window=36, min_periods=12, clip=3.0):
    """Trailing-window z-score. Already correct in the original; kept for parity."""
    m = series.rolling(window, min_periods=min_periods).mean()
    s = series.rolling(window, min_periods=min_periods).std().replace(0, np.nan)
    return ((series - m) / s).clip(-clip, clip)
