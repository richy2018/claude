"""FRED data fetching module."""

import pandas as pd
import requests
from datetime import datetime, timedelta
from ..config import FRED_API_KEY, FRED_SERIES, MONTHLY_SERIES

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


def fetch_fred_series(series_id: str, start_date: str = None, api_key: str = None) -> pd.DataFrame:
    """Fetch a single FRED series."""
    key = api_key or FRED_API_KEY
    if not key:
        raise ValueError("FRED_API_KEY not set. Set it via environment variable or pass directly.")

    if start_date is None:
        start_date = "2000-01-01"

    params = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "observation_start": start_date,
        "sort_order": "asc",
    }

    resp = requests.get(FRED_BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    observations = data.get("observations", [])
    if not observations:
        return pd.DataFrame(columns=["date", series_id])

    df = pd.DataFrame(observations)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df[["date", "value"]].dropna(subset=["value"])
    df = df.rename(columns={"value": series_id})
    df = df.set_index("date")
    return df


def fetch_all_fred(api_key: str = None, start_date: str = "2000-01-01") -> pd.DataFrame:
    """Fetch all configured FRED series and return a combined DataFrame."""
    all_series = {}
    errors = {}

    for series_id in FRED_SERIES:
        try:
            df = fetch_fred_series(series_id, start_date=start_date, api_key=api_key)
            all_series[series_id] = df[series_id]
        except Exception as e:
            errors[series_id] = str(e)

    if not all_series:
        raise RuntimeError(f"Failed to fetch any FRED series. Errors: {errors}")

    combined = pd.DataFrame(all_series)
    combined.index.name = "date"

    return combined, errors


def compute_monthly_derived(df: pd.DataFrame) -> dict:
    """Compute MoM%, YoY%, and annualized rates for monthly index series."""
    derived = {}

    for series_id in MONTHLY_SERIES:
        if series_id not in df.columns:
            continue

        s = df[series_id].dropna()
        if len(s) < 13:
            continue

        mom_pct = s.pct_change() * 100
        yoy_pct = s.pct_change(periods=12) * 100
        # Annualized 3-month rate
        ann_3m = ((s / s.shift(3)) ** 4 - 1) * 100

        derived[series_id] = {
            "mom_pct": mom_pct,
            "yoy_pct": yoy_pct,
            "annualized_3m": ann_3m,
        }

    return derived
