"""Dollar Stress Index — parse cross-currency basis swap data from Bloomberg gist."""

import re
import numpy as np
import pandas as pd
import requests
from io import StringIO

GIST_URL = "https://gist.githubusercontent.com/richy2018/9c08bff76ae15e1a344e948c549c771d/raw"
GIST_PAGE_URL = "https://gist.github.com/richy2018/9c08bff76ae15e1a344e948c549c771d"

# GDP-weighted currency pair importance for dollar stress
CURRENCY_WEIGHTS = {
    "EUR/USD": 0.35,
    "JPY/USD": 0.25,
    "GBP/USD": 0.15,
    "CHF/USD": 0.15,
    "KRW/USD": 0.10,
}

CURRENCIES = list(CURRENCY_WEIGHTS.keys())


def _parse_date(s):
    """Parse dates in MM/DD/YYYY or MM.DD.YYYY format."""
    s = str(s).strip()
    for fmt in ["%m/%d/%Y", "%m.%d.%Y", "%m/%d/%y", "%m.%d.%y", "%Y-%m-%d"]:
        try:
            return pd.Timestamp(pd.to_datetime(s, format=fmt))
        except (ValueError, TypeError):
            continue
    try:
        return pd.Timestamp(pd.to_datetime(s))
    except Exception:
        return None


