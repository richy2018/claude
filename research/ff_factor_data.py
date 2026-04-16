"""
Fama-French factor data loader.

Fetches monthly FF5 factors + Momentum factor from Kenneth French's
data library and caches to CSV locally.

FF CSV format quirks handled:
  - Multi-line header (copyright/description)
  - Date column is YYYYMM integer
  - Returns are in PERCENT (divided by 100 here)
  - Monthly rows are followed by an "Annual Factors:" section that must
    be dropped
  - Latin-1 encoding (some special characters in header)
"""

import io
import os
import zipfile
import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(__file__), "output", "ff_cache")

FF5_URL = ("https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
           "F-F_Research_Data_5_Factors_2x3_CSV.zip")
MOM_URL = ("https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
           "F-F_Momentum_Factor_CSV.zip")

FF5_COLS = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"]
MOM_COL = "Mom"


def _http_get_zip(url, timeout=30):
    """Download a zip file from Ken French's data library."""
    import requests
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GLI-Research/2.0)",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return zipfile.ZipFile(io.BytesIO(resp.content))


def _parse_ff_csv(content_bytes):
    """Parse a Fama-French CSV into a DataFrame of monthly returns.

    Returns DataFrame indexed by month-start dates, returns as decimals.
    Drops the annual-factors section after the monthly rows.
    """
    text = content_bytes.decode("latin-1")
    lines = text.split("\n")

    # Find the header line — typically contains "Mkt-RF" or "Mom"
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        parts = [p.strip() for p in stripped.split(",")]
        # Header line has column names, all after the blank leading col
        if any(col in parts for col in ("Mkt-RF", "Mom")):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("Could not locate FF CSV header row")

    # Build CSV from header onward, stopping at "Annual Factors" or blank run
    data_lines = [lines[header_idx]]
    for line in lines[header_idx + 1:]:
        s = line.strip()
        if not s:
            continue
        # Stop when we hit "Annual" or any non-numeric date
        if "Annual" in s:
            break
        first = s.split(",")[0].strip()
        if not first.isdigit() or len(first) != 6:
            # Not a YYYYMM row — stop
            break
        data_lines.append(line)

    csv_text = "\n".join(data_lines)
    df = pd.read_csv(io.StringIO(csv_text))

    # First column is the date (unnamed in FF CSVs)
    date_col = df.columns[0]
    df = df.rename(columns={date_col: "YYYYMM"})
    df["YYYYMM"] = df["YYYYMM"].astype(str).str.strip()
    df = df[df["YYYYMM"].str.match(r"^\d{6}$")]

    df["date"] = pd.to_datetime(df["YYYYMM"] + "01", format="%Y%m%d")
    df = df.set_index("date").drop(columns=["YYYYMM"])

    # Convert percent -> decimal
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce") / 100.0

    return df.sort_index()


def _ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def fetch_ff5_factors(force_refresh=False):
    """Fetch FF5 monthly factors (Mkt-RF, SMB, HML, RMW, CMA, RF)."""
    _ensure_cache_dir()
    cache = os.path.join(CACHE_DIR, "ff5.csv")

    if not force_refresh and os.path.exists(cache):
        df = pd.read_csv(cache, parse_dates=["date"]).set_index("date")
        return df

    z = _http_get_zip(FF5_URL)
    fname = z.namelist()[0]
    with z.open(fname) as f:
        content = f.read()

    df = _parse_ff_csv(content)
    missing = [c for c in FF5_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"FF5 CSV missing columns: {missing}")
    df = df[FF5_COLS]

    df.reset_index().to_csv(cache, index=False)
    return df


def fetch_ff_momentum(force_refresh=False):
    """Fetch Momentum (Mom) monthly factor."""
    _ensure_cache_dir()
    cache = os.path.join(CACHE_DIR, "ff_mom.csv")

    if not force_refresh and os.path.exists(cache):
        df = pd.read_csv(cache, parse_dates=["date"]).set_index("date")
        return df

    z = _http_get_zip(MOM_URL)
    fname = z.namelist()[0]
    with z.open(fname) as f:
        content = f.read()

    df = _parse_ff_csv(content)
    # Momentum column is often named "Mom" but sometimes shipped with
    # trailing whitespace — normalize
    df.columns = [c.strip() for c in df.columns]
    if MOM_COL not in df.columns:
        # Fall back to the first numeric column
        df = df.rename(columns={df.columns[0]: MOM_COL})
    df = df[[MOM_COL]]

    df.reset_index().to_csv(cache, index=False)
    return df


def load_ff_factors(force_refresh=False):
    """Load combined FF5 + Momentum factor DataFrame.

    Returns:
        DataFrame indexed by month-start dates with columns:
          Mkt-RF, SMB, HML, RMW, CMA, RF, Mom (all decimals)
    """
    ff5 = fetch_ff5_factors(force_refresh=force_refresh)
    mom = fetch_ff_momentum(force_refresh=force_refresh)
    merged = ff5.join(mom, how="inner")
    return merged
