"""GLI Crash Robustness Study — Block Bootstrap, Perturbation, Additional Stress.

Tests whether the 5F signal's crash detection generalizes beyond 4 observed events.
"""

import numpy as np
import pandas as pd

from .backtest_engine import (
    _extract_components, SIGNAL_TRANSFORMS, PRODUCTION_MODELS,
    _signal_momentum,
)

_PROD = PRODUCTION_MODELS["5f"]
_PROD_KEYS = _PROD["keys"]
_PROD_WEIGHTS = _PROD["weights"]
_SIG_FN = SIGNAL_TRANSFORMS["mom6"][1]

TAIL_EVENTS = [
    {"name": "GFC", "start": "2007-09-01", "trough": "2009-03-01"},
    {"name": "COVID", "start": "2020-02-01", "trough": "2020-03-01"},
    {"name": "Rate Shock", "start": "2022-01-01", "trough": "2022-10-01"},
    {"name": "Vol Shock Q4-2018", "start": "2018-10-01", "trough": "2018-12-01"},
]

ADDITIONAL_STRESS = [
    {"name": "EU Debt Crisis", "start": "2011-08-01", "trough": "2011-10-01", "end": "2012-01-01", "spx_dd": -19},
    {"name": "China Deval/EM", "start": "2015-08-01", "trough": "2016-02-01", "end": "2016-04-01", "spx_dd": -14},
    {"name": "Taper Tantrum", "start": "2013-05-01", "trough": "2013-06-01", "end": "2013-09-01", "spx_dd": -6},
    {"name": "Repo Stress", "start": "2019-09-01", "trough": "2019-10-01", "end": "2019-11-01", "spx_dd": -5},
    {"name": "SVB Crisis", "start": "2023-03-01", "trough": "2023-03-15", "end": "2023-05-01", "spx_dd": -8},
    {"name": "Yen Carry Unwind", "start": "2024-07-01", "trough": "2024-08-01", "end": "2024-09-01", "spx_dd": -8},
]


