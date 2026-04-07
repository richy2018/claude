"""GLI data fetching — Fed net liquidity, CB balance sheets, FX rates."""

import pandas as pd
from .fred_fetcher import fetch_fred_series
from ..config import GLI_FED_SERIES, GLI_FX_SERIES, GLI_CB_SERIES


def fetch_gli_fed(api_key: str, start_date: str = "2003-01-01") -> pd.DataFrame:
    """Fetch the 4 Fed net liquidity component series from FRED."""
    frames = {}
    errors = {}
    for series_id in GLI_FED_SERIES:
        try:
            df = fetch_fred_series(series_id, start_date=start_date, api_key=api_key)
            frames[series_id] = df[series_id]
        except Exception as e:
            errors[series_id] = str(e)

    if not frames:
        raise RuntimeError(f"Failed to fetch any Fed liquidity series: {errors}")

    combined = pd.DataFrame(frames)
    combined.index.name = "date"
    return combined, errors


def fetch_gli_fx(api_key: str, start_date: str = "2003-01-01") -> pd.DataFrame:
    """Fetch FX rate series for USD conversion."""
    frames = {}
    errors = {}
    for series_id in GLI_FX_SERIES:
        try:
            df = fetch_fred_series(series_id, start_date=start_date, api_key=api_key)
            frames[series_id] = df[series_id]
        except Exception as e:
            errors[series_id] = str(e)

    if not frames:
        raise RuntimeError(f"Failed to fetch any FX series: {errors}")

    combined = pd.DataFrame(frames)
    combined.index.name = "date"
    return combined, errors


def fetch_gli_cb_fred(api_key: str, start_date: str = "2003-01-01") -> pd.DataFrame:
    """Fetch CB balance sheet series available on FRED (WALCL + JPNASSETS)."""
    series_to_fetch = {"WALCL": "Fed Total Assets", **GLI_CB_SERIES}
    frames = {}
    errors = {}
    for series_id in series_to_fetch:
        try:
            df = fetch_fred_series(series_id, start_date=start_date, api_key=api_key)
            frames[series_id] = df[series_id]
        except Exception as e:
            errors[series_id] = str(e)

    if not frames:
        raise RuntimeError(f"Failed to fetch any CB series: {errors}")

    combined = pd.DataFrame(frames)
    combined.index.name = "date"
    return combined, errors


def fetch_ecb_balance_sheet(start_date: str = "2003-01-01") -> pd.Series:
    """Fetch ECB total assets from ECB SDMX REST API (no key needed).

    Uses the ILM dataset: monthly total assets of the Eurosystem in EUR millions.
    """
    import requests

    url = (
        "https://data-api.ecb.europa.eu/service/data/ILM/"
        "M.U2.C.L010000.Z5.EUR"
    )
    params = {
        "format": "csvdata",
        "startPeriod": start_date[:7],  # YYYY-MM
    }

    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()

    from io import StringIO
    df = pd.read_csv(StringIO(resp.text))

    # ECB CSV has TIME_PERIOD and OBS_VALUE columns
    if "TIME_PERIOD" not in df.columns or "OBS_VALUE" not in df.columns:
        raise ValueError(f"Unexpected ECB CSV columns: {list(df.columns)}")

    df["date"] = pd.to_datetime(df["TIME_PERIOD"])
    df["ECB"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
    series = df.set_index("date")["ECB"].dropna().sort_index()
    series.name = "ECB"
    return series


def fetch_pboc_balance_sheet() -> pd.Series:
    """Fetch PBoC total assets from IMF IFS SDMX API.

    Uses the IFS dataset with indicator FAABC_XDC (central bank assets, national currency).
    Returns values in CNY billions.
    """
    import requests

    # IMF SDMX 2.1 REST API for IFS
    # Indicator: FAABC_XDC = "Claims on Other Depository Corporations" proxy for CB total assets
    # Ref area: CN (China), Frequency: M (Monthly)
    url = (
        "https://sdmxcentral.imf.org/ws/public/sdmxapi/rest/data/"
        "IFS/M.CN.FABC_XDC"
    )
    headers = {"Accept": "application/vnd.sdmx.data+csv;version=2.0.0"}

    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()

    from io import StringIO
    df = pd.read_csv(StringIO(resp.text))

    # SDMX CSV has TIME_PERIOD and OBS_VALUE
    time_col = "TIME_PERIOD" if "TIME_PERIOD" in df.columns else df.columns[-2]
    val_col = "OBS_VALUE" if "OBS_VALUE" in df.columns else df.columns[-1]

    df["date"] = pd.to_datetime(df[time_col])
    df["PBoC"] = pd.to_numeric(df[val_col], errors="coerce")
    series = df.set_index("date")["PBoC"].dropna().sort_index()
    series.name = "PBoC"
    return series
