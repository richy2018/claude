"""Bloomberg bond universe CSV parser."""

import pandas as pd
import numpy as np
from datetime import datetime
from io import StringIO


# All #N/A variants from Bloomberg
NA_VALUES = ['#N/A Field Not Applicable', '#N/A N/A', '#N/A', 'N/A', 'n/a', '', '-']

# Column name mapping: Bloomberg field name → internal snake_case key
COLUMN_MAP = {
    'Issuer Name': 'issuer_name',
    'Amt Out': 'amount_outstanding',
    'Ticker': 'ticker',
    'Issuer 1-yr Default Probability': 'default_probability',
    'EBITDA to Interest Expense': 'ebitda_to_interest',
    'Net Debt to EBITDA': 'net_debt_to_ebitda',
    'Yld to Mty (Ask)': 'ytm',
    'Yld to Mty Ask': 'ytm',
    'Payment Rank': 'payment_rank',
    'Cpn': 'coupon',
    'Maturity': 'maturity',
    'BBG Composite': 'rating',
    'Mty Type': 'maturity_type',
    'Currency': 'currency',
    'ISIN': 'isin',
    'Interest Coverage Ratio': 'interest_coverage',
    'Asset Class': 'asset_class',
    'OAS Eff Dur (Mid)': 'duration',
    'OAS Eff Dur Mid': 'duration',
    'OAS Sprd (Mid)': 'oas_spread',
    'OAS Sprd Mid': 'oas_spread',
    'G-Spread (Mid)': 'g_spread',
    'G-Spread Mid': 'g_spread',
    'Cntry of Risk': 'country_of_risk',
    'Normalized Payment Rank': 'normalized_payment_rank',
}
# Also add lowercase variants
_extra = {}
for k, v in list(COLUMN_MAP.items()):
    _extra[k.lower()] = v
    _extra[k.lower().replace(' ', '_')] = v
COLUMN_MAP.update(_extra)

# Rating scale: letter → numeric
RATING_TO_NUM = {
    'AAA': 1, 'AA+': 2, 'AA': 3, 'AA-': 4,
    'A+': 5, 'A': 6, 'A-': 7,
    'BBB+': 8, 'BBB': 9, 'BBB-': 10,
    'BB+': 11, 'BB': 12, 'BB-': 13,
    'B+': 14, 'B': 15, 'B-': 16,
    'CCC+': 17, 'CCC': 18, 'CCC-': 19,
    'CC': 20, 'C': 21, 'D': 22,
}

NUM_TO_RATING = {v: k for k, v in RATING_TO_NUM.items()}


