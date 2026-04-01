"""Portfolio optimizer — scores and selects bonds for optimal allocation."""

import numpy as np


def optimize_portfolio(bonds, constraints):
    """
    Score and select bonds to build an optimized portfolio.

    constraints: {
        investment_amount: 200000,
        target_return: 6.2 (gross),
        target_duration: 3.0,
        max_issuer_pct: 0.05,
        max_position_pct: 0.10,
        max_usd_pct: 0.50,
        min_rating_num: 13 (BB-),
        max_positions: 20,
        weights: {ytm: 0.30, default: 0.25, spread_eff: 0.25, icr: 0.10, ebitda: 0.10},
        excluded_ids: []
    }
    """
    weights = constraints.get('weights', {
        'ytm': 0.30, 'default': 0.25, 'spread_eff': 0.25, 'icr': 0.10, 'ebitda': 0.10
    })
    investment = constraints.get('investment_amount', 200000)
    target_return = constraints.get('target_return', 6.2)
    target_duration = constraints.get('target_duration', 3.0)
    max_issuer_pct = constraints.get('max_issuer_pct', 0.05)
    max_position_pct = constraints.get('max_position_pct', 0.10)
    max_usd_pct = constraints.get('max_usd_pct', 0.50)
    min_rating_num = constraints.get('min_rating_num', 13)
    max_positions = constraints.get('max_positions', 20)
    excluded_ids = set(constraints.get('excluded_ids', []))

    # Filter eligible bonds
    eligible = []
    for b in bonds:
        if b.get('id') in excluded_ids:
            continue
        if b.get('ytm') is None or b.get('duration') is None:
            continue
        if b.get('rating_num') is not None and b['rating_num'] > min_rating_num:
            continue
        if b.get('duration', 99) > target_duration * 2:
            continue
        eligible.append(b)

    if not eligible:
        return {'positions': [], 'error': 'No eligible bonds found'}

    # Compute median values for normalization
    icr_values = [b['interest_coverage'] for b in eligible if b.get('interest_coverage')]
    ebitda_values = [b['ebitda_to_interest'] for b in eligible if b.get('ebitda_to_interest')]
    median_icr = float(np.median(icr_values)) if icr_values else 1
    median_ebitda = float(np.median(ebitda_values)) if ebitda_values else 1

    # Score each bond
    for b in eligible:
        ytm_score = (b.get('ytm') or 0) / max(target_return, 1)

        dp = b.get('default_probability')
        default_score = (1.0 / max(dp, 1e-6)) if dp and dp > 0 else 1.0
        default_score = min(default_score, 100)  # cap to prevent outliers
        default_score = default_score / 100  # normalize to 0-1 range

        dur = b.get('duration') or 1
        oas = b.get('oas_spread') or 0
        spread_eff_score = (oas / max(dur, 0.1)) / 100  # normalize

        icr = b.get('interest_coverage')
        icr_score = (icr / max(median_icr, 1)) if icr else 0.5
        icr_score = min(icr_score, 2) / 2  # normalize to 0-1

        ebitda = b.get('ebitda_to_interest')
        ebitda_score = (ebitda / max(median_ebitda, 1)) if ebitda else 0.5
        ebitda_score = min(ebitda_score, 2) / 2  # normalize to 0-1

        composite = (
            weights['ytm'] * ytm_score +
            weights['default'] * default_score +
            weights['spread_eff'] * spread_eff_score +
            weights['icr'] * icr_score +
            weights['ebitda'] * ebitda_score
        )

        b['_score'] = round(composite, 4)
        b['_score_breakdown'] = {
            'ytm': round(ytm_score, 3),
            'default': round(default_score, 3),
            'spread_eff': round(spread_eff_score, 3),
            'icr': round(icr_score, 3),
            'ebitda': round(ebitda_score, 3),
        }

    # Sort by score descending
    eligible.sort(key=lambda b: b['_score'], reverse=True)

    # Greedy selection with constraint checking
    selected = []
    total_alloc = 0
    issuer_allocs = {}  # issuer_name → total allocation
    usd_alloc = 0
    position_size = investment / max_positions  # equal weight starting point

    for b in eligible:
        if len(selected) >= max_positions:
            break
        if total_alloc >= investment:
            break

        alloc = min(position_size, investment - total_alloc)
        alloc = min(alloc, investment * max_position_pct)

        issuer = b.get('issuer_name') or b.get('ticker') or 'Unknown'

        # Check issuer concentration
        current_issuer = issuer_allocs.get(issuer, 0)
        if (current_issuer + alloc) / investment > max_issuer_pct:
            continue

        # Check USD concentration
        if b.get('currency') == 'USD':
            if (usd_alloc + alloc) / investment > max_usd_pct:
                continue

        # Check if adding this bond keeps duration within target
        # Weighted average duration check
        if selected:
            new_total = total_alloc + alloc
            current_dur = sum(s['allocation'] * (s.get('duration') or 0) for s in selected) / total_alloc if total_alloc > 0 else 0
            new_dur = (current_dur * total_alloc + (b.get('duration') or 0) * alloc) / new_total
            if new_dur > target_duration * 1.15:  # allow 15% overshoot
                continue

        # Add to portfolio
        position = {**b, 'allocation': round(alloc, 2)}
        selected.append(position)
        total_alloc += alloc
        issuer_allocs[issuer] = issuer_allocs.get(issuer, 0) + alloc
        if b.get('currency') == 'USD':
            usd_alloc += alloc

    # Compute portfolio metrics
    if selected:
        w_ytm = sum(s['allocation'] * (s.get('ytm') or 0) for s in selected) / total_alloc if total_alloc > 0 else 0
        w_dur = sum(s['allocation'] * (s.get('duration') or 0) for s in selected) / total_alloc if total_alloc > 0 else 0
    else:
        w_ytm = 0
        w_dur = 0

    return {
        'positions': selected,
        'metrics': {
            'count': len(selected),
            'total_allocation': round(total_alloc, 2),
            'weighted_ytm': round(w_ytm, 3),
            'weighted_duration': round(w_dur, 2),
            'usd_pct': round(usd_alloc / total_alloc * 100, 1) if total_alloc > 0 else 0,
        },
        'universe_size': len(eligible),
    }