def fetch_dollar_stress_gist():
    """Fetch raw gist text. Tries raw URL first, then page scraping."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # Try raw URL
    try:
        resp = requests.get(GIST_URL, headers=headers, timeout=30)
        if resp.status_code == 200 and len(resp.text) > 500:
            print(f"[DollarStress] Fetched gist raw: {len(resp.text)} chars")
            return resp.text
    except Exception as e:
        print(f"[DollarStress] Raw URL failed: {e}")

    # Try page URL and extract from HTML
    try:
        resp = requests.get(GIST_PAGE_URL, headers=headers, timeout=30)
        if resp.status_code == 200:
            # Extract raw content from the gist page
            # Look for the raw file content between specific markers
            text = resp.text
            # Find the raw blob content
            start = text.find('class="blob-code')
            if start > 0:
                # Extract all lines
                lines = re.findall(r'<td[^>]*class="blob-code[^"]*"[^>]*>(.*?)</td>', text)
                if lines:
                    # Clean HTML tags
                    clean = []
                    for line in lines:
                        line = re.sub(r'<[^>]+>', '', line)
                        line = line.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&#39;', "'")
                        clean.append(line)
                    raw_text = "\n".join(clean)
                    print(f"[DollarStress] Extracted from page: {len(raw_text)} chars, {len(clean)} lines")
                    return raw_text
    except Exception as e:
        print(f"[DollarStress] Page fetch failed: {e}")

    raise RuntimeError("Failed to fetch dollar stress gist data")


def parse_basis_swaps(text):
    """Parse 5 currency pairs from the gist text.

    Each line has up to 10 columns: 5 pairs × (date, value).
    Parse by column position, not sequentially, to handle gaps.
    """
    lines = text.strip().split("\n")

    # Find header line
    header_idx = None
    for i, line in enumerate(lines):
        if "EUR/USD" in line and "JPY/USD" in line:
            header_idx = i
            break

    if header_idx is None:
        raise ValueError("Could not find header row with currency pair names")

    results = {c: [] for c in CURRENCIES}

    for line in lines[header_idx + 1:]:
        # Strip annotation text
        line = re.sub(r'<-.*$', '', line).strip()
        line = re.sub(r'←.*$', '', line).strip()
        if not line or line.startswith('#'):
            continue

        # Split by tabs first (most reliable), fall back to multi-space
        if '\t' in line:
            parts = line.split('\t')
        else:
            parts = re.split(r'\s{2,}', line)
        parts = [p.strip() for p in parts]

        # Pad to at least 10 columns
        while len(parts) < 10:
            parts.append('')

        # Parse each currency pair by column position
        # Columns: 0=EUR_date, 1=EUR_val, 2=JPY_date, 3=JPY_val, etc.
        for pair_idx, ccy in enumerate(CURRENCIES):
            date_col = pair_idx * 2
            val_col = pair_idx * 2 + 1
            if date_col >= len(parts) or val_col >= len(parts):
                continue
            date_str = parts[date_col].strip()
            val_str = parts[val_col].strip()
            if not date_str or not val_str:
                continue
            date = _parse_date(date_str)
            if date is None:
                continue
            try:
                val = float(val_str.replace(',', ''))
                results[ccy].append((date, val))
            except (ValueError, TypeError):
                continue

    # Convert to Series
    swaps = {}
    for ccy in CURRENCIES:
        if results[ccy]:
            dates, vals = zip(*results[ccy])
            s = pd.Series(vals, index=pd.DatetimeIndex(dates), dtype=float)
            s = s.sort_index()
            s = s[~s.index.duplicated(keep='last')]
            swaps[ccy] = s
            print(f"[DollarStress] {ccy}: {len(s)} obs, {s.index[0].strftime('%Y-%m')} to {s.index[-1].strftime('%Y-%m')}, latest={s.iloc[-1]:.2f} bp")

    return swaps


def build_dollar_stress_index(swaps):
    """Build weighted Dollar Stress Index from parsed basis swap data.

    Higher values = MORE dollar stress (tighter offshore dollar conditions).
    """
    # Resample each to monthly (last observation) — NO forward-fill
    # Missing months stay as NaN so they're excluded from the composite
    monthly = {}
    for ccy, s in swaps.items():
        m = s.resample("MS").last()  # NaN for months with no observation
        # Do NOT ffill — stale values should not contaminate the composite
        monthly[ccy] = m
        valid = m.dropna()
        gaps = m.isna().sum()
        print(f"[DollarStress] {ccy} monthly: {len(valid)} valid, {gaps} gaps")

    # Build weighted index — re-weight if some currencies missing
    all_dates = sorted(set().union(*[set(m.index) for m in monthly.values()]))
    index_values = []

    for date in all_dates:
        total_weight = 0
        weighted_sum = 0
        for ccy in CURRENCIES:
            if ccy in monthly and date in monthly[ccy].index:
                val = monthly[ccy][date]
                if pd.notna(val):
                    w = CURRENCY_WEIGHTS[ccy]
                    # Invert: more negative basis = higher stress score
                    stress = -1 * val
                    weighted_sum += w * stress
                    total_weight += w

        if total_weight > 0:
            # Re-weight to sum to 1.0
            index_values.append((date, weighted_sum / total_weight))

    if not index_values:
        raise ValueError("No valid data points for Dollar Stress Index")

    dates, vals = zip(*index_values)
    index = pd.Series(vals, index=pd.DatetimeIndex(dates), dtype=float, name="DollarStress")
    index = index.sort_index()

    print(f"[DollarStress] Index: {len(index)} months, {index.index[0].strftime('%Y-%m')} to {index.index[-1].strftime('%Y-%m')}")
    print(f"[DollarStress] Latest: {index.iloc[-1]:.2f} (higher = more stress)")

    return index


def get_dollar_stress():
    """Fetch, parse, and build Dollar Stress Index. Returns monthly pd.Series."""
    text = fetch_dollar_stress_gist()
    swaps = parse_basis_swaps(text)
    index = build_dollar_stress_index(swaps)
    return index


def get_dollar_stress_with_swaps():
    """Fetch, parse, and return both the index and raw swap data for charting."""
    text = fetch_dollar_stress_gist()
    swaps = parse_basis_swaps(text)
    index = build_dollar_stress_index(swaps)

    # Build chart data with NaN gaps preserved (Recharts will break the line)
    swap_chart = {}
    for ccy, s in swaps.items():
        m = s.resample("MS").last()  # Keep NaN for missing months
        points = []
        for d, v in m.items():
            points.append({"date": d.strftime("%Y-%m-%d"), "value": float(v) if pd.notna(v) else None})
        swap_chart[ccy] = points

    return index, swap_chart