def parse_bond_csv(content: str) -> list:
    """
    Parse a Bloomberg bond universe CSV (tab-delimited).
    Returns list of bond dicts with normalized keys.
    """
    # Auto-detect delimiter: try tab first, then semicolon, then comma
    sep = '\t'
    first_line = content.split('\n')[0]
    if '\t' in first_line:
        sep = '\t'
    elif ';' in first_line:
        sep = ';'
    else:
        sep = ','

    # Read with pandas, treating all #N/A variants as NaN
    df = pd.read_csv(
        StringIO(content),
        sep=sep,
        na_values=NA_VALUES,
        keep_default_na=True,
    )

    # Rename columns to snake_case
    rename = {}
    for col in df.columns:
        col_stripped = col.strip()
        if col_stripped in COLUMN_MAP:
            rename[col] = COLUMN_MAP[col_stripped]
        else:
            # Convert unknown columns to snake_case
            rename[col] = col_stripped.lower().replace(' ', '_').replace('(', '').replace(')', '')
    df = df.rename(columns=rename)

    # Parse maturity dates (DD.MM.YYYY format)
    if 'maturity' in df.columns:
        df['maturity_date'] = df['maturity'].apply(_parse_maturity)
        df['years_to_maturity'] = df['maturity_date'].apply(_years_to_maturity)

    # Ensure numeric columns are float
    numeric_cols = [
        'amount_outstanding', 'default_probability', 'ebitda_to_interest',
        'net_debt_to_ebitda', 'ytm', 'coupon', 'interest_coverage',
        'duration', 'oas_spread', 'g_spread',
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Add rating numeric value
    if 'rating' in df.columns:
        df['rating_num'] = df['rating'].map(RATING_TO_NUM)

    # Convert to list of dicts, replacing NaN with None
    bonds = df.where(df.notna(), None).to_dict(orient='records')

    # Clean up: convert numpy types to native Python
    cleaned = []
    for bond in bonds:
        clean = {}
        for k, v in bond.items():
            if isinstance(v, (np.floating, np.integer)):
                clean[k] = float(v) if not np.isnan(v) else None
            elif isinstance(v, np.bool_):
                clean[k] = bool(v)
            elif isinstance(v, pd.Timestamp):
                clean[k] = v.strftime('%Y-%m-%d')
            elif v is np.nan or v is pd.NaT:
                clean[k] = None
            elif isinstance(v, float) and np.isnan(v):
                clean[k] = None
            else:
                clean[k] = v
        # Add an ID for frontend tracking
        clean['id'] = clean.get('isin') or f"{clean.get('ticker', 'UNK')}_{clean.get('coupon', 0)}_{clean.get('maturity', '')}"
        cleaned.append(clean)

    return cleaned


def _parse_maturity(val):
    """Parse maturity date from DD.MM.YYYY format."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    s = str(val).strip()
    for fmt in ['%d.%m.%Y', '%d/%m/%Y', '%Y-%m-%d', '%m/%d/%Y']:
        try:
            return pd.Timestamp(datetime.strptime(s, fmt))
        except (ValueError, TypeError):
            continue
    return None


def _years_to_maturity(dt):
    """Compute years from now to maturity date."""
    if dt is None or pd.isna(dt):
        return None
    now = pd.Timestamp.now()
    delta = (dt - now).days / 365.25
    return round(delta, 2) if delta > 0 else 0


def filter_bonds(bonds: list, filters: dict) -> list:
    """Apply filters to bond list. All filters are optional."""
    result = bonds

    # Text search
    q = (filters.get('search') or '').lower()
    if q:
        result = [b for b in result if
                  q in (b.get('issuer_name') or '').lower() or
                  q in (b.get('ticker') or '').lower() or
                  q in (b.get('isin') or '').lower()]

    # Currency
    currencies = filters.get('currencies')
    if currencies:
        cur_list = [c.strip().upper() for c in currencies.split(',')]
        result = [b for b in result if b.get('currency') in cur_list]

    # Rating range (by numeric)
    rating_min = filters.get('rating_min')
    rating_max = filters.get('rating_max')
    if rating_min is not None:
        result = [b for b in result if b.get('rating_num') is not None and b['rating_num'] >= rating_min]
    if rating_max is not None:
        result = [b for b in result if b.get('rating_num') is not None and b['rating_num'] <= rating_max]

    # Numeric range filters
    range_filters = [
        ('maturity_min', 'maturity_max', 'years_to_maturity'),
        ('duration_min', 'duration_max', 'duration'),
        ('ytm_min', 'ytm_max', 'ytm'),
        ('oas_min', 'oas_max', 'oas_spread'),
        ('coupon_min', 'coupon_max', 'coupon'),
    ]
    for min_key, max_key, field in range_filters:
        min_val = filters.get(min_key)
        max_val = filters.get(max_key)
        if min_val is not None:
            result = [b for b in result if b.get(field) is not None and b[field] >= min_val]
        if max_val is not None:
            result = [b for b in result if b.get(field) is not None and b[field] <= max_val]

    # Amount outstanding min
    amt_min = filters.get('amount_min')
    if amt_min is not None:
        result = [b for b in result if b.get('amount_outstanding') is not None and b['amount_outstanding'] >= amt_min]

    # Default probability max
    dp_max = filters.get('default_prob_max')
    if dp_max is not None:
        result = [b for b in result if b.get('default_probability') is not None and b['default_probability'] <= dp_max]

    # Payment rank
    ranks = filters.get('payment_ranks')
    if ranks:
        rank_list = [r.strip() for r in ranks.split(',')]
        result = [b for b in result if b.get('payment_rank') in rank_list]

    # Asset class
    classes = filters.get('asset_classes')
    if classes:
        class_list = [c.strip() for c in classes.split(',')]
        result = [b for b in result if b.get('asset_class') in class_list]

    return result


def get_bond_summary(bonds: list) -> dict:
    """Get summary statistics for a bond list."""
    if not bonds:
        return {'count': 0}

    currencies = set(b.get('currency') for b in bonds if b.get('currency'))
    ratings = [b.get('rating') for b in bonds if b.get('rating')]
    asset_classes = set(b.get('asset_class') for b in bonds if b.get('asset_class'))
    payment_ranks = set(b.get('payment_rank') for b in bonds if b.get('payment_rank'))

    return {
        'count': len(bonds),
        'currencies': sorted(currencies),
        'asset_classes': sorted(asset_classes),
        'payment_ranks': sorted(payment_ranks),
        'rating_range': [min(ratings), max(ratings)] if ratings else [],
    }
