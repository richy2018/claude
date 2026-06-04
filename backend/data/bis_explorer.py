"""BIS Explorer — generic fetcher for BIS SDMX dataflows.

Powers the interactive BIS Explorer tab. Fetches credit, FX, property,
and banking statistics from the BIS SDMX REST API v2 and returns
chart-ready JSON.

Dataset groups:
  - credit:   Total credit (WS_TC), credit-to-GDP gap (WS_CREDIT_GAP),
              debt service ratios (WS_DSR)
  - fx:       Effective exchange rates (WS_EER), policy rates (WS_CBPOL)
  - property: Residential (WS_SPP) & commercial property prices,
              consolidated/locational banking stats

On-demand fetch with 24h in-memory cache (managed by the endpoint layer).
"""

import requests
import pandas as pd
from io import StringIO
from datetime import date

BIS_API_BASE = "https://stats.bis.org/api/v2/data/dataflow/BIS"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
}

# Country code → display name (BIS reference area codes)
COUNTRY_NAMES = {
    "US": "United States", "XM": "Euro Area", "JP": "Japan",
    "GB": "United Kingdom", "DE": "Germany", "FR": "France",
    "IT": "Italy", "ES": "Spain", "CA": "Canada", "AU": "Australia",
    "KR": "Korea", "CN": "China", "BR": "Brazil", "IN": "India",
    "NL": "Netherlands", "CH": "Switzerland", "SE": "Sweden",
    "MX": "Mexico", "TR": "Turkey", "5R": "All reporting countries",
    "RU": "Russia", "ZA": "South Africa", "ID": "Indonesia",
    "SA": "Saudi Arabia", "HK": "Hong Kong", "SG": "Singapore",
}


def _fetch_bis_csv(dataflow, key, params=None):
    """Fetch one BIS series via the SDMX CSV endpoint.

    Returns a long-form DataFrame with columns [date, value, *dimensions]
    or an empty DataFrame on failure.
    """
    url = f"{BIS_API_BASE}/{dataflow}/{key}?format=csv"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=60)
        if resp.status_code != 200 or len(resp.text) < 100:
            print(f"[BIS-EXP] {dataflow}/{key}: HTTP {resp.status_code}, len={len(resp.text)}")
            return pd.DataFrame()

        df = pd.read_csv(StringIO(resp.text))

        # Locate time + value columns (BIS CSV uses TIME_PERIOD / OBS_VALUE)
        time_col = val_col = None
        for c in df.columns:
            cl = c.lower()
            if time_col is None and ("time_period" in cl or cl == "time" or "period" in cl):
                time_col = c
            if val_col is None and ("obs_value" in cl or cl == "value"):
                val_col = c

        if not time_col or not val_col:
            print(f"[BIS-EXP] {dataflow}/{key}: no time/value cols in {list(df.columns)[:6]}")
            return pd.DataFrame()

        df["date"] = pd.to_datetime(df[time_col].apply(_normalize_period), errors="coerce")
        df["value"] = pd.to_numeric(df[val_col], errors="coerce")
        df = df.dropna(subset=["date", "value"]).sort_values("date")
        return df

    except Exception as e:
        print(f"[BIS-EXP] {dataflow}/{key}: ERROR {e}")
        return pd.DataFrame()


def _normalize_period(p):
    """Normalize BIS period strings to a parseable date.

    BIS uses: '2025-Q3' (quarterly), '2025-07' (monthly), '2025' (annual),
    '2026-04-27' (daily). Quarter strings are mapped to quarter-end month.
    """
    s = str(p).strip()
    if "-Q" in s:
        year, q = s.split("-Q")
        # Map quarter to quarter-end month: Q1→03, Q2→06, Q3→09, Q4→12
        month = {"1": "03", "2": "06", "3": "09", "4": "12"}.get(q.strip(), "12")
        return f"{year}-{month}-01"
    return s


def _series_to_points(df, value_col="value"):
    """Convert a fetched DataFrame to [{date, value}] chart points."""
    points = []
    for _, row in df.iterrows():
        points.append({
            "date": row["date"].strftime("%Y-%m-%d"),
            "value": round(float(row[value_col]), 3),
        })
    return points


def _meta(df):
    """Build freshness metadata for a series."""
    if df.empty:
        return {"n_obs": 0, "latest": None, "days_behind": None}
    latest = df["date"].max()
    behind = (pd.Timestamp(date.today()) - latest).days
    return {
        "n_obs": int(len(df)),
        "latest": latest.strftime("%Y-%m-%d"),
        "days_behind": int(behind),
        "first": df["date"].min().strftime("%Y-%m-%d"),
    }


# ───────────────────────── CREDIT & DEBT ─────────────────────────────────

# Default countries for multi-country comparison charts
CREDIT_COUNTRIES = ["US", "XM", "JP", "GB", "CN", "5R"]


