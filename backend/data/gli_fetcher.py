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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/csv,*/*",
    }

    resp = requests.get(url, params=params, headers=headers, timeout=60)
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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/vnd.sdmx.data+csv;version=2.0.0",
    }

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


def _parse_sdmx_xml(xml_text: str) -> list:
    """Parse SDMX XML response into list of (period, value) tuples."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_text)

    # SDMX uses namespaces — find all Obs elements regardless of namespace
    observations = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        if tag == "Obs":
            period = None
            value = None
            # Check attributes (compact format)
            period = elem.attrib.get("TIME_PERIOD") or elem.attrib.get("ObsDimension")
            value = elem.attrib.get("OBS_VALUE") or elem.attrib.get("ObsValue")

            # Check child elements (generic format)
            for child in elem:
                child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if child_tag == "ObsDimension":
                    period = child.attrib.get("value", period)
                elif child_tag == "ObsValue":
                    value = child.attrib.get("value", value)
                elif child_tag == "Time" or child_tag == "TimeDimension":
                    period = child.text or child.attrib.get("value", period)
                elif child_tag == "Value" and "value" in child.attrib:
                    value = child.attrib.get("value", value)

            if period and value:
                try:
                    observations.append((period, float(value)))
                except (ValueError, TypeError):
                    pass

    return observations


def _fetch_bis_single(country_code: str, headers: dict) -> pd.Series:
    """Fetch BIS credit for one country from data.bis.org, parsing XML response."""
    import requests

    url = (
        f"https://data.bis.org/topics/TOTAL_CREDIT/"
        f"BIS,WS_TC,2.0/Q.{country_code}.C.A.M.770.A"
    )

    resp = requests.get(url, headers=headers, timeout=60)
    print(f"[BIS] {country_code}: {resp.status_code}, content-type={resp.headers.get('Content-Type', '?')}, len={len(resp.text)}")

    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} for {country_code}")

    text = resp.text.strip()

    # Check if response is XML (SDMX format)
    if text.startswith("<?xml") or text.startswith("<"):
        observations = _parse_sdmx_xml(text)
        if not observations:
            raise RuntimeError(f"No observations found in SDMX XML for {country_code} (response length: {len(text)})")

        print(f"[BIS] {country_code}: parsed {len(observations)} observations from XML")
        dates = pd.to_datetime([o[0] for o in observations])
        values = [o[1] for o in observations]
        series = pd.Series(values, index=dates).sort_index()
        return series

    # Try CSV parsing as fallback
    from io import StringIO
    df = pd.read_csv(StringIO(text))
    print(f"[BIS] {country_code}: CSV columns={list(df.columns)}, rows={len(df)}")

    time_col = val_col = None
    for c in df.columns:
        cl = c.lower()
        if time_col is None and ("time_period" in cl or "period" in cl):
            time_col = c
        if val_col is None and ("obs_value" in cl or cl == "value"):
            val_col = c

    if time_col and val_col:
        df["date"] = pd.to_datetime(df[time_col])
        df["value"] = pd.to_numeric(df[val_col], errors="coerce")
        series = df.set_index("date")["value"].dropna().sort_index()
        if len(series) > 0:
            return series

    raise RuntimeError(f"Could not parse BIS response for {country_code}")


def fetch_bis_credit() -> pd.DataFrame:
    """Fetch BIS total credit to non-financial sector from data.bis.org.

    Key structure: Q.{country}.C.A.M.770.A (quarterly, all sectors, USD billions).
    Response is SDMX XML which we parse directly.
    """
    all_data = {}
    errors = {}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }

    for country_code, country_name in BIS_CREDIT_COUNTRIES.items():
        try:
            series = _fetch_bis_single(country_code, headers)
            series.name = country_name
            all_data[country_name] = series
        except Exception as e:
            errors[country_code] = str(e)
            print(f"[BIS] FAILED {country_code}: {e}")

    if not all_data:
        raise RuntimeError(f"Failed to fetch any BIS credit data: {errors}")

    combined = pd.DataFrame(all_data)
    combined.index.name = "date"
    return combined, errors
