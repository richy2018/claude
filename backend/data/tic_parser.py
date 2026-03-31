"""TIC Major Foreign Holders of Treasury Securities — data parser.

The TIC file is tab-delimited with yearly blocks. Each block has:
- A header row with month names: [empty]\tDec\tNov\t...\tJan
- A year row: Country\t2025\t2025\t...\t2025
- Country data rows: Japan\t1185.5\t1202.7\t...\t1079.3
- Aggregate rows: Grand Total, For. Official, Treasury Bills, T-Bonds & Notes

For years with benchmark survey revisions (series breaks), there are
13+ columns with duplicate June entries. We keep only the newer series.
"""

import json
import re
from pathlib import Path
from datetime import datetime

MONTH_MAP = {
    'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
    'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12,
}

AGGREGATE_MAP = {
    'Grand Total': 'Grand Total',
    'For. Official': 'Official',
    'For. official': 'Official',
    'Treasury Bills': 'Treasury Bills',
    'T-Bonds & Notes': 'T-Bonds & Notes',
}


def _clean_name(raw):
    """Extract and normalize a country name from the first tab field."""
    name = raw.strip().strip('"').strip()
    name = re.sub(r'\s*\d+/\s*$', '', name)  # Remove footnote markers like "2/"
    name = name.strip()
    if name.startswith('Korea') and 'South' in name:
        return 'Korea, South'
    if name.startswith('China') and 'Mainland' in name:
        return 'China, Mainland'
    return name


def _parse_value(v):
    """Parse a cell value to float or None."""
    v = v.strip()
    if not v or v == '*' or v.lower() == 'n.a.' or v in ('--', '---', '------'):
        return None
    try:
        return float(v.replace(',', ''))
    except ValueError:
        return None


def _is_skip_line(line):
    """Check if a line should be skipped entirely."""
    s = line.strip()
    if not s:
        return True
    if s.startswith('------'):
        return True
    if s.startswith('Series ') or s.startswith('Series\t'):
        return True
    if 'MAJOR FOREIGN' in s or 'HOLDINGS' in s or 'in billions' in s:
        return True
    if s.startswith('Department') or s.startswith('*') or s.startswith('('):
        return True
    if s.startswith('"(') or 'revised' in s.lower():
        return True
    if any(s.startswith(f'{n}/') for n in range(1, 20)):
        return True
    if 'treasury.gov' in s.lower() or 'TIC FAQ' in s:
        return True
    return False