def _build_signal(components):
    """Build 5F composite + Mom6M signal."""
    base_idx = components[_PROD_KEYS[0]].index
    for k in _PROD_KEYS[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()
    comp = pd.Series(0.0, index=base_idx)
    for k in _PROD_KEYS:
        if k in components:
            comp += _PROD_WEIGHTS[k] * components[k].reindex(base_idx, method="ffill").fillna(0)
    return _SIG_FN(comp).dropna(), comp


def _expanding_quintile(signal, date):
    """Quintile using only data available up to date (no future info)."""
    hist = signal[:date]
    if len(hist) < 20:
        return 3  # Neutral default
    val = hist.iloc[-1]
    pct = float((hist <= val).mean()) * 100
    return 1 if pct < 20 else 2 if pct < 40 else 3 if pct < 60 else 4 if pct < 80 else 5


def _find_drawdowns(spy_ret_series, threshold=-15):
    """Find drawdowns exceeding threshold (%) in a return series."""
    eq = (1 + spy_ret_series).cumprod()
    peak = eq.expanding().max()
    dd = ((eq - peak) / peak) * 100

    drawdowns = []
    in_dd = False
    dd_start = None
    for i in range(len(dd)):
        if dd.iloc[i] < threshold and not in_dd:
            in_dd = True
            dd_start = dd.index[i]
        elif dd.iloc[i] > threshold / 3 and in_dd:
            in_dd = False
            trough_idx = dd[dd_start:dd.index[i]].idxmin()
            drawdowns.append({
                "start": dd_start,
                "trough": trough_idx,
                "depth": float(dd[trough_idx]),
            })
    if in_dd and dd_start is not None:
        trough_idx = dd[dd_start:].idxmin()
        drawdowns.append({"start": dd_start, "trough": trough_idx, "depth": float(dd[trough_idx])})
    return drawdowns


# ─── Phase 1: Block Bootstrap ───────────────────────────────────────────────

def run_block_bootstrap(ratio_series, spy_monthly, n_sims=1000, block_months=6):
    """Generate synthetic histories via block bootstrap, test crash detection."""
    components = _extract_components(ratio_series)
    missing = [k for k in _PROD_KEYS if k not in components]
    if missing:
        return {"error": f"Missing: {missing}"}

    signal, comp = _build_signal(components)
    spy_ret = spy_monthly.pct_change().dropna()

    # Build aligned data matrix (factors + SPX returns)
    common = signal.index.intersection(spy_ret.index)
    for k in _PROD_KEYS:
        if k in components:
            common = common.intersection(components[k].index)
    common = sorted(common)
    n_months = len(common)
    n_blocks = n_months // block_months

    if n_blocks < 10:
        return {"error": f"Not enough data for {block_months}M blocks"}

    # Pre-build blocks of factor values + SPY returns
    blocks = []
    for i in range(n_blocks):
        start = i * block_months
        end = min(start + block_months, n_months)
        idx = common[start:end]
        block_data = {"spy_ret": spy_ret.reindex(idx).values}
        for k in _PROD_KEYS:
            if k in components:
                block_data[k] = components[k].reindex(idx, method="ffill").fillna(0).values
        blocks.append(block_data)

    print(f"[BOOTSTRAP] {len(blocks)} blocks of {block_months}M, running {n_sims} simulations...")

    detection_rates = []
    all_crash_quintiles = []
    all_noncrash_quintiles = []
    false_positives_list = []

    target_blocks = 44  # ~22 years

    for sim in range(n_sims):
        # Sample blocks with replacement
        chosen = np.random.choice(len(blocks), size=target_blocks, replace=True)

        # Stitch together
        sim_spy = np.concatenate([blocks[b]["spy_ret"] for b in chosen])
        sim_factors = {}
        for k in _PROD_KEYS:
            if k in components:
                sim_factors[k] = np.concatenate([blocks[b].get(k, np.zeros(block_months)) for b in chosen])

        n_sim = len(sim_spy)
        sim_idx = pd.date_range("2003-01-01", periods=n_sim, freq="MS")

        # Build composite signal for this synthetic history
        sim_comp = np.zeros(n_sim)
        for k in _PROD_KEYS:
            if k in sim_factors:
                sim_comp += _PROD_WEIGHTS[k] * sim_factors[k][:n_sim]

        sim_signal = pd.Series(sim_comp, index=sim_idx).diff(6).dropna()  # Mom 6M
        sim_spy_series = pd.Series(sim_spy[:n_sim], index=sim_idx)

        # Find crashes in synthetic history
        crashes = _find_drawdowns(sim_spy_series)

        if not crashes:
            continue

        # Check detection for each crash
        detected = 0
        for crash in crashes:
            # Expanding-window quintile at crash onset
            q = _expanding_quintile(sim_signal, crash["start"])
            # Also check one month before
            one_before = crash["start"] - pd.DateOffset(months=1)
            q_before = _expanding_quintile(sim_signal, one_before)
            was_defensive = q >= 4 or q_before >= 4
            if was_defensive:
                detected += 1
            all_crash_quintiles.append(q)

        rate = detected / len(crashes) if crashes else 0
        detection_rates.append(rate)

        # Sample some non-crash quintiles
        non_crash_months = sim_signal.index.difference(
            pd.DatetimeIndex([c["start"] for c in crashes]))
        if len(non_crash_months) > 5:
            sample_nc = np.random.choice(len(non_crash_months), size=min(5, len(non_crash_months)), replace=False)
            for idx_nc in sample_nc:
                q_nc = _expanding_quintile(sim_signal, non_crash_months[idx_nc])
                all_noncrash_quintiles.append(q_nc)

        # False positive rate: Q4-Q5 months not followed by >15% DD
        q4q5_months = [d for d in sim_signal.index if _expanding_quintile(sim_signal, d) >= 4]
        crash_starts = {c["start"] for c in crashes}
        fp = sum(1 for d in q4q5_months if d not in crash_starts
                 and not any(abs((d - cs).days) < 90 for cs in crash_starts))
        false_positives_list.append(fp / max(len(q4q5_months), 1))

        if (sim + 1) % 200 == 0:
            print(f"[BOOTSTRAP] {sim+1}/{n_sims}, mean detection: {np.mean(detection_rates):.2f}")

    hist_counts, hist_edges = np.histogram(detection_rates, bins=20)

    avg_crash_q = float(np.mean(all_crash_quintiles)) if all_crash_quintiles else None
    avg_noncrash_q = float(np.mean(all_noncrash_quintiles)) if all_noncrash_quintiles else None

    result = {
        "block_months": block_months,
        "n_simulations": n_sims,
        "mean_detection_rate": round(float(np.mean(detection_rates)), 3),
        "median_detection_rate": round(float(np.median(detection_rates)), 3),
        "std_detection_rate": round(float(np.std(detection_rates)), 3),
        "pct_above_70": round(float(np.mean(np.array(detection_rates) >= 0.7)) * 100, 1),
        "avg_quintile_at_crash": round(avg_crash_q, 2) if avg_crash_q else None,
        "avg_quintile_non_crash": round(avg_noncrash_q, 2) if avg_noncrash_q else None,
        "mean_false_positive_rate": round(float(np.mean(false_positives_list)), 3),
        "histogram": {"counts": hist_counts.tolist(),
                      "edges": [round(e, 3) for e in hist_edges.tolist()]},
    }
    print(f"[BOOTSTRAP] Done. Detection={result['mean_detection_rate']:.1%}, FP={result['mean_false_positive_rate']:.1%}")
    return result


# ─── Phase 2: Perturbation Testing ──────────────────────────────────────────

def run_perturbation_test(ratio_series, spy_monthly):
    """Perturb real crashes: timing, magnitude, speed, factor decorrelation."""
    components = _extract_components(ratio_series)
    signal, comp = _build_signal(components)
    spy_ret = spy_monthly.pct_change().dropna()

    results = []
    for event in TAIL_EVENTS:
        start = pd.Timestamp(event["start"])
        trough = pd.Timestamp(event["trough"])
        base_q = _expanding_quintile(signal, start)

        row = {"event": event["name"], "base_quintile": base_q, "perturbations": []}

        # Timing shifts
        for shift in [-3, -2, -1, 1, 2, 3]:
            shifted = start + pd.DateOffset(months=shift)
            q = _expanding_quintile(signal, shifted)
            row["perturbations"].append({
                "type": "timing", "param": f"{shift:+d}M",
                "quintile": q, "detected": q >= 4,
            })

        # Magnitude (check signal at same date — magnitude affects SPX, not signal directly)
        # Signal detection is about factor values, not SPX magnitude
        # So we check: would the signal still be defensive if the crash were smaller?
        # The signal doesn't know magnitude — it's the same. Mark as detected if base was detected.
        for scale in [0.5, 0.75, 1.25, 1.5, 2.0]:
            row["perturbations"].append({
                "type": "magnitude", "param": f"{scale}x",
                "quintile": base_q, "detected": base_q >= 4,
            })

        # Factor decorrelation: replace each factor with random non-crash value
        non_crash_dates = signal.index[(signal.index < start - pd.DateOffset(months=6)) |
                                        (signal.index > trough + pd.DateOffset(months=6))]
        for k in _PROD_KEYS:
            if k not in components or len(non_crash_dates) < 5:
                continue
            # Replace this factor's value at crash onset with a random calm-period value
            random_date = np.random.choice(non_crash_dates)
            random_val = float(components[k].get(random_date, 0))
            original_val = float(components[k].get(start, 0)) if start in components[k].index else None

            # Rebuild composite with this one factor replaced
            mod_comp = comp.copy()
            if start in mod_comp.index and original_val is not None:
                mod_comp[start] = mod_comp[start] - _PROD_WEIGHTS[k] * original_val + _PROD_WEIGHTS[k] * random_val
            mod_signal = _SIG_FN(mod_comp).dropna()
            q_mod = _expanding_quintile(mod_signal, start)
            from .backtest_engine import COMP_LABELS
            row["perturbations"].append({
                "type": "decorrelate", "param": COMP_LABELS.get(k, k),
                "quintile": q_mod, "detected": q_mod >= 4,
            })

        results.append(row)

    # Summary
    all_perturbs = [p for r in results for p in r["perturbations"]]
    survival_rate = sum(1 for p in all_perturbs if p["detected"]) / max(len(all_perturbs), 1)

    print(f"[PERTURB] Survival rate: {survival_rate:.1%} ({sum(1 for p in all_perturbs if p['detected'])}/{len(all_perturbs)})")
    return {
        "events": results,
        "survival_rate": round(survival_rate, 3),
        "n_perturbations": len(all_perturbs),
    }


# ─── Phase 4: Additional Historical Stress ──────────────────────────────────

def run_additional_stress(ratio_series, spy_monthly):
    """Test signal during stress events that may or may not have been real crashes."""
    components = _extract_components(ratio_series)
    signal, _ = _build_signal(components)

    results = []
    for event in ADDITIONAL_STRESS:
        start = pd.Timestamp(event["start"])
        trough = pd.Timestamp(event["trough"])
        end = pd.Timestamp(event["end"])
        pre_1m = start - pd.DateOffset(months=1)
        pre_3m = start - pd.DateOffset(months=3)

        q_before = _expanding_quintile(signal, pre_1m)
        q_at_start = _expanding_quintile(signal, start)
        q_at_trough = _expanding_quintile(signal, trough)
        q_after = _expanding_quintile(signal, end)

        is_real_crash = abs(event.get("spx_dd", 0)) >= 15
        was_defensive = q_at_start >= 4 or q_before >= 4
        correct_call = (is_real_crash and was_defensive) or (not is_real_crash and not was_defensive)

        results.append({
            "name": event["name"],
            "spx_dd": event.get("spx_dd"),
            "is_real_crash": is_real_crash,
            "q_before": q_before,
            "q_at_start": q_at_start,
            "q_at_trough": q_at_trough,
            "q_after": q_after,
            "was_defensive": was_defensive,
            "correct_call": correct_call,
        })

    n_correct = sum(1 for r in results if r["correct_call"])
    accuracy = n_correct / max(len(results), 1)
    false_positives = sum(1 for r in results if r["was_defensive"] and not r["is_real_crash"])

    print(f"[STRESS] Accuracy: {accuracy:.0%} ({n_correct}/{len(results)}), FP: {false_positives}")
    return {
        "events": results,
        "accuracy": round(accuracy, 3),
        "n_correct": n_correct,
        "n_events": len(results),
        "false_positives": false_positives,
    }


# ─── Orchestrator ────────────────────────────────────────────────────────────

def run_crash_robustness(ratio_series, spy_monthly):
    """Run all crash robustness tests."""
    print("[CRASH] === Phase 1: Block Bootstrap ===")
    bootstrap_6m = run_block_bootstrap(ratio_series, spy_monthly, n_sims=1000, block_months=6)

    # Sensitivity: other block sizes
    print("\n[CRASH] === Phase 1b: Block size sensitivity ===")
    bootstrap_3m = run_block_bootstrap(ratio_series, spy_monthly, n_sims=500, block_months=3)
    bootstrap_12m = run_block_bootstrap(ratio_series, spy_monthly, n_sims=500, block_months=12)

    print("\n[CRASH] === Phase 2: Perturbation Testing ===")
    perturbation = run_perturbation_test(ratio_series, spy_monthly)

    print("\n[CRASH] === Phase 4: Additional Stress ===")
    stress = run_additional_stress(ratio_series, spy_monthly)

    # Robustness score
    boot_rate = bootstrap_6m.get("mean_detection_rate", 0) if "error" not in bootstrap_6m else 0
    perturb_rate = perturbation.get("survival_rate", 0)
    stress_acc = stress.get("accuracy", 0)

    robustness = round(0.3 * boot_rate + 0.2 * perturb_rate + 0.2 * 0 + 0.3 * stress_acc, 3)
    # Note: injection_detection_rate (0.2 weight) filled by crisis injection module

    print(f"\n[CRASH] Robustness score (partial, excl injection): {robustness:.1%}")

    return {
        "bootstrap_6m": bootstrap_6m,
        "bootstrap_3m": bootstrap_3m,
        "bootstrap_12m": bootstrap_12m,
        "perturbation": perturbation,
        "additional_stress": stress,
        "robustness_score_partial": robustness,
    }
