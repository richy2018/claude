"""Track 5 — Tail Event Case Studies for GLI 3FA model.

Diagnoses model behavior during major drawdowns:
GFC (2007-09 to 2009-03), COVID (2020-02 to 2020-04),
Rate Shock (2022-01 to 2022-10), Vol Shock (2018-Q4).
"""

import numpy as np
import pandas as pd

from .backtest_engine import (
    _extract_components, _build_composite, SIGNAL_TRANSFORMS,
    PRODUCTION_MODELS, ALLOCATION_RULES, simulate_equity_curve,
)

TAIL_EVENTS = [
    {"name": "GFC", "start": "2007-09-01", "trough": "2009-03-01",
     "end": "2009-06-01", "driver": "Credit crisis / housing collapse"},
    {"name": "COVID", "start": "2020-02-01", "trough": "2020-03-01",
     "end": "2020-05-01", "driver": "Exogenous pandemic shock"},
    {"name": "Rate Shock", "start": "2022-01-01", "trough": "2022-10-01",
     "end": "2022-12-01", "driver": "Fed hiking cycle / inflation"},
    {"name": "Vol Shock Q4-2018", "start": "2018-10-01", "trough": "2018-12-01",
     "end": "2019-02-01", "driver": "Fed QT / autopilot tightening"},
]

# 3FA production config
_3FA = PRODUCTION_MODELS["3fa"]
_3FA_KEYS = _3FA["keys"]
_3FA_WEIGHTS = _3FA["weights"]
_SIG_FN = SIGNAL_TRANSFORMS["mom6"][1]
_ALLOC = ALLOCATION_RULES["aggressive"]


