"""Dollar Stress Index — parse cross-currency basis swap data from Bloomberg gist."""

import re
import numpy as np
import pandas as pd
import requests
from io import StringIO

GIST_URL = "https://gist.githubusercontent.com/richy2018/9c08bff76ae15e1a344e948c549c771d/raw"
GIST_PAGE_URL = "https://gist.github.com/richy2018/9c08bff76ae15e1a344e948c549c771d"

# Original 5-pair weights (proven). CNY at 0% = monitored but not in signal.
CURRENCY_WEIGHTS = {
    "EUR/USD": 0.35,
    "JPY/USD": 0.25,
    "GBP/USD": 0.15,
    "CHF/USD": 0.15,
    "KRW/USD": 0.10,
    "CNY/USD": 0.00,   # Keep in data/charts but exclude from signal
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


def _parse_row_stride(parts):
    """Pass 1: Try 3-column stride (date, value, separator per pair).

    Gist layout: 6 pairs × 3-column blocks (date, value, empty tab).
    EUR_date, EUR_val, '', JPY_date, JPY_val, '', GBP_date, GBP_val, '', ...
    Returns list of (pair_idx, date, value) tuples found.
    """
    found = []
    for pair_idx in range(len(CURRENCIES)):
        date_col = pair_idx * 3
        val_col = pair_idx * 3 + 1
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
            found.append((pair_idx, date, val))
        except (ValueError, TypeError):
            continue
    return found


def _parse_row_scan(parts):
    """Pass 2: Date-scanning fallback for misaligned rows.

    Walk tokens, find each date, take the next token as value.
    Assign to currency pairs in order (1st date→EUR, 2nd→JPY, etc.).
    """
    found = []
    pair_idx = 0
    i = 0
    while i < len(parts) and pair_idx < len(CURRENCIES):
        token = parts[i].strip()
        if not token:
            i += 1
            continue
        date = _parse_date(token)
        if date is not None:
            # Look for value in the next non-empty token
            j = i + 1
            while j < len(parts) and not parts[j].strip():
                j += 1
            if j < len(parts):
                val_str = parts[j].strip()
                try:
                    val = float(val_str.replace(',', ''))
                    found.append((pair_idx, date, val))
                    pair_idx += 1
                    i = j + 1
                    continue
                except (ValueError, TypeError):
                    pass
        i += 1
    return found


def parse_basis_swaps(text):
    """Parse 6 currency pairs from the gist text.

    Uses a two-pass approach per row:
      Pass 1 (stride): Try fixed 3-column-wide blocks per pair (date, value, separator).
      Pass 2 (scan):   If stride yields < 2 pairs, scan for date tokens
                        and assign value from the next token in sequence.
    """
    lines = text.strip().split("\n")

    # Log column mapping for diagnostics
    print("[DollarStress] Column mapping (3-col stride: date, value, separator):")
    for pair_idx, ccy in enumerate(CURRENCIES):
        print(f"  {ccy}: date_col={pair_idx * 3}, val_col={pair_idx * 3 + 1}")

    # Find header line
    header_idx = None
    for i, line in enumerate(lines):
        if "EUR/USD" in line and "JPY/USD" in line:
            header_idx = i
            break

    if header_idx is None:
        raise ValueError("Could not find header row with currency pair names")

    results = {c: [] for c in CURRENCIES}
    _logged_first_row = False

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

        # Pad for stride-based parsing (6 pairs × 3 cols: date, value, separator)
        while len(parts) < 18:
            parts.append('')

        # Pass 1: stride-based (works for well-formatted rows)
        found = _parse_row_stride(parts)

        # Pass 2: if stride found < 2 pairs, fall back to date-scanning
        if len(found) < 2:
            scan_found = _parse_row_scan(parts)
            if len(scan_found) > len(found):
                found = scan_found

        # Log first successfully parsed row for diagnostics
        if not _logged_first_row and len(found) >= 3:
            _logged_first_row = True
            print(f"[DollarStress] First parsed row ({len(parts)} cols): {parts[:20]}")
            for pi, dt, vl in found:
                print(f"  {CURRENCIES[pi]}: col[{pi*3}]={dt.strftime('%Y-%m-%d')}, col[{pi*3+1}]={vl:.2f}")

        # Accumulate results
        for pair_idx, date, val in found:
            results[CURRENCIES[pair_idx]].append((date, val))

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

    # Post-parse validation: warn if any pair ends early
    if swaps:
        most_recent = max(s.index[-1] for s in swaps.values())
        for ccy, s in swaps.items():
            gap = (most_recent - s.index[-1]).days
            if gap > 14:
                print(f"[DollarStress] WARNING: {ccy} last date {s.index[-1].strftime('%Y-%m-%d')} is {gap} days behind most recent ({most_recent.strftime('%Y-%m-%d')})")

    return swaps


def chain_link_pairs(swaps):
    """Resample each pair to monthly for chart series.

    For EUR/JPY/GBP/CHF: forward-fill short gaps (LIBOR→SOFR transition).
    For KRW: do NOT forward-fill — show gaps as null so the chart line breaks.
    """
    if not swaps:
        return {}

    monthly = {}
    for ccy, s in swaps.items():
        # Handle stale cache: s may be a list-of-dicts from old JSON cache
        if isinstance(s, list):
            df = pd.DataFrame(s)
            if 'date' in df.columns and 'value' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                s = df.set_index('date')['value'].dropna().astype(float)
            else:
                continue
        monthly[ccy] = s.resample("MS").last().dropna()

    all_starts = [m.index.min() for m in monthly.values()]
    all_ends = [m.index.max() for m in monthly.values()]
    full_range = pd.date_range(min(all_starts), max(all_ends), freq="MS")

    result = {}
    for ccy, m in monthly.items():
        reindexed = m.reindex(full_range)
        if ccy in ("KRW/USD", "CNY/USD"):
            # KRW/CNY: only fill gaps up to 2 months, leave longer gaps as NaN
            result[ccy] = reindexed.ffill(limit=2)
        else:
            # Other pairs: forward-fill through LIBOR→SOFR transition gap
            result[ccy] = reindexed.ffill()
    return result


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


def build_dollar_stress_index_custom(swaps, weights):
    """Build Dollar Stress Index with custom weights (for optimizer)."""
    monthly = {}
    for ccy, s in swaps.items():
        monthly[ccy] = s.resample("MS").last()

    all_dates = sorted(set().union(*[set(m.index) for m in monthly.values()]))
    index_values = []
    for date in all_dates:
        total_weight = 0
        weighted_sum = 0
        for ccy, w in weights.items():
            if ccy in monthly and date in monthly[ccy].index:
                val = monthly[ccy][date]
                if pd.notna(val):
                    stress = -1 * val
                    weighted_sum += w * stress
                    total_weight += w
        if total_weight > 0:
            index_values.append((date, weighted_sum / total_weight))

    if not index_values:
        return pd.Series(dtype=float)
    dates, vals = zip(*index_values)
    return pd.Series(vals, index=pd.DatetimeIndex(dates), dtype=float).sort_index()


def optimize_currency_weights(swaps, spy_monthly, signal_type="mom6"):
    """Find currency weights that maximize Dollar Stress Index's
    standalone correlation with SPY 6M forward returns."""
    from scipy.optimize import minimize as sp_minimize
    from scipy import stats as sp_stats

    # Prepare monthly swap data
    monthly_swaps = {}
    for ccy, s in swaps.items():
        monthly_swaps[ccy] = s.resample("MS").last()

    currencies = list(monthly_swaps.keys())
    n = len(currencies)
    spy_fwd = spy_monthly.pct_change(6).shift(-6) * 100

    # Signal transform functions
    def _mom6(s): return s.diff(6)
    def _mom3(s): return s.diff(3)
    def _z36(s):
        m = s.rolling(36, min_periods=12).mean()
        st = s.rolling(36, min_periods=12).std().replace(0, np.nan)
        return ((s - m) / st).clip(-3, 3)
    transforms = {"mom6": _mom6, "mom3": _mom3, "z36": _z36, "level": lambda s: s}
    tfn = transforms.get(signal_type, _mom6)

    def _objective(weights):
        w_dict = {currencies[i]: weights[i] for i in range(n)}
        ds = build_dollar_stress_index_custom(swaps, w_dict)
        sig = tfn(ds).dropna()
        common = sig.index.intersection(spy_fwd.dropna().index)
        if len(common) < 30:
            return 0
        return float(np.corrcoef(sig.reindex(common), spy_fwd.reindex(common))[0, 1])

    bounds = [(0.0, 1.0)] * n
    constraints = [{'type': 'eq', 'fun': lambda w: sum(w) - 1.0}]
    x0 = [1.0 / n] * n

    result = sp_minimize(_objective, x0, method='SLSQP',
                         bounds=bounds, constraints=constraints,
                         options={'maxiter': 500})

    opt_weights = {currencies[i]: round(float(result.x[i]), 4) for i in range(n)}
    opt_corr = round(float(result.fun), 4)

    # Also compute equal-weight and GDP-weight correlations for comparison
    eq_w = {c: 1.0/n for c in currencies}
    eq_ds = build_dollar_stress_index_custom(swaps, eq_w)
    eq_sig = tfn(eq_ds).dropna()
    eq_common = eq_sig.index.intersection(spy_fwd.dropna().index)
    eq_corr = round(float(np.corrcoef(eq_sig.reindex(eq_common), spy_fwd.reindex(eq_common))[0, 1]), 4) if len(eq_common) >= 30 else None

    gdp_ds = build_dollar_stress_index_custom(swaps, CURRENCY_WEIGHTS)
    gdp_sig = tfn(gdp_ds).dropna()
    gdp_common = gdp_sig.index.intersection(spy_fwd.dropna().index)
    gdp_corr = round(float(np.corrcoef(gdp_sig.reindex(gdp_common), spy_fwd.reindex(gdp_common))[0, 1]), 4) if len(gdp_common) >= 30 else None

    print(f"[CcyOpt] Optimized: {opt_weights}, corr={opt_corr}")
    print(f"[CcyOpt] Equal-weight corr={eq_corr}, GDP-weight corr={gdp_corr}")

    # Walk-forward stability (96M train, 24M test)
    stability = []
    all_dates = sorted(set().union(*[set(m.index) for m in monthly_swaps.values()]))
    for start in range(0, len(all_dates) - 120, 24):
        train = all_dates[start:start + 96]
        test = all_dates[start + 96:start + 120]
        if len(test) < 12:
            break
        train_idx = pd.DatetimeIndex(train)
        test_idx = pd.DatetimeIndex(test)

        # Optimize on training window
        def _train_obj(weights):
            w_dict = {currencies[i]: weights[i] for i in range(n)}
            ds = build_dollar_stress_index_custom(swaps, w_dict)
            sig = tfn(ds).dropna()
            common = sig.index.intersection(spy_fwd.dropna().index).intersection(train_idx)
            if len(common) < 20:
                return 0
            return float(np.corrcoef(sig.reindex(common), spy_fwd.reindex(common))[0, 1])

        try:
            res = sp_minimize(_train_obj, x0, method='SLSQP',
                              bounds=bounds, constraints=constraints,
                              options={'maxiter': 200})
            window_w = {currencies[i]: round(float(res.x[i]), 3) for i in range(n)}
        except Exception:
            window_w = eq_w

        # Test OOS
        ds_test = build_dollar_stress_index_custom(swaps, window_w)
        sig_test = tfn(ds_test).dropna()
        test_common = sig_test.index.intersection(spy_fwd.dropna().index).intersection(test_idx)
        oos = round(float(np.corrcoef(sig_test.reindex(test_common), spy_fwd.reindex(test_common))[0, 1]), 4) if len(test_common) >= 10 else None

        stability.append({
            "period": f"{train[0].strftime('%Y')}-{train[-1].strftime('%Y')} / {test[0].strftime('%Y')}-{test[-1].strftime('%Y')}",
            "weights": window_w,
            "oos_corr": oos,
        })

    return {
        "optimized_weights": opt_weights,
        "optimized_corr": opt_corr,
        "equal_weight_corr": eq_corr,
        "gdp_weight_corr": gdp_corr,
        "stability": stability,
    }
    """Fetch, parse, and build Dollar Stress Index. Returns monthly pd.Series."""
    text = fetch_dollar_stress_gist()
    swaps = parse_basis_swaps(text)
    index = build_dollar_stress_index(swaps)
    return index


def get_dollar_stress_with_swaps():
    """Fetch, parse, and return both the index and raw weekly swap data for charting."""
    text = fetch_dollar_stress_gist()
    swaps = parse_basis_swaps(text)
    index = build_dollar_stress_index(swaps)

    # Return RAW WEEKLY data for charts (not monthly resampled)
    # NaN gaps preserved — Recharts will break the line at null values
    swap_chart = {}
    for ccy, s in swaps.items():
        points = []
        for d, v in s.items():
            points.append({"date": d.strftime("%Y-%m-%d"), "value": float(v) if pd.notna(v) else None})
        swap_chart[ccy] = points

    return index, swap_chart
