"""GLI Synthetic Crisis Injection — inject stress scenarios into calm periods.

Tests whether the 5F signal mechanically detects various crisis types by
modifying raw factor values and recomputing the signal from scratch.
"""

import numpy as np
import pandas as pd
import copy

from .backtest_engine import (
    _extract_components, SIGNAL_TRANSFORMS, PRODUCTION_MODELS,
    COMP_LABELS,
)

_PROD = PRODUCTION_MODELS["5f"]
_PROD_KEYS = _PROD["keys"]
_PROD_WEIGHTS = _PROD["weights"]
_SIG_FN = SIGNAL_TRANSFORMS["mom6"][1]

# Crisis scenarios: monthly deltas applied to factor z-scores
CRISIS_SCENARIOS = {
    "sovereign_debt": {
        "label": "Sovereign Debt Crisis",
        "duration": 4,
        "monthly_deltas": {
            "spread_signal": [0.05, 0.10, 0.15, 0.15],      # HY OAS widening (tightening)
            "dollar_stress_signal": [0.02, 0.05, 0.07, 0.08], # Xccy basis stress
            "quantity_signal": [0, 0, 0, 0],                   # CB sheets flat
            "m2_signal": [0, 0.02, 0.03, 0.03],               # M2 slowing
            "rate_signal": [0, 0, 0.02, 0.03],                # Rates rising (risk)
        },
    },
    "currency_crisis": {
        "label": "Currency Crisis (EM-style)",
        "duration": 3,
        "monthly_deltas": {
            "spread_signal": [0.08, 0.12, 0.10],              # HY widens
            "dollar_stress_signal": [0.15, 0.20, 0.15],       # Dollar shortage
            "quantity_signal": [0.03, 0.05, 0.05],             # CB selling reserves
            "m2_signal": [0.02, 0.04, 0.04],                  # M2 contraction
            "rate_signal": [0.05, 0.08, 0.06],                # Rates spiking
        },
    },
    "stagflation": {
        "label": "Stagflation (Slow Grind)",
        "duration": 6,
        "monthly_deltas": {
            "spread_signal": [0.02, 0.03, 0.04, 0.05, 0.05, 0.05],
            "dollar_stress_signal": [0.01, 0.02, 0.03, 0.03, 0.04, 0.04],
            "quantity_signal": [0, 0, 0.01, 0.01, 0.02, 0.02],
            "m2_signal": [0.01, 0.02, 0.03, 0.03, 0.04, 0.04],
            "rate_signal": [0.01, 0.02, 0.03, 0.04, 0.04, 0.05],
        },
    },
    "flash_crash": {
        "label": "Flash Crash / Liquidity Event",
        "duration": 2,
        "monthly_deltas": {
            "spread_signal": [0.25, -0.10],                   # Spike then partial recovery
            "dollar_stress_signal": [0.15, -0.05],
            "quantity_signal": [0, 0],                         # Too fast for macro
            "m2_signal": [0, 0],
            "rate_signal": [0.03, -0.02],
        },
    },
    "inflationary_bust": {
        "label": "Inflationary Bust (QT)",
        "duration": 5,
        "monthly_deltas": {
            "spread_signal": [0.03, 0.05, 0.07, 0.08, 0.08],
            "dollar_stress_signal": [0.02, 0.03, 0.04, 0.05, 0.05],
            "quantity_signal": [0.02, 0.04, 0.06, 0.07, 0.08], # CB shrinking (QT)
            "m2_signal": [0.01, 0.03, 0.05, 0.06, 0.06],      # M2 declining
            "rate_signal": [0.05, 0.08, 0.10, 0.10, 0.08],     # Rates elevated
        },
    },
}

# Calm periods to inject crises into
CALM_PERIODS = [
    {"label": "2004-2005", "start": "2004-06-01"},
    {"label": "2012-2013", "start": "2012-06-01"},
    {"label": "2014-2015", "start": "2014-06-01"},
    {"label": "2017", "start": "2017-06-01"},
    {"label": "2021", "start": "2021-06-01"},
]


def _inject_crisis(ratio_series, scenario, inject_start):
    """Inject a crisis scenario by modifying factor values in ratio_series.

    Modifies raw values BEFORE signal computation, so the full pipeline
    (z-score → weight → composite → momentum → quintile) processes them fresh.
    """
    modified = copy.deepcopy(ratio_series)
    inject_date = pd.Timestamp(inject_start)
    duration = scenario["duration"]

    for i, row in enumerate(modified):
        row_date = pd.Timestamp(row["date"])
        month_offset = (row_date.year - inject_date.year) * 12 + (row_date.month - inject_date.month)

        if 0 <= month_offset < duration:
            for factor_key, deltas in scenario["monthly_deltas"].items():
                if factor_key in row and month_offset < len(deltas):
                    original = row.get(factor_key)
                    if original is not None:
                        row[factor_key] = original + deltas[month_offset]

    return modified


