"""TIC Major Foreign Holders of Treasury Securities — data parser."""

import json
import re
from pathlib import Path
from datetime import datetime

MONTH_MAP = {
    'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
    'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12,
}

AGGREGATE_PREFIXES = ['Grand Total', 'For. Official', 'For. official',
                      'Treasury Bills', 'T-Bonds & Notes', 'Of which']

AGGREGATE_MAP = {
    'Grand Total': 'Grand Total',
    'For. Official': 'Official',
    'For. official': 'Official',
    'Treasury Bills': 'Treasury Bills',
    'T-Bonds & Notes': 'T-Bonds & Notes',
}


def _clean_name(name):
    """Normalize a country name."""
    name = name.strip().strip('"').strip()
    name = re.sub(r'\s*\d+/\s*$', '', name)  # Remove footnote markers
    name = name.strip()
    # Normalize known variants
    if name.startswith('Korea') and 'South' in name:
        return 'Korea, South'
    if name.startswith('China'):
        return 'China, Mainland'
    return name


def _parse_value(v):
    """Parse a cell value to float or None."""
    v = v.strip()
    if not v or v == '*' or v.lower() == 'n.a.' or v == '--' or v == '---':
        return None
    try:
        return float(v.replace(',', ''))
    except ValueError:
        return None


def parse_tic_text(raw_text: str) -> dict:
    """Parse the TIC Major Foreign Holders text file."""
    lines = raw_text.split('\n')

    countries = {}  # {name: {date_str: value}}
    aggregates = {'Grand Total': {}, 'Official': {}, 'Treasury Bills': {}, 'T-Bonds & Notes': {}}

    current_columns = []  # list of date strings like "2025-12" aligned to tab positions
    in_aggregate = False

    i = 0
    while i < len(lines):
        line = lines[i].rstrip('\r\n')
        i += 1

        parts = line.split('\t')
        stripped = [p.strip() for p in parts]

        # Count months in this line
        month_count = sum(1 for p in stripped if p in MONTH_MAP)

        # Detect month header row (has 6+ month names)
        if month_count >= 6:
            month_positions = []  # (tab_index, month_number)
            seen_months = set()  # track which months we've seen to skip duplicates
            for j, p in enumerate(stripped):
                if p in MONTH_MAP:
                    month_num = MONTH_MAP[p]
                    if month_num not in seen_months:
                        # First occurrence = newer series (columns go Dec→Jan, left=newer)
                        month_positions.append((j, month_num))
                        seen_months.add(month_num)
                    # Skip duplicate month (old series comparison column)

            # Next non-empty line should have year info (starts with "Country" or has year numbers)
            year = None
            while i < len(lines):
                next_line = lines[i].rstrip('\r\n')
                next_parts = [p.strip() for p in next_line.split('\t')]
                i += 1

                # Look for a 4-digit year in this line
                for p in next_parts:
                    try:
                        y = int(p)
                        if 1990 <= y <= 2030:
                            year = y
                            break
                    except ValueError:
                        continue

                if year:
                    break
                # Skip separator lines
                if next_line.strip().startswith('---') or not next_line.strip():
                    continue
                # If it starts with "Country", the year might be on this line
                if 'Country' in next_line:
                    for p in next_parts:
                        try:
                            y = int(p)
                            if 1990 <= y <= 2030:
                                year = y
                                break
                        except ValueError:
                            continue
                    if year:
                        break

            if not year:
                continue

            # Build column mapping: tab_index -> date_string
            current_columns = []
            for tab_idx, month_num in month_positions:
                current_columns.append((tab_idx, f"{year}-{month_num:02d}"))

            in_aggregate = False
            continue

        # Skip non-data lines
        first = stripped[0] if stripped else ''
        if not first:
            continue
        if first.startswith('---') or first.startswith('Series'):
            continue
        if 'MAJOR FOREIGN' in line or 'HOLDINGS' in line or 'in billions' in line:
            continue
        if first.startswith('Department') or first.startswith('*') or first.startswith('('):
            continue
        if first.startswith('"(') or 'revised' in line.lower():
            continue
        if any(first.startswith(f'{n}/') for n in range(1, 20)):
            continue
        if 'treasury.gov' in line.lower() or 'TIC FAQ' in line:
            continue

        # Check for "Of which:" marker
        if 'Of which' in first:
            in_aggregate = True
            continue

        # If no columns defined yet, skip
        if not current_columns:
            continue

        # Determine if this is an aggregate row
        is_agg = False
        agg_key = None
        for prefix, key in AGGREGATE_MAP.items():
            if prefix in first:
                is_agg = True
                agg_key = key
                break

        # Clean country name
        name = _clean_name(parts[0]) if not is_agg else None

        # Skip lines that don't look like data (no numeric values)
        has_numbers = any(_parse_value(p) is not None for p in stripped[1:] if p)
        if not has_numbers:
            continue

        # Extract values at the column positions
        for tab_idx, date_str in current_columns:
            if tab_idx < len(stripped):
                val = _parse_value(stripped[tab_idx])
                if val is not None:
                    if is_agg and agg_key:
                        # Always overwrite — later series data is more accurate
                        aggregates[agg_key][date_str] = val
                    elif name and name != 'All Other' and len(name) > 1:
                        if name not in countries:
                            countries[name] = {}
                        # Always overwrite — later series data is more accurate
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
