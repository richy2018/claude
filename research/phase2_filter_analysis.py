"""Phase 2 — Univariate Filter Analysis & Rule Design.

Computes univariate separation statistics, builds three candidate
rule-based filters, evaluates on train/holdout split, and produces
filtered signal CSVs for Phase 3 backtesting.

Usage (standalone):
  python research/phase2_filter_analysis.py

Usage (as module from backend):
  from research.phase2_filter_analysis import run_phase2_analysis
  result = run_phase2_analysis(phase1_result)
"""

import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "backend"))

from research.config import OUTPUT_DIR

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COVID_PRESERVE_DATES = [
    "2020-02-01", "2020-03-01", "2020-04-01",
    "2020-05-01", "2020-06-01",
]

TRAIN_END = "2019-12-31"
HOLDOUT_START = "2020-01-01"

# Variables to test (priority order)
UNIVARIATE_VARS = [
    "hy_oas_level_percentile",
    "hy_oas_3m_change",
    "hy_oas_6m_change",
    "hy_oas",
    "cfnai_ma3",
    "cfnai_3m_change",
    "curve_10y_2y",
    "fed_funds_3m_change",
    "real_10y",
    "real_10y_3m_change",
    "vix_level",
    "vix_percentile_5y",
    "spy_pct_from_52w_high",
    "spy_trailing_12m_return",
    "quintile_duration",
    "dxy_12m_change",
    "earnings_yoy",
]

# One-hot variables (computed from categoricals)
ONEHOT_VARS = {
    "growth_regime_contraction": ("growth_regime", "contraction"),
    "curve_regime_inverted": ("curve_regime", "inverted"),
    "fed_regime_cutting": ("fed_regime", "cutting"),
}

# Grid search parameters
X_GRID = [10, 15, 20, 25, 30]        # HY OAS percentile threshold
Y_GRID = [0, 10, 20, 30, 50]         # HY OAS 3m change threshold (bps)

# Objective weights: TP retention × 0.6 + FP reduction × 0.4
W_TP = 0.6
W_FP = 0.4


# ---------------------------------------------------------------------------
# Univariate analysis
# ---------------------------------------------------------------------------

