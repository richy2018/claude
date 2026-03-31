"""TIC Major Foreign Holders of Treasury Securities — data parser."""

import json
import re
from pathlib import Path
from datetime import datetime

MONTH_MAP = {
    'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
    'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12,
}

AGGREGATE_KEYS = {
    'Grand Total': 'Grand Total',
    'For. Official': 'Official',
    'For. official': 'Official',
    'Treasury Bills': 'Treasury Bills',
    'T-Bonds & Notes': 'T-Bonds & Notes',
}

# Countries to normalize
COUNTRY_NORMALIZE = {
    '"China, Mainland"': 'China, Mainland',
    'China, Mainland': 'China, Mainland',
    '"Korea, South"': 'Korea, South',
    'Korea, South': 'Korea, South',
    '"Korea, South "': 'Korea, South',
    'Korea, South ': 'Korea, South',
}


def parse_tic_text(raw_text: str) -> dict:
    """Parse the TIC Major Foreign Holders text file."""
    lines = raw_text.strip().split('\n')

    countries = {}  # {name: {date_str: value}}
    aggregates = {'Grand Total': {}, 'Official': {}, 'Treasury Bills': {}, 'T-Bonds & Notes': {}}

    current_months = []  # list of (month, year) tuples for current block
    in_data_block = False
    in_aggregate_section = False

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        i += 1

        # Skip empty lines and separators
        if not line.strip() or line.strip().startswith('------') or line.strip().startswith('MAJOR FOREIGN'):
            if line.strip().startswith('------'):
                continue
            continue

        # Skip header/metadata lines
        if line.strip().startswith('(in billions') or line.strip().startswith('HOLDINGS'):
            continue
        if line.strip().startswith('Series ') or line.strip().startswith('Department') or line.strip().startswith('*'):
            continue
        if line.strip().startswith('1/') or line.strip().startswith('2/') or line.strip().startswith('3/'):
            continue
        if line.strip().startswith('"') and ('revised' in line or 'Less than' in line or 'data in this' in line):
            continue
        if 'footnote' in line.lower() or 'treasury.gov' in line.lower():
            continue

        # Detect month header row: contains month abbreviations
        parts = line.split('\t')
        cleaned_parts = [p.strip() for p in parts]

        # Check if this is a month header row
        month_count = sum(1 for p in cleaned_parts if p in MONTH_MAP)
        if month_count >= 6:
            # This is a month header — next line should have years
            # Read year line
            if i < len(lines):
                year_line = lines[i].rstrip()
                year_parts = [p.strip() for p in year_line.split('\t')]
                i += 1

                # Build date columns by pairing months with years positionally
                # Both rows have the same tab structure: first col is label, rest are data
                current_months = []
                for j in range(max(len(cleaned_parts), len(year_parts))):
                    mp = cleaned_parts[j].strip() if j < len(cleaned_parts) else ''
                    yp = year_parts[j].strip() if j < len(year_parts) else ''

                    if mp in MONTH_MAP:
                        yr = None
                        try:
                            yr = int(yp)
                        except (ValueError, TypeError):
                            # Year might be in a different column — use the block's year
                            for yy in year_parts:
                                try:
                                    yr = int(yy.strip())
                                    break
                                except ValueError:
                                    continue
                        if yr and yr >= 1990 and yr <= 2030:
                            current_months.append((MONTH_MAP[mp], yr))
                        else:
                            current_months.append(None)
                    else:
                        current_months.append(None)

                in_data_block = True
                in_aggregate_section = False
                continue

        # Check for "Country" header line (skip it)
        if cleaned_parts[0].lower().startswith('country'):
            continue

        # Check for "Of which:" marker
        if 'Of which' in line:
            in_aggregate_section = True
            continue

        # If we're in a data block, parse country/aggregate rows
        if in_data_block and current_months:
            name = cleaned_parts[0].strip()

            # Skip empty or non-data rows
            if not name or name.startswith('------') or name.startswith('Series'):
                continue

            # Clean country name
            name = re.sub(r'\s*\d+/\s*$', '', name)  # Remove footnote markers like "2/"
            name = name.strip('"').strip()
            name = COUNTRY_NORMALIZE.get(name, name)
            if name in COUNTRY_NORMALIZE.values():
                pass
            elif '"' in cleaned_parts[0]:
                # Handle quoted names
                orig = cleaned_parts[0].strip()
                name = orig.strip('"').strip()
                name = re.sub(r'\s*\d+/\s*$', '', name)
                name = COUNTRY_NORMALIZE.get(name, name)

            # Skip continuation lines from footnotes
            if name.startswith('(') or name.startswith('*') or name.lower().startswith('note'):
                in_data_block = False
                continue

            # Determine if this is an aggregate row
            is_agg = False
            agg_key = None
            for pattern, key in AGGREGATE_KEYS.items():
                if pattern in name:
                    is_agg = True
                    agg_key = key
                    break

            # Parse values — use same positional index as month columns
            # (cleaned_parts[0] is the country name, data starts at [1])
            for j, month_info in enumerate(current_months):
                if month_info is None:
                    continue
                month, year = month_info
                date_str = f"{year}-{month:02d}"

                val = None
                if j < len(cleaned_parts):
                    v = cleaned_parts[j].strip()
                    if v and v != '*' and v.lower() != 'n.a.' and v != '--' and v != '---':
                        try:
                            val = float(v.replace(',', ''))
                        except ValueError:
                            val = None

                if val is not None:
                    if is_agg:
                        if agg_key not in aggregates:
                            aggregates[agg_key] = {}
                        # Keep the newer series value if duplicate
                        if date_str not in aggregates[agg_key]:
                            aggregates[agg_key][date_str] = val
                    else:
                        if name not in countries:
                            countries[name] = {}
                        if date_str not in countries[name]:
                            countries[name][date_str] = val

    # Convert to sorted arrays
    result_countries = {}
    for name, data in countries.items():
        if len(data) < 3:  # Skip countries with very little data
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

    # Find date range
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
        json.dump(parsed, f, indent=2)
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
