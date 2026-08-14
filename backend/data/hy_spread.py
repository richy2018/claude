"""High-yield OAS from the Bloomberg export in backend/data/HY data.csv.

WHY THIS FILE EXISTS
FRED serves the licensed ICE BofA series (BAMLH0A0HYM2, BAMLC0A4CBBB) as a
~3-year rolling window regardless of observation_start — verified 2026-08-14: a
request from 2000-01-01 returned 795 observations starting 2023-08-14. That left
spread_signal, 20% of the 5F composite, absent for 96% of the backtest.

This export covers 1994-01 to present, so the credit component finally spans the
whole history, including the GFC (peaks at 19.71 in Nov-Dec 2008).

FORMAT
    Semicolon-delimited, no header, European dates:  DD.MM.YYYY;value
    Monthly (month-end dated) until 2000-08, daily from 2000-08-16 onward.
    The mixed frequency is harmless — every consumer resamples to month-start
    and a month-end observation lands in the month it belongs to.

Values are percent (3.29 = 329bp), matching FRED's convention for the same
quantity, so this is a drop-in replacement for the BAMLH0A0HYM2 column.
"""

from pathlib import Path

import pandas as pd

DEFAULT_PATH = Path(__file__).resolve().parent / "HY data.csv"

# Below this the series cannot support diff(12) + a 36-month z-score plus the
# Rule A 60-month percentile window.
MIN_USABLE_MONTHS = 120


def load_hy_spread(path=None, strict=False):
    """Load the export into a float Series indexed by date, ascending.

    Args:
        path: override the default location.
        strict: raise if the file is missing rather than returning None. The
            default is lenient so the app still boots without the export; the
            credit component simply falls back down CREDIT_SPREAD_SERIES.

    Returns:
        pd.Series named "HY_OAS", or None when absent and strict is False.
    """
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        if strict:
            raise FileNotFoundError(f"HY spread export not found at {p}")
        print(f"[HY] No export at {p} — falling back to FRED credit series.")
        return None

    df = pd.read_csv(p, sep=";", header=None, names=["date", "value"], dtype=str)

    # dayfirst is not a guess: 31.01.1994 in row 1 is unambiguous.
    dates = pd.to_datetime(df["date"], format="%d.%m.%Y", errors="coerce")
    # Tolerate a comma decimal separator in case the export locale changes.
    values = pd.to_numeric(df["value"].str.replace(",", ".", regex=False),
                           errors="coerce")

    bad = int(dates.isna().sum() + values.isna().sum())
    s = pd.Series(values.to_numpy(), index=dates).dropna().sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s.name = "HY_OAS"

    months = len(s.resample("MS").last().dropna())
    print(f"[HY] Loaded {len(s)} obs ({months} months) "
          f"{s.index[0]:%Y-%m-%d} -> {s.index[-1]:%Y-%m-%d}, "
          f"range {s.min():.2f}-{s.max():.2f}"
          + (f", {bad} unparseable rows skipped" if bad else ""))

    if months < MIN_USABLE_MONTHS:
        print(f"[HY] WARNING: only {months} months — below the {MIN_USABLE_MONTHS} "
              f"needed for the signal's own transforms.")

    return s


def is_usable(series):
    """True when the series is long enough to carry the signal."""
    if series is None or len(series) == 0:
        return False
    return len(series.resample("MS").last().dropna()) >= MIN_USABLE_MONTHS
