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
    current_dates = []
    current_keep_indices = []   # tab indices in header that map to dates
    current_skip_indices = set()  # tab indices to skip (old series duplicates)

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
            # Find the tab positions of each month, tracking duplicates
            # We need to know WHICH tab indices to READ and which to SKIP
            keep_indices = []   # tab indices to keep (newer series)
            skip_indices = set()  # tab indices to skip (old series duplicates)
            seen_months = set()

            for j, p in enumerate(stripped):
                if p in MONTH_MAP:
                    if p not in seen_months:
                        keep_indices.append((j, MONTH_MAP[p]))
                        seen_months.add(p)
                    else:
                        skip_indices.add(j)  # duplicate month — mark for skipping

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

            # Build date list from kept indices
            current_dates = [f"{year}-{m:02d}" for _, m in keep_indices]
            # Store the tab indices to keep vs skip for data row extraction
            current_keep_indices = [j for j, _ in keep_indices]
            current_skip_indices = skip_indices
            continue

        # --- Skip if no dates defined yet ---
        if not current_dates:
            continue

        # --- Check for "Of which:" marker ---
        if 'Of which' in stripped[0]:
            continue

        # --- Extract row name ---
        raw_name = parts[0].strip()
        if not raw_name:
            # Name might be after a leading tab (indented aggregate rows)
            for p in parts:
                if p.strip():
                    raw_name = p.strip()
                    break
            if not raw_name:
                continue

        # --- Extract values at the KEPT tab positions only ---
        # This ensures we skip the duplicate series-break columns
        # and read exactly the right number of values (one per date)
        extracted = []
        for keep_idx in current_keep_indices:
            if keep_idx < len(stripped):
                extracted.append(stripped[keep_idx])
            else:
                extracted.append('')

        parsed_values = [_parse_value(v) for v in extracted]

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

        # Map values to dates by position (1:1 correspondence)
        for j in range(len(current_dates)):
            if j >= len(parsed_values):
                break
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


# Supplemental data not yet in the main TIC text file
# Update this dict when new monthly data is released
SUPPLEMENTAL_DATA = {
    "2026-01": {
        "Japan": 1225.3,
        "United Kingdom": 895.3,
        "China, Mainland": 694.4,
        "Belgium": 451.0,
        "Luxembourg": 446.9,
        "Cayman Islands": 432.7,
        "Canada": 395.8,
        "France": 380.5,
        "Ireland": 342.0,
        "Taiwan": 307.8,
        "Switzerland": 289.2,
        "Singapore": 273.4,
        "Hong Kong": 259.9,
        "Norway": 218.8,
        "India": 190.4,
        "Brazil": 168.0,
        "Korea, South": 141.3,
        "Saudi Arabia": 134.8,
        "Israel": 114.7,
        "United Arab Emirates": 112.4,
    },
    "2026-01_aggregates": {
        "Grand Total": 9305.8,
        "Official": 3954.8,
        "Treasury Bills": 407.7,
        "T-Bonds & Notes": 3547.1,
    },
    "2026-02": {
        "Japan": 1239.3,
        "United Kingdom": 897.3,
        "China, Mainland": 693.3,
        "Belgium": 454.7,
        "Canada": 446.3,
        "Luxembourg": 445.7,
        "Cayman Islands": 443.0,
        "France": 395.1,
        "Ireland": 350.6,
        "Taiwan": 313.5,
        "Switzerland": 286.7,
        "Singapore": 280.0,
        "Hong Kong": 269.2,
        "Norway": 223.0,
        "India": 190.6,
        "Brazil": 170.6,
        "Saudi Arabia": 160.4,
        "Korea, South": 140.9,
        "United Arab Emirates": 119.9,
        "Israel": 110.8,
    },
    "2026-02_aggregates": {
        "Grand Total": 9487.1,
        "Official": 4035.7,
        "Treasury Bills": 475.5,
        "T-Bonds & Notes": 3560.2,
    },
}


def apply_supplemental(parsed: dict) -> dict:
    """Append supplemental monthly data not yet in the main TIC file."""
    for date_key, values in SUPPLEMENTAL_DATA.items():
        if date_key.endswith('_aggregates'):
            date = date_key.replace('_aggregates', '')
            for agg_name, val in values.items():
                if agg_name in parsed['aggregates']:
                    if date not in parsed['aggregates'][agg_name]['dates']:
                        parsed['aggregates'][agg_name]['dates'].append(date)
                        parsed['aggregates'][agg_name]['values'].append(val)
        else:
            for country, val in values.items():
                if country in parsed['countries']:
                    if date_key not in parsed['countries'][country]['dates']:
                        parsed['countries'][country]['dates'].append(date_key)
                        parsed['countries'][country]['values'].append(val)

    # Update metadata
    all_dates = set()
    for c in parsed['countries'].values():
        all_dates.update(c['dates'])
    if all_dates:
        parsed['metadata']['date_range'] = [min(all_dates), max(all_dates)]
    parsed['metadata']['last_updated'] = datetime.now().strftime('%Y-%m-%d')

    return parsed


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