def _build_3fa_signal(components):
    """Build production 3FA Mom6M signal from components."""
    base_idx = components[_3FA_KEYS[0]].index
    for k in _3FA_KEYS[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()
    comp = _build_composite(components, _3FA_KEYS, _3FA_WEIGHTS, base_idx)
    signal = _SIG_FN(comp).dropna()
    return signal, comp


def _quintile_at(signal, date):
    """Return the quintile (1-5) of the signal at a given date."""
    if date not in signal.index:
        nearby = signal.index[signal.index <= date]
        if len(nearby) == 0:
            return None
        date = nearby[-1]
    val = signal[date]
    pct = float((signal[:date] <= val).mean()) * 100
    q = 1 if pct < 20 else 2 if pct < 40 else 3 if pct < 60 else 4 if pct < 80 else 5
    return q


def _signal_at(signal, date):
    """Get signal value nearest to date."""
    if date in signal.index:
        return float(signal[date])
    nearby = signal.index[signal.index <= date]
    if len(nearby) > 0:
        return float(signal[nearby[-1]])
    return None


def analyze_single_event(event, signal, comp_level, spy_monthly, components):
    """Analyze GLI model behavior during a single tail event."""
    start = pd.Timestamp(event["start"])
    trough = pd.Timestamp(event["trough"])
    end = pd.Timestamp(event["end"])
    pre_3m = start - pd.DateOffset(months=3)
    pre_6m = start - pd.DateOffset(months=6)

    # SPY drawdown in event window
    spy_m = spy_monthly.resample("MS").last().dropna()
    spy_window = spy_m[spy_m.index >= pre_6m]
    spy_window = spy_window[spy_window.index <= end]

    if len(spy_window) < 3:
        return {"name": event["name"], "error": "Not enough SPY data for this period"}

    spy_peak = spy_window[:start + pd.DateOffset(months=1)].max()
    spy_trough_val = spy_window[start:end].min()
    spy_dd = float((spy_trough_val - spy_peak) / spy_peak * 100) if spy_peak > 0 else 0

    # Signal values at key dates
    sig_pre_6m = _signal_at(signal, pre_6m)
    sig_pre_3m = _signal_at(signal, pre_3m)
    sig_at_start = _signal_at(signal, start)
    sig_at_trough = _signal_at(signal, trough)

    # Quintile at key dates
    q_pre_3m = _quintile_at(signal, pre_3m)
    q_at_start = _quintile_at(signal, start)
    q_at_trough = _quintile_at(signal, trough)

    # When did signal first enter Q4 or Q5 (defensive)?
    window_sig = signal[(signal.index >= pre_6m) & (signal.index <= end)]
    months_to_defensive = None
    defensive_date = None
    for d in window_sig.index:
        q = _quintile_at(signal, d)
        if q is not None and q >= 4:
            months_to_defensive = max(0, (d - start).days // 30)
            defensive_date = d.strftime("%Y-%m-%d")
            break

    # Strategy drawdown in event (simulate equity curve for the period)
    spy_ret = spy_monthly.pct_change().dropna()
    ec = simulate_equity_curve(signal, spy_ret, alloc_map=_ALLOC)
    strat_dd = None
    if "error" not in ec:
        chart = ec["chart"]
        window_chart = [c for c in chart if event["start"] <= c["date"] <= event["end"]]
        if window_chart:
            peak_val = max(c["portfolio"] for c in window_chart)
            trough_val = min(c["portfolio"] for c in window_chart)
            strat_dd = round((trough_val - peak_val) / peak_val * 100, 1) if peak_val > 0 else None

    # Component values at start
    comp_vals = {}
    for k in _3FA_KEYS:
        if k in components:
            comp_vals[k] = _signal_at(components[k], start)

    # Classify failure mode
    was_defensive = q_at_start is not None and q_at_start >= 4
    turned_defensive = months_to_defensive is not None
    slow = turned_defensive and months_to_defensive > 2
    wrong = not turned_defensive or (months_to_defensive is not None and months_to_defensive > 6)

    if was_defensive:
        failure_mode = "CORRECT — signal was defensive entering drawdown"
    elif slow and turned_defensive:
        failure_mode = f"SLOW — took {months_to_defensive}M to turn defensive (monthly frequency lag)"
    elif wrong:
        failure_mode = "WRONG — signal failed to capture this driver"
    else:
        failure_mode = f"LATE — turned defensive after {months_to_defensive}M"

    return {
        "name": event["name"],
        "period": f"{event['start'][:7]} to {event['end'][:7]}",
        "driver": event["driver"],
        "spy_drawdown": round(spy_dd, 1),
        "strategy_drawdown": strat_dd,
        "signal_pre_6m": round(sig_pre_6m, 3) if sig_pre_6m is not None else None,
        "signal_pre_3m": round(sig_pre_3m, 3) if sig_pre_3m is not None else None,
        "signal_at_start": round(sig_at_start, 3) if sig_at_start is not None else None,
        "signal_at_trough": round(sig_at_trough, 3) if sig_at_trough is not None else None,
        "quintile_pre_3m": q_pre_3m,
        "quintile_at_start": q_at_start,
        "quintile_at_trough": q_at_trough,
        "months_to_defensive": months_to_defensive,
        "defensive_date": defensive_date,
        "failure_mode": failure_mode,
        "component_values_at_start": {k: round(v, 3) if v is not None else None
                                       for k, v in comp_vals.items()},
    }


def run_tail_analysis(ratio_series, spy_monthly):
    """Run tail event analysis across all major drawdowns.

    Args:
        ratio_series: list of dicts from BIS debt ratio (gli_bis_credit cache)
        spy_monthly: pd.Series of SPY monthly prices

    Returns:
        dict with case_studies list and summary
    """
    components = _extract_components(ratio_series)
    missing = [k for k in _3FA_KEYS if k not in components]
    if missing:
        return {"error": f"Missing components: {missing}"}

    signal, comp_level = _build_3fa_signal(components)
    print(f"[TAIL] Signal: {len(signal)} pts, {signal.index[0].strftime('%Y-%m')} to {signal.index[-1].strftime('%Y-%m')}")

    case_studies = []
    for event in TAIL_EVENTS:
        print(f"[TAIL] Analyzing {event['name']}...")
        result = analyze_single_event(event, signal, comp_level, spy_monthly, components)
        case_studies.append(result)

    # Summary
    n_correct = sum(1 for cs in case_studies if "CORRECT" in cs.get("failure_mode", ""))
    n_slow = sum(1 for cs in case_studies if "SLOW" in cs.get("failure_mode", "") or "LATE" in cs.get("failure_mode", ""))
    n_wrong = sum(1 for cs in case_studies if "WRONG" in cs.get("failure_mode", ""))

    avg_spy_dd = np.mean([cs["spy_drawdown"] for cs in case_studies if cs.get("spy_drawdown") is not None])
    strat_dds = [cs["strategy_drawdown"] for cs in case_studies if cs.get("strategy_drawdown") is not None]
    avg_strat_dd = np.mean(strat_dds) if strat_dds else None

    return {
        "case_studies": case_studies,
        "summary": {
            "n_events": len(case_studies),
            "n_correct": n_correct,
            "n_slow": n_slow,
            "n_wrong": n_wrong,
            "avg_spy_drawdown": round(avg_spy_dd, 1),
            "avg_strategy_drawdown": round(avg_strat_dd, 1) if avg_strat_dd is not None else None,
            "verdict": (
                "Signal correctly positioned for most tail events"
                if n_correct >= len(case_studies) // 2
                else "Signal missed or was slow for most tail events — monthly frequency is a limiting factor"
            ),
        },
    }


if __name__ == "__main__":
    print("=" * 60)
    print("GLI 3FA Tail Event Analysis")
    print("=" * 60)
    print("This module must be run via the API endpoint.")
    print("Call run_tail_analysis(ratio_series, spy_monthly)")
    print("where ratio_series comes from _cache['gli_bis_credit']['debt_ratio']['ratio_series']")