def fetch_credit(countries=None):
    """Total credit to non-financial sector (% of GDP) + credit-to-GDP gap
    + debt service ratios, for the given countries.

    Returns dict with per-indicator multi-country series.
    """
    countries = countries or CREDIT_COUNTRIES
    result = {"indicators": {}, "countries": {}, "as_of": {}}

    # 1. Total credit to non-financial sector, % of GDP (WS_TC, unit=770 pct GDP)
    #    Key: Q.{country}.C.A.M.770.A — borrower=C(all), valuation=M, unit=770(%GDP)
    credit_gdp = {}
    for c in countries:
        df = _fetch_bis_csv("WS_TC/2.0", f"Q.{c}.C.A.M.770.A")
        if not df.empty:
            credit_gdp[c] = _series_to_points(df)
            result["as_of"][f"credit_gdp_{c}"] = _meta(df)
    result["indicators"]["credit_to_gdp"] = credit_gdp

    # 2. Credit-to-GDP gap (WS_CREDIT_GAP) — early-warning indicator
    gap = {}
    for c in countries:
        df = _fetch_bis_csv("WS_CREDIT_GAP/1.0", f"Q.{c}.C")
        if not df.empty:
            gap[c] = _series_to_points(df)
            result["as_of"][f"gap_{c}"] = _meta(df)
    result["indicators"]["credit_gdp_gap"] = gap

    # 3. Debt service ratio, private non-financial sector (WS_DSR)
    dsr = {}
    for c in countries:
        df = _fetch_bis_csv("WS_DSR/1.0", f"Q.{c}.P.A")
        if not df.empty:
            dsr[c] = _series_to_points(df)
            result["as_of"][f"dsr_{c}"] = _meta(df)
    result["indicators"]["debt_service_ratio"] = dsr

    result["country_names"] = {c: COUNTRY_NAMES.get(c, c) for c in countries}
    return result


# ───────────────────────── FX RATES ──────────────────────────────────────

FX_COUNTRIES = ["US", "XM", "JP", "GB", "CN", "CH"]


def fetch_fx(countries=None):
    """Effective exchange rates (nominal & real, broad basket) + policy rates.

    Returns dict with NEER, REER, and policy rate series per country.
    """
    countries = countries or FX_COUNTRIES
    result = {"indicators": {}, "as_of": {}}

    # 1. Nominal effective exchange rate, broad (WS_EER, type=N, basket=B)
    #    Key: D.N.B.{country}  (Daily, Nominal, Broad)
    neer = {}
    for c in countries:
        df = _fetch_bis_csv("WS_EER/1.0", f"M.N.B.{c}")  # monthly to keep size sane
        if not df.empty:
            neer[c] = _series_to_points(df)
            result["as_of"][f"neer_{c}"] = _meta(df)
    result["indicators"]["neer_broad"] = neer

    # 2. Real effective exchange rate, broad (type=R)
    reer = {}
    for c in countries:
        df = _fetch_bis_csv("WS_EER/1.0", f"M.R.B.{c}")
        if not df.empty:
            reer[c] = _series_to_points(df)
            result["as_of"][f"reer_{c}"] = _meta(df)
    result["indicators"]["reer_broad"] = reer

    # 3. Central bank policy rates (WS_CBPOL) — monthly
    policy = {}
    for c in countries:
        df = _fetch_bis_csv("WS_CBPOL/1.0", f"M.{c}")
        if not df.empty:
            policy[c] = _series_to_points(df)
            result["as_of"][f"policy_{c}"] = _meta(df)
    result["indicators"]["policy_rate"] = policy

    result["country_names"] = {c: COUNTRY_NAMES.get(c, c) for c in countries}
    return result


# ───────────────────────── PROPERTY & BANKING ────────────────────────────

PROPERTY_COUNTRIES = ["US", "XM", "JP", "GB", "DE", "CN", "AU", "CA"]


def fetch_property(countries=None):
    """Residential property prices (real & nominal) + consolidated/locational
    banking claims.

    Returns dict with property price indices and banking series.
    """
    countries = countries or PROPERTY_COUNTRIES
    result = {"indicators": {}, "as_of": {}}

    # 1. Residential property prices, nominal index (WS_SPP, unit=628 index)
    #    Key: Q.{country}.N.628  (Quarterly, Nominal)
    rppi_nom = {}
    for c in countries:
        df = _fetch_bis_csv("WS_SPP/1.0", f"Q.{c}.N.628")
        if not df.empty:
            rppi_nom[c] = _series_to_points(df)
            result["as_of"][f"rppi_nom_{c}"] = _meta(df)
    result["indicators"]["residential_nominal"] = rppi_nom

    # 2. Residential property prices, real index (R)
    rppi_real = {}
    for c in countries:
        df = _fetch_bis_csv("WS_SPP/1.0", f"Q.{c}.R.771")
        if not df.empty:
            rppi_real[c] = _series_to_points(df)
            result["as_of"][f"rppi_real_{c}"] = _meta(df)
    result["indicators"]["residential_real"] = rppi_real

    # 3. Consolidated banking claims, total (WS_CBS_PUB) — immediate counterparty
    cbs = {}
    for c in countries:
        df = _fetch_bis_csv("WS_CBS_PUB/1.0", f"Q.S.{c}.4B.N.A.A.TO1.A.5J.N")
        if not df.empty:
            cbs[c] = _series_to_points(df)
            result["as_of"][f"cbs_{c}"] = _meta(df)
    result["indicators"]["banking_claims"] = cbs

    result["country_names"] = {c: COUNTRY_NAMES.get(c, c) for c in countries}
    return result


# Dispatcher
GROUP_FETCHERS = {
    "credit": fetch_credit,
    "fx": fetch_fx,
    "property": fetch_property,
}


def fetch_group(group, countries=None):
    """Fetch a dataset group by name. Returns chart-ready dict."""
    fn = GROUP_FETCHERS.get(group)
    if fn is None:
        return {"error": f"Unknown group '{group}'. Valid: {list(GROUP_FETCHERS)}"}
    return fn(countries)