def compute_univariate_stats(df, label_col="label_moderate_tp"):
    """Compute AUC, KS, optimal threshold for each variable."""
    from sklearn.metrics import roc_auc_score
    from scipy.stats import ks_2samp

    results = []

    # Add one-hot columns
    for oh_name, (src_col, src_val) in ONEHOT_VARS.items():
        if src_col in df.columns:
            df[oh_name] = (df[src_col] == src_val).astype(int)

    all_vars = UNIVARIATE_VARS + list(ONEHOT_VARS.keys())

    for var in all_vars:
        if var not in df.columns:
            continue

        valid = df[[var, label_col]].dropna()
        if len(valid) < 20:
            continue

        x = valid[var].astype(float).values
        y = valid[label_col].astype(int).values

        if y.sum() == 0 or y.sum() == len(y):
            continue

        # AUC (handle direction — higher AUC is better separation)
        try:
            auc = roc_auc_score(y, x)
            # If AUC < 0.5, the variable is inversely correlated — flip
            if auc < 0.5:
                auc = 1 - auc
                direction = "lower_is_tp"
            else:
                direction = "higher_is_tp"
        except Exception:
            continue

        # KS statistic
        tp_vals = x[y == 1]
        fp_vals = x[y == 0]
        try:
            ks_stat, ks_p = ks_2samp(tp_vals, fp_vals)
        except Exception:
            ks_stat, ks_p = 0, 1

        # Optimal threshold (maximize TP rate - FP rate)
        best_thresh = None
        best_sep = -1
        best_tp_ret = 0
        best_fp_red = 0

        thresholds = np.percentile(x, np.arange(5, 96, 5))
        for t in thresholds:
            if direction == "higher_is_tp":
                pred_tp = x >= t
            else:
                pred_tp = x <= t
            tp_retained = y[pred_tp].sum() / max(y.sum(), 1)
            fp_removed = 1 - (len(y[pred_tp]) - y[pred_tp].sum()) / max((1 - y).sum(), 1)
            sep = tp_retained - (1 - fp_removed)
            if sep > best_sep:
                best_sep = sep
                best_thresh = float(t)
                best_tp_ret = tp_retained
                best_fp_red = fp_removed

        results.append({
            "variable": var,
            "auc": round(auc, 4),
            "ks_stat": round(ks_stat, 4),
            "ks_p": round(ks_p, 4),
            "direction": direction,
            "optimal_threshold": round(best_thresh, 2) if best_thresh is not None else None,
            "tp_retention": round(best_tp_ret * 100, 1),
            "fp_reduction": round(best_fp_red * 100, 1),
            "tp_mean": round(float(tp_vals.mean()), 2),
            "fp_mean": round(float(fp_vals.mean()), 2),
            "n_valid": len(valid),
        })

    results.sort(key=lambda r: r["auc"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------

def _add_covid_flag(df):
    """Add is_covid_preserve column."""
    df = df.copy()
    df["is_covid_preserve"] = df["signal_date"].isin(COVID_PRESERVE_DATES)
    return df


def evaluate_rule(df, rule_fn, label_col="label_moderate_tp"):
    """Evaluate a filter rule on a DataFrame.

    rule_fn: callable(row) -> bool, True = downgrade (filter triggers)
    Returns metrics dict.
    """
    df = _add_covid_flag(df)

    kept = []
    removed = []
    covid_preserved = 0
    covid_total = int(df["is_covid_preserve"].sum())

    for _, row in df.iterrows():
        # COVID exception: never filter these
        if row["is_covid_preserve"]:
            covid_preserved += 1
            kept.append(row)
            continue

        if rule_fn(row):
            removed.append(row)
        else:
            kept.append(row)

    kept_df = pd.DataFrame(kept) if kept else pd.DataFrame()
    removed_df = pd.DataFrame(removed) if removed else pd.DataFrame()

    total = len(df)
    n_kept = len(kept_df)
    n_removed = len(removed_df)

    # TP/FP counts
    total_tp = int(df[label_col].dropna().sum())
    total_fp = int((df[label_col].dropna() == 0).sum())

    if len(kept_df) > 0 and label_col in kept_df.columns:
        kept_tp = int(kept_df[label_col].dropna().sum())
    else:
        kept_tp = 0

    if len(removed_df) > 0 and label_col in removed_df.columns:
        removed_fp = int((removed_df[label_col].dropna() == 0).sum())
    else:
        removed_fp = 0

    tp_retained_pct = round(kept_tp / max(total_tp, 1) * 100, 1)
    fp_removed_pct = round(removed_fp / max(total_fp, 1) * 100, 1)
    accuracy = round(kept_tp / max(n_kept, 1) * 100, 1) if n_kept > 0 else 0

    return {
        "signals_kept": n_kept,
        "signals_removed": n_removed,
        "tps_retained": kept_tp,
        "tps_retained_pct": tp_retained_pct,
        "fps_removed": removed_fp,
        "fps_removed_pct": fp_removed_pct,
        "covid_preserved": f"{covid_preserved}/{covid_total}",
        "accuracy": accuracy,
        "total_tp": total_tp,
        "total_fp": total_fp,
    }


def make_rule_a(x_thresh, y_thresh):
    """Rule A: Credit-Only. Downgrade if HY OAS pctl < X AND 3m change < Y."""
    def rule(row):
        pctl = row.get("hy_oas_level_percentile")
        chg = row.get("hy_oas_3m_change")
        if pctl is None or chg is None or pd.isna(pctl) or pd.isna(chg):
            return False
        return pctl < x_thresh and chg < y_thresh
    return rule


def make_rule_b(x_thresh, y_thresh):
    """Rule B: Credit + Growth. Downgrade if credit trigger AND NOT contraction."""
    def rule(row):
        pctl = row.get("hy_oas_level_percentile")
        chg = row.get("hy_oas_3m_change")
        growth = row.get("growth_regime")
        if pctl is None or chg is None or pd.isna(pctl) or pd.isna(chg):
            return False
        credit_trigger = pctl < x_thresh and chg < y_thresh
        not_contraction = growth != "contraction"
        return credit_trigger and not_contraction
    return rule


def make_rule_c(x_thresh, y_thresh):
    """Rule C: Credit + Growth + Curve. Three-factor filter."""
    def rule(row):
        pctl = row.get("hy_oas_level_percentile")
        chg = row.get("hy_oas_3m_change")
        growth = row.get("growth_regime")
        curve = row.get("curve_regime")
        if pctl is None or chg is None or pd.isna(pctl) or pd.isna(chg):
            return False
        credit_trigger = pctl < x_thresh and chg < y_thresh
        not_contraction = growth != "contraction"
        not_stressed_curve = curve not in ("inverted", "flat")
        return credit_trigger and not_contraction and not_stressed_curve
    return rule


# ---------------------------------------------------------------------------
# Threshold optimization (grid search)
# ---------------------------------------------------------------------------

def optimize_thresholds(df, rule_factory, label_col="label_moderate_tp"):
    """Grid search over (X, Y) to maximize weighted objective.

    Trains on pre-2020 data, evaluates on 2020+ holdout.
    """
    train = df[df["signal_date"] <= TRAIN_END].copy()
    holdout = df[df["signal_date"] > TRAIN_END].copy()

    best_score = -1
    best_x = None
    best_y = None
    best_train_metrics = None
    best_holdout_metrics = None
    grid_results = []

    for x in X_GRID:
        for y in Y_GRID:
            rule_fn = rule_factory(x, y)
            train_m = evaluate_rule(train, rule_fn, label_col)

            # Objective: TP retention × 0.6 + FP reduction × 0.4
            score = (train_m["tps_retained_pct"] / 100 * W_TP +
                     train_m["fps_removed_pct"] / 100 * W_FP)

            grid_results.append({
                "x": x, "y": y,
                "score": round(score, 4),
                "train_tp_ret": train_m["tps_retained_pct"],
                "train_fp_red": train_m["fps_removed_pct"],
            })

            if score > best_score:
                best_score = score
                best_x = x
                best_y = y
                best_train_metrics = train_m

    # Evaluate best on holdout
    if best_x is not None and len(holdout) > 0:
        best_holdout_metrics = evaluate_rule(
            holdout, rule_factory(best_x, best_y), label_col
        )
    else:
        best_holdout_metrics = {}

    return {
        "best_x": best_x,
        "best_y": best_y,
        "best_score": round(best_score, 4),
        "train_metrics": best_train_metrics,
        "holdout_metrics": best_holdout_metrics,
        "grid_results": grid_results,
    }


# ---------------------------------------------------------------------------
# Generate filtered signal CSVs
# ---------------------------------------------------------------------------

def generate_filtered_csv(full_quintiles, df, rule_fn, rule_name):
    """Generate filtered quintile series CSV.

    full_quintiles: pd.Series of all quintiles (Q1-Q5)
    df: diagnostic DataFrame (Q4/Q5 rows only)
    rule_fn: filter function
    """
    df = _add_covid_flag(df)

    # Build set of dates to downgrade
    downgrade_dates = set()
    filter_reasons = {}
    for _, row in df.iterrows():
        if row["is_covid_preserve"]:
            continue
        if rule_fn(row):
            downgrade_dates.add(row["signal_date"])
            filter_reasons[row["signal_date"]] = rule_name

    # Build output
    records = []
    for dt, q in full_quintiles.items():
        date_str = dt.strftime("%Y-%m-%d")
        filtered_q = 3 if date_str in downgrade_dates else int(q)
        triggered = date_str in downgrade_dates
        records.append({
            "signal_date": date_str,
            "original_quintile": int(q),
            "filtered_quintile": filtered_q,
            "filter_triggered": triggered,
            "filter_reason": filter_reasons.get(date_str),
        })

    out_df = pd.DataFrame(records)
    path = os.path.join(OUTPUT_DIR, f"filtered_signal_{rule_name}.csv")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_df.to_csv(path, index=False)
    return out_df, path


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run_phase2_analysis(phase1_result):
    """Run Phase 2 analysis using Phase 1 diagnostic result.

    Args:
        phase1_result: dict from run_diagnostic() with 'full_dataset',
                       'quintile_distribution', etc.

    Returns:
        Structured dict for API response.
    """
    print("[PHASE2] Starting filter analysis...")

    full_dataset = phase1_result.get("full_dataset", [])
    if not full_dataset:
        return {"error": "No Phase 1 data. Run Phase 1 diagnostic first."}

    df = pd.DataFrame(full_dataset)
    print(f"[PHASE2] Dataset: {len(df)} Q4/Q5 signals")

    # ── 1. Univariate analysis ───────────────────────────────────────────
    print("[PHASE2] Computing univariate statistics...")
    univariate = compute_univariate_stats(df.copy())
    print(f"[PHASE2] {len(univariate)} variables analyzed")

    for i, v in enumerate(univariate[:5]):
        print(f"  #{i+1} {v['variable']}: AUC={v['auc']}, "
              f"KS={v['ks_stat']}, TP_ret={v['tp_retention']}%, "
              f"FP_red={v['fp_reduction']}%")

    # ── 2. Optimize each rule ────────────────────────────────────────────
    print("[PHASE2] Optimizing Rule A (Credit-Only)...")
    opt_a = optimize_thresholds(df, make_rule_a)
    print(f"  Best: X={opt_a['best_x']}, Y={opt_a['best_y']}, "
          f"score={opt_a['best_score']}")

    print("[PHASE2] Optimizing Rule B (Credit + Growth)...")
    opt_b = optimize_thresholds(df, make_rule_b)
    print(f"  Best: X={opt_b['best_x']}, Y={opt_b['best_y']}, "
          f"score={opt_b['best_score']}")

    print("[PHASE2] Optimizing Rule C (Credit + Growth + Curve)...")
    opt_c = optimize_thresholds(df, make_rule_c)
    print(f"  Best: X={opt_c['best_x']}, Y={opt_c['best_y']}, "
          f"score={opt_c['best_score']}")

    # ── 3. Evaluate all rules on full dataset ────────────────────────────
    rule_a_fn = make_rule_a(opt_a["best_x"], opt_a["best_y"])
    rule_b_fn = make_rule_b(opt_b["best_x"], opt_b["best_y"])
    rule_c_fn = make_rule_c(opt_c["best_x"], opt_c["best_y"])

    eval_none = evaluate_rule(df, lambda r: False)
    eval_a = evaluate_rule(df, rule_a_fn)
    eval_b = evaluate_rule(df, rule_b_fn)
    eval_c = evaluate_rule(df, rule_c_fn)

    # ── 4. Determine winner (best holdout score) ────────────────────────
    holdout_scores = {
        "rule_a": (opt_a["holdout_metrics"].get("tps_retained_pct", 0) / 100 * W_TP +
                   opt_a["holdout_metrics"].get("fps_removed_pct", 0) / 100 * W_FP),
        "rule_b": (opt_b["holdout_metrics"].get("tps_retained_pct", 0) / 100 * W_TP +
                   opt_b["holdout_metrics"].get("fps_removed_pct", 0) / 100 * W_FP),
        "rule_c": (opt_c["holdout_metrics"].get("tps_retained_pct", 0) / 100 * W_TP +
                   opt_c["holdout_metrics"].get("fps_removed_pct", 0) / 100 * W_FP),
    }
    winning_rule = max(holdout_scores, key=holdout_scores.get)

    print(f"\n[PHASE2] Holdout scores: A={holdout_scores['rule_a']:.3f}, "
          f"B={holdout_scores['rule_b']:.3f}, C={holdout_scores['rule_c']:.3f}")
    print(f"[PHASE2] Winner: {winning_rule}")

    # ── 5. Generate filtered signal CSVs ─────────────────────────────────
    # We need the full quintile series — reconstruct from Phase 1
    # For now, generate filter trigger lists for each rule
    filtered_a = []
    filtered_b = []
    filtered_c = []
    df_covid = _add_covid_flag(df)
    for _, row in df_covid.iterrows():
        base = {
            "signal_date": row["signal_date"],
            "original_quintile": int(row["quintile"]),
            "is_covid": bool(row["is_covid_preserve"]),
        }
        # Rule A
        triggered_a = not row["is_covid_preserve"] and rule_a_fn(row)
        filtered_a.append({**base,
            "filtered_quintile": 3 if triggered_a else int(row["quintile"]),
            "filter_triggered": triggered_a,
        })
        # Rule B
        triggered_b = not row["is_covid_preserve"] and rule_b_fn(row)
        filtered_b.append({**base,
            "filtered_quintile": 3 if triggered_b else int(row["quintile"]),
            "filter_triggered": triggered_b,
        })
        # Rule C
        triggered_c = not row["is_covid_preserve"] and rule_c_fn(row)
        filtered_c.append({**base,
            "filtered_quintile": 3 if triggered_c else int(row["quintile"]),
            "filter_triggered": triggered_c,
        })

    # Save CSVs
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        for name, data in [("rule_a", filtered_a), ("rule_b", filtered_b), ("rule_c", filtered_c)]:
            pd.DataFrame(data).to_csv(
                os.path.join(OUTPUT_DIR, f"filtered_signal_{name}.csv"), index=False
            )
    except Exception as e:
        print(f"[PHASE2] CSV save failed: {e}")

    # ── 6. Build result ──────────────────────────────────────────────────
    def _rule_result(name, opt, eval_full, eval_label, rule_factory):
        return {
            "name": name,
            "label": eval_label,
            "thresholds": {"x": opt["best_x"], "y": opt["best_y"]},
            "train_score": opt["best_score"],
            "holdout_score": round(holdout_scores[name], 4),
            "full_metrics": eval_full,
            "train_metrics": opt["train_metrics"],
            "holdout_metrics": opt["holdout_metrics"],
        }

    result = {
        "univariate_rankings": univariate[:20],
        "rule_comparisons": {
            "no_filter": eval_none,
            "rule_a": _rule_result("rule_a", opt_a, eval_a,
                                    f"Credit-Only (pctl<{opt_a['best_x']}, 3m<{opt_a['best_y']}bps)",
                                    make_rule_a),
            "rule_b": _rule_result("rule_b", opt_b, eval_b,
                                    f"Credit+Growth (pctl<{opt_b['best_x']}, 3m<{opt_b['best_y']}bps, !contraction)",
                                    make_rule_b),
            "rule_c": _rule_result("rule_c", opt_c, eval_c,
                                    f"Credit+Growth+Curve (pctl<{opt_c['best_x']}, 3m<{opt_c['best_y']}bps, !contraction, !inv/flat)",
                                    make_rule_c),
        },
        "winning_rule": winning_rule,
        "filtered_signals": {
            "rule_a": filtered_a,
            "rule_b": filtered_b,
            "rule_c": filtered_c,
        },
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "from_cache": False,
    }

    return result


# ---------------------------------------------------------------------------
# Standalone CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from research.diagnostic_builder import run_diagnostic

    print("=" * 70)
    print("  PHASE 2 — FILTER RULE ANALYSIS")
    print("=" * 70)

    print("\n[1] Running Phase 1 diagnostic...")
    p1 = run_diagnostic(use_cache=False)
    if "error" in p1:
        print(f"  Phase 1 failed: {p1['error']}")
        sys.exit(1)

    print("\n[2] Running Phase 2 analysis...")
    result = run_phase2_analysis(p1)

    if "error" in result:
        print(f"  Phase 2 failed: {result['error']}")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("  RESULTS")
    print("=" * 70)

    print("\n  UNIVARIATE RANKING (top 10)")
    print(f"  {'Variable':<25} {'AUC':>6} {'KS':>6} {'Thresh':>8} {'TP%':>6} {'FP%':>6}")
    print("  " + "-" * 60)
    for v in result["univariate_rankings"][:10]:
        print(f"  {v['variable']:<25} {v['auc']:>6.3f} {v['ks_stat']:>6.3f} "
              f"{str(v['optimal_threshold']):>8} {v['tp_retention']:>5.1f}% {v['fp_reduction']:>5.1f}%")

    print("\n  RULE COMPARISON")
    rc = result["rule_comparisons"]
    print(f"  {'Rule':<12} {'Kept':>5} {'TPs Ret':>10} {'FPs Rem':>10} {'COVID':>7} {'Acc':>6}")
    print("  " + "-" * 55)
    for key in ["no_filter", "rule_a", "rule_b", "rule_c"]:
        m = rc[key] if key == "no_filter" else rc[key]["full_metrics"]
        label = "No Filter" if key == "no_filter" else key.upper()
        print(f"  {label:<12} {m['signals_kept']:>5} "
              f"{m['tps_retained']:>4} ({m['tps_retained_pct']:>5.1f}%) "
              f"{m['fps_removed']:>4} ({m['fps_removed_pct']:>5.1f}%) "
              f"{m['covid_preserved']:>7} {m['accuracy']:>5.1f}%")

    print(f"\n  WINNER: {result['winning_rule'].upper()}")
