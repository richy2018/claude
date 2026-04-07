"""Portfolio optimizer — scores, selects, and allocates bonds."""

import numpy as np


def optimize_portfolio(bonds, constraints):
    """Score, select, and allocate bonds for an optimized portfolio."""
    weights = constraints.get('weights', {
        'ytm': 0.25, 'default': 0.20, 'spread_eff': 0.20, 'icr': 0.10, 'ebitda': 0.05,
        'ytw': 0.10, 'liquidity': 0.10,
    })
    investment = constraints.get('investment_amount', 200000)
    target_return = constraints.get('target_return', 6.2)
    target_duration = constraints.get('target_duration', 3.0)
    max_position_pct = constraints.get('max_position_pct', 0.10)
    max_usd_pct = constraints.get('max_usd_pct', 0.50)
    min_rating_num = constraints.get('min_rating_num', 13)
    max_rating_num = constraints.get('max_rating_num', 1)  # 1 = AAA (best), higher = worse
    max_positions = constraints.get('max_positions', 20)
    excluded_ids = set(constraints.get('excluded_ids', []))
    min_position = 2000  # minimum position size

    # Filter eligible bonds
    eligible = []
    for b in bonds:
        if b.get('id') in excluded_ids:
            continue
        if b.get('ytm') is None:
            continue
        if b.get('rating_num') is not None and b['rating_num'] > min_rating_num:
            continue
        if b.get('rating_num') is not None and b['rating_num'] < max_rating_num:
            continue
        eligible.append(b)

    if not eligible:
        return {'positions': [], 'error': 'No eligible bonds found'}

    # Compute medians for normalization
    icr_vals = [b['interest_coverage'] for b in eligible if b.get('interest_coverage')]
    ebitda_vals = [b['ebitda_to_interest'] for b in eligible if b.get('ebitda_to_interest')]
    bid_ask_vals = [b['bid_ask_spread'] for b in eligible if b.get('bid_ask_spread') and b['bid_ask_spread'] > 0]
    median_icr = float(np.median(icr_vals)) if icr_vals else 1
    median_ebitda = float(np.median(ebitda_vals)) if ebitda_vals else 1
    median_bid_ask = float(np.median(bid_ask_vals)) if bid_ask_vals else 1

    # Score each bond
    for b in eligible:
        ytm_score = (b.get('ytm') or 0) / max(target_return, 1)

        dp = b.get('default_probability')
        default_score = min((1.0 / max(dp, 1e-6)) / 100, 1.0) if dp and dp > 0 else 0.5

        dur = b.get('duration') or 1
        oas = b.get('oas_spread') or 0
        spread_eff_score = min((oas / max(dur, 0.1)) / 100, 1.0)

        icr = b.get('interest_coverage')
        icr_score = min((icr / max(median_icr, 1)), 2) / 2 if icr else 0.5

        ebitda = b.get('ebitda_to_interest')
        ebitda_score = min((ebitda / max(median_ebitda, 1)), 2) / 2 if ebitda else 0.5

        # YTW score: yield-to-worst relative to target (lower YTW on callables = less attractive)
        ytw = b.get('ytw')
        ytw_score = (ytw / max(target_return, 1)) if ytw else ytm_score  # fallback to YTM score

        # Liquidity score: inverse of bid-ask spread (tighter = more liquid = better)
        ba = b.get('bid_ask_spread')
        liquidity_score = min((median_bid_ask / max(ba, 0.001)), 2) / 2 if ba and ba > 0 else 0.5

        composite = (
            weights.get('ytm', 0) * ytm_score +
            weights.get('default', 0) * default_score +
            weights.get('spread_eff', 0) * spread_eff_score +
            weights.get('icr', 0) * icr_score +
            weights.get('ebitda', 0) * ebitda_score +
            weights.get('ytw', 0) * ytw_score +
            weights.get('liquidity', 0) * liquidity_score
        )

        b['_score'] = round(composite, 4)
        b['_score_breakdown'] = {
            'ytm': round(ytm_score, 3),
            'default': round(default_score, 3),
            'spread_eff': round(spread_eff_score, 3),
            'icr': round(icr_score, 3),
            'ebitda': round(ebitda_score, 3),
            'ytw': round(ytw_score, 3),
            'liquidity': round(liquidity_score, 3),
        }

    # Sort by score descending
    eligible.sort(key=lambda b: b['_score'], reverse=True)

    # --- Phase 1: Select bonds via greedy constraint checking ---
    selected = []
    usd_count = 0
    issuers_seen = set()

    for b in eligible:
        if len(selected) >= max_positions:
            break

        issuer = b.get('issuer_name') or b.get('ticker') or 'Unknown'

        # Skip duplicate issuers (allow max 2 bonds per issuer)
        issuer_count = sum(1 for s in selected if (s.get('issuer_name') or s.get('ticker')) == issuer)
        if issuer_count >= 2:
            continue

        # Check if adding this bond would bust USD limit
        if b.get('currency') == 'USD':
            usd_pct = (usd_count + 1) / max(len(selected) + 1, 1)
            if usd_pct > max_usd_pct and max_usd_pct < 1.0:
                continue

        selected.append(b)
        if b.get('currency') == 'USD':
            usd_count += 1

    if not selected:
        return {'positions': [], 'error': 'No bonds passed constraint checks'}

    # --- Phase 2: Score-weighted allocation ---
    total_score = sum(s['_score'] for s in selected)
    max_alloc = investment * max_position_pct

    # Initial allocation proportional to score
    for s in selected:
        raw_weight = s['_score'] / total_score if total_score > 0 else 1 / len(selected)
        s['_raw_weight'] = raw_weight
        s['allocation'] = round(raw_weight * investment, 2)

    # --- Phase 3: Iterative constraint enforcement ---
    for iteration in range(5):
        total_alloc = sum(s['allocation'] for s in selected)

        # Cap max position size
        excess = 0
        for s in selected:
            if s['allocation'] > max_alloc:
                excess += s['allocation'] - max_alloc
                s['allocation'] = max_alloc

        # Redistribute excess to uncapped positions proportionally
        if excess > 0:
            uncapped = [s for s in selected if s['allocation'] < max_alloc]
            if uncapped:
                uncapped_score = sum(s['_score'] for s in uncapped)
                for s in uncapped:
                    share = s['_score'] / uncapped_score if uncapped_score > 0 else 1 / len(uncapped)
                    s['allocation'] = min(s['allocation'] + excess * share, max_alloc)

        # Enforce minimum position size
        for s in selected:
            if s['allocation'] < min_position:
                s['allocation'] = min_position

        # Duration adjustment: if over target, shift weight to shorter bonds
        w_dur = _weighted_avg(selected, 'duration')
        if w_dur and w_dur > target_duration * 1.1:
            for s in selected:
                dur = s.get('duration') or 0
                if dur > target_duration:
                    s['allocation'] *= 0.85  # reduce long duration
                elif dur < target_duration:
                    s['allocation'] *= 1.15  # increase short duration

        # YTM adjustment: if under target, shift weight to higher yielding
        w_ytm = _weighted_avg(selected, 'ytm')
        if w_ytm and w_ytm < target_return * 0.95:
            for s in selected:
                ytm = s.get('ytm') or 0
                if ytm > target_return:
                    s['allocation'] *= 1.1
                elif ytm < target_return * 0.8:
                    s['allocation'] *= 0.9

        # Normalize to investment amount
        current_total = sum(s['allocation'] for s in selected)
        if current_total > 0:
            scale = investment / current_total
            for s in selected:
                s['allocation'] = round(s['allocation'] * scale, 2)

    # Final metrics
    total_alloc = sum(s['allocation'] for s in selected)
    w_ytm = _weighted_avg(selected, 'ytm')
    w_dur = _weighted_avg(selected, 'duration')
    usd_alloc = sum(s['allocation'] for s in selected if s.get('currency') == 'USD')

    # Add allocation rationale
    for s in selected:
        pct = s['allocation'] / total_alloc * 100 if total_alloc > 0 else 0
        eq_pct = 100 / len(selected) if selected else 0
        s['_alloc_pct'] = round(pct, 1)
        s['_vs_equal'] = round(pct - eq_pct, 1)  # positive = overweight vs equal

    # Equal-weight comparison
    eq_ytm = sum((s.get('ytm') or 0) for s in selected) / len(selected) if selected else 0
    eq_dur = sum((s.get('duration') or 0) for s in selected) / len(selected) if selected else 0

    return {
        'positions': selected,
        'metrics': {
            'count': len(selected),
            'total_allocation': round(total_alloc, 2),
            'weighted_ytm': round(w_ytm, 3) if w_ytm else 0,
            'weighted_duration': round(w_dur, 2) if w_dur else 0,
            'usd_pct': round(usd_alloc / total_alloc * 100, 1) if total_alloc > 0 else 0,
            'equal_weight_ytm': round(eq_ytm, 3),
            'equal_weight_dur': round(eq_dur, 2),
        },
        'universe_size': len(eligible),
    }


def _weighted_avg(items, field):
    sw, swv = 0, 0
    for i in items:
        v = i.get(field)
        w = i.get('allocation', 0)
        if v is not None and w > 0:
            sw += w
            swv += w * v
    return swv / sw if sw > 0 else None