def parse_tic_text(raw_text: str) -> dict:
    """Parse the TIC Major Foreign Holders text file."""
    lines = raw_text.split('\n')

    countries = {}   # {name: {date_str: value}}
    aggregates = {'Grand Total': {}, 'Official': {}, 'Treasury Bills': {}, 'T-Bonds & Notes': {}}

    # current_dates: ordered list of date strings for the current block
    # These correspond to the data values in each row (1st value = 1st date, etc.)
    current_dates = []

    i = 0
    while i < len(lines):
        line = lines[i].rstrip('\r\n')
        i += 1

        if _is_skip_line(line):
            continue

        parts = line.split('\t')
        stripped = [p.strip() for p in parts]

        # --- Detect month header row (6+ month abbreviations) ---
        month_names_in_line = [p for p in stripped if p in MONTH_MAP]
        if len(month_names_in_line) >= 6:
            # Extract ordered month list, skipping duplicates (series breaks)
            months_ordered = []
            seen = set()
            for p in stripped:
                if p in MONTH_MAP and p not in seen:
                    months_ordered.append(MONTH_MAP[p])
                    seen.add(p)
                elif p in MONTH_MAP:
                    pass  # Duplicate month (old series) — skip

            # Find the year from the next meaningful line
            year = None
            while i < len(lines):
                next_line = lines[i].rstrip('\r\n')
                i += 1
                next_stripped = [p.strip() for p in next_line.split('\t')]

                # Look for 4-digit year
                for p in next_stripped:
                    try:
                        y = int(p)
                        if 1990 <= y <= 2030:
                            year = y
                            break
                    except ValueError:
                        continue
                if year:
                    break
                if next_line.strip().startswith('---') or not next_line.strip():
                    continue

            if not year:
                continue

            # Build date list: each month paired with the year
            current_dates = [f"{year}-{m:02d}" for m in months_ordered]
            continue

        # --- Skip if no dates defined yet ---
        if not current_dates:
            continue

        # --- Check for "Of which:" marker ---
        if 'Of which' in stripped[0]:
            continue

        # --- Extract the row name and data values ---
        # The first field is the name (may be quoted with commas inside)
        # All subsequent non-empty fields are data values

        raw_name = parts[0].strip()
        if not raw_name:
            # Name might be in position 1 if there's a leading tab for indented aggregates
            for p in parts:
                if p.strip():
                    raw_name = p.strip()
                    break
            if not raw_name:
                continue

        # Collect all numeric-looking values from the row
        data_values = []
        for p in parts[1:]:  # Skip the first field (name)
            p = p.strip()
            if not p:
                continue
            # Skip if it looks like a Series label (Roman numerals)
            if re.match(r'^[IVXLC]+$', p):
                continue
            # Skip if it's a year number (from the Country/year header)
            try:
                y = int(p)
                if 1990 <= y <= 2030:
                    continue
            except ValueError:
                pass
            data_values.append(p)

        # Parse values
        parsed_values = [_parse_value(v) for v in data_values]

        # Check if this has any actual numbers
        if not any(v is not None for v in parsed_values):
            continue

        # Determine if aggregate
        is_agg = False
        agg_key = None
        name = _clean_name(raw_name)

        for prefix, key in AGGREGATE_MAP.items():
            if prefix in raw_name or prefix in name:
                is_agg = True
                agg_key = key
                break

        # Map values to dates: values are in the same order as current_dates
        # (Dec, Nov, Oct, ... Jan) — first value = first date
        num_dates = len(current_dates)
        num_values = len(parsed_values)

        # Use min of dates and values to avoid index errors
        n = min(num_dates, num_values)

        for j in range(n):
            val = parsed_values[j]
            date_str = current_dates[j]
            if val is None:
                continue

            if is_agg and agg_key:
                aggregates[agg_key][date_str] = val
            elif name and len(name) > 1 and name != 'All Other':
                if name not in countries:
                    countries[name] = {}
                countries[name][date_str] = val

    # Convert to sorted arrays
    result_countries = {}
    for name, data in countries.items():
        if len(data) < 3:
            continue
        sorted_dates = sorted(data.keys())
        result_countries[name] = {
            'dates': sorted_dates,
            'values': [data[d] for d in sorted_dates],
        }

    result_aggregates = {}
    for key, data in aggregates.items():
        if data:
            sorted_dates = sorted(data.keys())
            result_aggregates[key] = {
                'dates': sorted_dates,
                'values': [data[d] for d in sorted_dates],
            }

    all_dates = set()
    for c in result_countries.values():
        all_dates.update(c['dates'])
    for a in result_aggregates.values():
        all_dates.update(a['dates'])

    metadata = {
        'source': 'US Treasury TIC',
        'url': 'https://ticdata.treasury.gov/Publish/mfhhis01.txt',
        'last_updated': datetime.now().strftime('%Y-%m-%d'),
        'date_range': [min(all_dates), max(all_dates)] if all_dates else [],
        'countries_count': len(result_countries),
    }

    return {
        'metadata': metadata,
        'countries': result_countries,
        'aggregates': result_aggregates,
    }


def save_tic_json(parsed: dict, output_path: str = None) -> str:
    """Save parsed TIC data to JSON."""
    if output_path is None:
        output_path = str(Path(__file__).parent / 'tic_mfh_data.json')
    with open(output_path, 'w') as f:
        json.dump(parsed, f)
    return output_path


def load_tic_data() -> dict:
    """Load pre-parsed TIC data from JSON."""
    path = Path(__file__).parent / 'tic_mfh_data.json'
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def compute_tic_summary(data: dict) -> list:
    """Compute summary statistics for each country."""
    summary = []
    for name, series in data.get('countries', {}).items():
        dates = series['dates']
        values = series['values']
        if len(values) < 2:
            continue

        latest = values[-1]
        prev_1m = values[-2] if len(values) >= 2 else None
        prev_12m = values[-13] if len(values) >= 13 else None
        prev_36m = values[-37] if len(values) >= 37 else None
        prev_60m = values[-61] if len(values) >= 61 else None
        all_time_high = max(v for v in values if v is not None)
        ath_idx = values.index(all_time_high)
        ath_date = dates[ath_idx]

        entry = {
            'country': name,
            'latest': round(latest, 1),
            'latest_date': dates[-1],
            'change_1m': round(latest - prev_1m, 1) if prev_1m else None,
            'pct_1m': round((latest - prev_1m) / prev_1m * 100, 1) if prev_1m and prev_1m != 0 else None,
            'change_12m': round(latest - prev_12m, 1) if prev_12m else None,
            'pct_12m': round((latest - prev_12m) / prev_12m * 100, 1) if prev_12m and prev_12m != 0 else None,
            'pct_36m': round((latest - prev_36m) / prev_36m * 100, 1) if prev_36m and prev_36m != 0 else None,
            'pct_60m': round((latest - prev_60m) / prev_60m * 100, 1) if prev_60m and prev_60m != 0 else None,
            'all_time_high': round(all_time_high, 1),
            'ath_date': ath_date,
        }
        summary.append(entry)

    summary.sort(key=lambda x: x['latest'], reverse=True)
    return summary