def _compute_signal_from_ratio(ratio_series):
    """Build 5F composite signal from ratio_series."""
    components = _extract_components(ratio_series)
    missing = [k for k in _PROD_KEYS if k not in components]
    if missing:
        return None, missing
    base_idx = components[_PROD_KEYS[0]].index
    for k in _PROD_KEYS[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()
    comp = pd.Series(0.0, index=base_idx)
    for k in _PROD_KEYS:
        if k in components:
            comp += _PROD_WEIGHTS[k] * components[k].reindex(base_idx, method="ffill").fillna(0)
    signal = _SIG_FN(comp).dropna()
    return signal, None


def _expanding_quintile(signal, date):
    """Quintile using only data up to date."""
    hist = signal[:date]
    if len(hist) < 20:
        return 3
    val = hist.iloc[-1]
    pct = float((hist <= val).mean()) * 100
    return 1 if pct < 20 else 2 if pct < 40 else 3 if pct < 60 else 4 if pct < 80 else 5


def inject_single_crisis(ratio_series, scenario_key, calm_period):
    """Inject one crisis into one calm period, report detection."""
    scenario = CRISIS_SCENARIOS[scenario_key]
    inject_start = calm_period["start"]

    # Baseline signal (no injection)
    baseline_signal, err = _compute_signal_from_ratio(ratio_series)
    if err:
        return {"error": f"Baseline missing: {err}"}

    # Injected signal
    modified_rs = _inject_crisis(ratio_series, scenario, inject_start)
    injected_signal, err = _compute_signal_from_ratio(modified_rs)
    if err:
        return {"error": f"Injected missing: {err}"}

    inject_date = pd.Timestamp(inject_start)
    duration = scenario["duration"]

    # Track quintile evolution during injection
    quintile_path = []
    months_to_defensive = None
    for m in range(duration + 2):  # Check 2 months past injection end
        check_date = inject_date + pd.DateOffset(months=m)
        q_base = _expanding_quintile(baseline_signal, check_date)
        q_inj = _expanding_quintile(injected_signal, check_date)
        quintile_path.append({
            "month": m, "baseline_q": q_base, "injected_q": q_inj,
        })
        if q_inj >= 4 and months_to_defensive is None:
            months_to_defensive = m

    # Which factor drove the largest signal change?
    driver = None
    max_impact = 0
    for k in _PROD_KEYS:
        deltas = scenario["monthly_deltas"].get(k, [])
        total_delta = sum(abs(d) for d in deltas)
        if total_delta > max_impact:
            max_impact = total_delta
            driver = COMP_LABELS.get(k, k)

    detected = months_to_defensive is not None

    return {
        "scenario": scenario_key,
        "scenario_label": scenario["label"],
        "calm_period": calm_period["label"],
        "detected": detected,
        "months_to_defensive": months_to_defensive,
        "driver": driver,
        "quintile_path": quintile_path,
    }


def run_crisis_injection(ratio_series, spy_monthly):
    """Run all crisis scenarios across all calm periods."""
    results = []
    detection_count = 0
    total_tests = 0

    for scenario_key in CRISIS_SCENARIOS:
        scenario = CRISIS_SCENARIOS[scenario_key]
        for calm in CALM_PERIODS:
            print(f"[INJECT] {scenario['label']} → {calm['label']}...")
            result = inject_single_crisis(ratio_series, scenario_key, calm)
            results.append(result)
            total_tests += 1
            if result.get("detected"):
                detection_count += 1

    detection_rate = detection_count / max(total_tests, 1)

    # Summary by scenario
    by_scenario = {}
    for r in results:
        sk = r.get("scenario", "unknown")
        if sk not in by_scenario:
            by_scenario[sk] = {"detected": 0, "total": 0, "avg_months": []}
        by_scenario[sk]["total"] += 1
        if r.get("detected"):
            by_scenario[sk]["detected"] += 1
            if r.get("months_to_defensive") is not None:
                by_scenario[sk]["avg_months"].append(r["months_to_defensive"])

    scenario_summary = []
    for sk, sv in by_scenario.items():
        scenario_summary.append({
            "scenario": sk,
            "label": CRISIS_SCENARIOS.get(sk, {}).get("label", sk),
            "detected": sv["detected"],
            "total": sv["total"],
            "detection_rate": round(sv["detected"] / max(sv["total"], 1), 2),
            "avg_months_to_detect": round(float(np.mean(sv["avg_months"])), 1) if sv["avg_months"] else None,
        })

    print(f"[INJECT] Detection rate: {detection_rate:.0%} ({detection_count}/{total_tests})")
    return {
        "results": results,
        "scenario_summary": scenario_summary,
        "detection_rate": round(detection_rate, 3),
        "n_detected": detection_count,
        "n_total": total_tests,
    }
