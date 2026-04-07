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
            print(f"[GLI Fed] {series_id}: {len(df)} obs, latest={df[series_id].iloc[-1]:.0f}")
        except Exception as e:
            errors[series_id] = str(e)
            print(f"[GLI Fed] {series_id}: FAILED - {e}")

    if not frames:
        raise RuntimeError(f"Failed to fetch any Fed liquidity series: {errors}")

    combined = pd.DataFrame(frames)
    combined.index.name = "date"
    print(f"[GLI Fed] Combined: {len(combined)} rows, columns={list(combined.columns)}, NaN counts: {combined.isna().sum().to_dict()}")
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

    Tries multiple IFS indicator codes for China CB total assets.
    Returns values in CNY billions (converted from IMF's native units).
    PBoC total assets ~45 trillion CNY ≈ 450,000 (in 100M CNY / 亿元).
    """
    import requests
    from io import StringIO

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    # Try multiple IMF IFS indicators for PBoC total assets
    indicators = [
        "FABC_XDC",    # Claims on other depository corps (CB assets proxy)
        "FABA_XDC",    # Total assets of central bank
        "RAFA_XDC",    # Reserve assets
    ]

    for indicator in indicators:
        try:
            url = f"https://sdmxcentral.imf.org/ws/public/sdmxapi/rest/data/IFS/M.CN.{indicator}"
            csv_headers = {**headers, "Accept": "application/vnd.sdmx.data+csv;version=2.0.0"}
            resp = requests.get(url, headers=csv_headers, timeout=60)
            print(f"[PBoC] {indicator}: status={resp.status_code}, len={len(resp.text)}")

            if resp.status_code == 200 and len(resp.text) > 100:
                df = pd.read_csv(StringIO(resp.text))
                time_col = next((c for c in df.columns if "TIME" in c.upper() or "PERIOD" in c.upper()), None)
                val_col = next((c for c in df.columns if "OBS" in c.upper() or "VALUE" in c.upper()), None)

                if time_col and val_col:
                    df["date"] = pd.to_datetime(df[time_col])
                    df["value"] = pd.to_numeric(df[val_col], errors="coerce")
                    series = df.set_index("date")["value"].dropna().sort_index()

                    if len(series) > 12:
                        # IMF IFS reports China data in CNY 100 millions (亿元)
                        # Convert to CNY billions: divide by 10
                        series = series / 10
                        series.name = "PBoC"
                        print(f"[PBoC] {indicator}: OK, {len(series)} obs, latest={series.iloc[-1]:.0f} CNY B")
                        return series
        except Exception as e:
            print(f"[PBoC] {indicator}: error: {e}")

    raise RuntimeError("Failed to fetch PBoC data from any IMF IFS indicator")


# BIS total credit country codes — broad coverage for diffusion index
BIS_CREDIT_COUNTRIES = {
    "US": "United States",
    "CN": "China",
    "JP": "Japan",
    "GB": "United Kingdom",
    "DE": "Germany",
    "FR": "France",
    "IT": "Italy",
    "ES": "Spain",
    "CA": "Canada",
    "AU": "Australia",
    "KR": "Korea",
    "BR": "Brazil",
    "IN": "India",
    "NL": "Netherlands",
    "CH": "Switzerland",
    "SE": "Sweden",
    "MX": "Mexico",
    "TR": "Turkey",
    "5R": "All reporting countries",
}


def _parse_sdmx_xml(xml_text: str) -> list:
    """Parse SDMX XML response into list of (period, value) tuples.

    Handles both GenericData and StructureSpecificData SDMX formats.
    """
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_text)
    observations = []

    # Iterate ALL elements looking for Obs (works regardless of namespace)
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        if tag == "Obs":
            period = None
            value = None

            # StructureSpecific format: attributes directly on Obs element
            period = elem.attrib.get("TIME_PERIOD", elem.attrib.get("TIME", None))
            value = elem.attrib.get("OBS_VALUE", None)

            # Generic format: child elements
            if period is None or value is None:
                for child in elem:
                    child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if child_tag == "ObsDimension":
                        period = child.attrib.get("value", period)
                    elif child_tag == "ObsValue":
                        value = child.attrib.get("value", value)
                    elif child_tag == "Attributes":
                        pass  # skip metadata attributes

            if period and value:
                try:
                    observations.append((period, float(value)))
                except (ValueError, TypeError):
                    pass

    return observations


def _parse_sdmx_json(json_text: str) -> list:
    """Parse SDMX-JSON response into list of (period, value) tuples."""
    import json as _json
    data = _json.loads(json_text)

    observations = []

    # SDMX-JSON structure: data.dataSets[0].series.{key}.observations.{idx}
    datasets = data.get("data", data).get("dataSets", [])
    # Get time dimension values
    dims = data.get("data", data).get("structure", {}).get("dimensions", {})
    obs_dims = dims.get("observation", [])

    # Find time dimension values
    time_values = {}
    for dim in obs_dims:
        if dim.get("id") in ("TIME_PERIOD", "TIME"):
            for i, val in enumerate(dim.get("values", [])):
                time_values[str(i)] = val.get("id", val.get("name", str(i)))
            break

    for ds in datasets:
        series_dict = ds.get("series", {})
        for series_key, series_data in series_dict.items():
            obs = series_data.get("observations", {})
            for idx_str, val_list in obs.items():
                period = time_values.get(idx_str, idx_str)
                if val_list and len(val_list) > 0 and val_list[0] is not None:
                    try:
                        observations.append((period, float(val_list[0])))
                    except (ValueError, TypeError):
                        pass

    return observations


def _fetch_bis_single(country_code: str, headers: dict) -> pd.Series:
    """Fetch BIS credit for one country using the SDMX REST API v2.

    Key structure: Q.{country}.C.A.M.USD.A
    - Q = Quarterly
    - C = Total credit (all borrowing sectors combined)
    - A = All lenders
    - M = Market value
    - USD = US Dollar (billions)
    - A = Adjusted for breaks
    """
    import requests
    from io import StringIO

    base_url = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_TC/2.0"
    key = f"Q.{country_code}.C.A.M.USD.A"

    # Try CSV format first
    csv_url = f"{base_url}/{key}?format=csv"
    try:
        resp = requests.get(csv_url, headers=headers, timeout=60)
        print(f"[BIS] {country_code}: CSV {resp.status_code}, type={resp.headers.get('Content-Type','?')}, len={len(resp.text)}")

        if resp.status_code == 200 and "text/csv" in resp.headers.get("Content-Type", ""):
            df = pd.read_csv(StringIO(resp.text))
            print(f"[BIS] {country_code}: CSV columns={list(df.columns)}")

            time_col = val_col = None
            for c in df.columns:
                cl = c.lower()
                if time_col is None and ("time_period" in cl or "period" in cl or "time" in cl):
                    time_col = c
                if val_col is None and ("obs_value" in cl or cl == "value"):
                    val_col = c

            if time_col and val_col:
                df["date"] = pd.to_datetime(df[time_col])
                df["value"] = pd.to_numeric(df[val_col], errors="coerce")
                series = df.set_index("date")["value"].dropna().sort_index()
                if len(series) > 0:
                    print(f"[BIS] {country_code}: OK, {len(series)} observations")
                    return series
    except Exception as e:
        print(f"[BIS] {country_code}: CSV error: {e}")

    # Try SDMX-JSON format
    json_url = f"{base_url}/{key}"
    json_headers = {**headers, "Accept": "application/vnd.sdmx.data+json;version=2.0.0"}
    try:
        resp = requests.get(json_url, headers=json_headers, timeout=60)
        print(f"[BIS] {country_code}: JSON {resp.status_code}, type={resp.headers.get('Content-Type','?')}, len={len(resp.text)}")

        if resp.status_code == 200:
            text = resp.text.strip()
            if text.startswith("{"):
                observations = _parse_sdmx_json(text)
                if observations:
                    print(f"[BIS] {country_code}: JSON parsed {len(observations)} obs")
                    dates = pd.to_datetime([o[0] for o in observations])
                    values = [o[1] for o in observations]
                    return pd.Series(values, index=dates).sort_index()
    except Exception as e:
        print(f"[BIS] {country_code}: JSON error: {e}")

    # Try SDMX-XML format
    xml_url = f"{base_url}/{key}"
    xml_headers = {**headers, "Accept": "application/xml"}
    try:
        resp = requests.get(xml_url, headers=xml_headers, timeout=60)
        print(f"[BIS] {country_code}: XML {resp.status_code}, type={resp.headers.get('Content-Type','?')}, len={len(resp.text)}")

        if resp.status_code == 200:
            text = resp.text.strip()
            if text.startswith("<?xml") or text.startswith("<"):
                observations = _parse_sdmx_xml(text)
                if observations:
                    print(f"[BIS] {country_code}: XML parsed {len(observations)} obs")
                    dates = pd.to_datetime([o[0] for o in observations])
                    values = [o[1] for o in observations]
                    return pd.Series(values, index=dates).sort_index()
                print(f"[BIS] {country_code}: XML 0 obs, first 300: {text[:300]}")
    except Exception as e:
        print(f"[BIS] {country_code}: XML error: {e}")

    raise RuntimeError(f"All BIS API formats failed for {country_code}")


def fetch_bis_credit() -> pd.DataFrame:
    """Fetch BIS total credit to non-financial sector.

    Key structure: Q.{country}.C.A.M.USD.A (quarterly, all sectors, USD billions).
    Uses stats.bis.org SDMX API with CSV/JSON/XML fallbacks.
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
