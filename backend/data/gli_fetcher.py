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


# BIS total credit country codes for major economies
BIS_CREDIT_COUNTRIES = {
    "US": "United States",
    "GB": "United Kingdom",
    "JP": "Japan",
    "CN": "China",
    "DE": "Germany",
    "FR": "France",
    "CA": "Canada",
    "AU": "Australia",
    "KR": "Korea",
    "5R": "All reporting countries",
}


def fetch_bis_credit() -> pd.DataFrame:
    """Fetch BIS total credit to non-financial sector from BIS Data Portal.

    Uses the WS_TC dataflow v2.0. Fetches quarterly data for major economies.
    Key structure: Q.{country}.C.A.M.770.A
    - Q = Quarterly
    - C = All sectors (borrowers)
    - A = All sectors (lenders)
    - M = Market value
    - 770 = USD billions
    - A = Adjusted for breaks
    """
    import requests
    from io import StringIO

    all_data = {}
    errors = {}

    for country_code, country_name in BIS_CREDIT_COUNTRIES.items():
        try:
            url = (
                f"https://data.bis.org/topics/TOTAL_CREDIT/"
                f"BIS,WS_TC,2.0/Q.{country_code}.C.A.M.770.A"
            )
            params = {
                "file_format": "csv",
                "format": "long",
                "include": "code,label",
            }
            resp = requests.get(url, params=params, timeout=60)
            resp.raise_for_status()

            df = pd.read_csv(StringIO(resp.text))

            # BIS CSV typically has TIME_PERIOD and OBS_VALUE
            time_col = "TIME_PERIOD" if "TIME_PERIOD" in df.columns else None
            val_col = "OBS_VALUE" if "OBS_VALUE" in df.columns else None

            if time_col is None or val_col is None:
                # Try alternative column names
                for c in df.columns:
                    if "period" in c.lower() or "time" in c.lower():
                        time_col = c
                    if "value" in c.lower() or "obs" in c.lower():
                        val_col = c

            if time_col and val_col:
                df["date"] = pd.to_datetime(df[time_col])
                df["value"] = pd.to_numeric(df[val_col], errors="coerce")
                series = df.set_index("date")["value"].dropna().sort_index()
                series.name = country_name
                all_data[country_name] = series
        except Exception as e:
            errors[country_code] = str(e)

    if not all_data:
        raise RuntimeError(f"Failed to fetch any BIS credit data: {errors}")

    combined = pd.DataFrame(all_data)
    combined.index.name = "date"
    return combined, errors
