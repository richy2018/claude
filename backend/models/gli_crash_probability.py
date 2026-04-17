"""GLI Crash Probability — Logistic Regression for P(crash in next 3M).

Expanding-window logistic regression with L2 regularization.
Features: 5 factor z-scores + signal momentum + consensus + VIX + curve.
Reports OOS ROC-AUC, precision, recall, calibration, and full backtest.
"""

import numpy as np
import pandas as pd

from .backtest_engine import (
    _extract_components, SIGNAL_TRANSFORMS, PRODUCTION_MODELS,
    ALLOCATION_RULES, sortino_ratio, COMP_LABELS, sharpe_ratio,
    _old_sharpe_geometric, rf_from_fred,
)

_PROD = PRODUCTION_MODELS["5f"]
_PROD_KEYS = _PROD["keys"]
_PROD_WEIGHTS = _PROD["weights"]
_SIG_FN = SIGNAL_TRANSFORMS["mom6"][1]

TAIL_EVENTS = [
    {"name": "GFC", "start": "2007-09-01"},
    {"name": "COVID", "start": "2020-02-01"},
    {"name": "Rate Shock", "start": "2022-01-01"},
    {"name": "Vol Shock Q4-2018", "start": "2018-10-01"},
]


def _build_features(components, signal, spy_monthly, vix_data=None, fred_data=None):
    """Build feature matrix for logistic regression. All observable at time t."""
    common = signal.index
    features = pd.DataFrame(index=common)

    for k in _PROD_KEYS:
        if k in components:
            features[k] = components[k].reindex(common, method="ffill").fillna(0)

    features["sig_mom1"] = signal.diff(1)
    features["sig_mom3"] = signal.diff(3)

    consensus = pd.Series(0.0, index=common)
    for k in _PROD_KEYS:
        if k in components:
            s = components[k].reindex(common, method="ffill").fillna(0)
            median_12 = s.rolling(12, min_periods=6).median()
            consensus += (s > median_12).astype(float)
    features["consensus"] = consensus

    if vix_data is not None and len(vix_data) > 12:
        vix_m = vix_data.resample("MS").last().dropna()
        features["vix"] = vix_m.reindex(common, method="ffill").fillna(20)
        features["vix_mom1"] = features["vix"].diff(1)

    if fred_data is not None and isinstance(fred_data, pd.DataFrame):
        if "T10Y2Y" in fred_data.columns:
            curve = fred_data["T10Y2Y"].dropna().resample("MS").last()
            features["curve_slope"] = curve.reindex(common, method="ffill").fillna(1.5)

    # Signal quintile (expanding window — sampled every 3M for speed)
    quintiles = pd.Series(3, index=common, dtype=int)
    for i in range(20, len(signal)):
        hist = signal.iloc[:i+1]
        pct = float((hist <= hist.iloc[-1]).mean()) * 100
        quintiles.iloc[i] = 1 if pct < 20 else 2 if pct < 40 else 3 if pct < 60 else 4 if pct < 80 else 5
    features["quintile"] = quintiles

    return features.dropna()


def _build_target(spy_monthly, feature_index):
    """Target: 1 if 3M forward return < -10%, else 0.

    Uses simple forward return (not max drawdown) for more positive cases.
    -10% threshold captures GFC, COVID, 2022, 2018-Q4 and borderline events.
    """
    spy_ret = spy_monthly.pct_change().dropna()
    target = pd.Series(0, index=feature_index, dtype=int)

    # 3M cumulative forward return
    fwd_3m = spy_ret.rolling(3).sum().shift(-3)  # Approx 3M forward return
    fwd_aligned = fwd_3m.reindex(feature_index)

    target[fwd_aligned < -0.10] = 1  # < -10% in next 3 months
    return target


def run_crash_probability(ratio_series, spy_monthly, vix_data=None, fred_data=None):
    """Run expanding-window logistic regression for crash probability."""
    # Lazy import — don't crash the module if sklearn not installed
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score, precision_score, recall_score
    except ImportError:
        return {"error": "scikit-learn not installed. Run: pip install scikit-learn"}

    components = _extract_components(ratio_series)
    missing = [k for k in _PROD_KEYS if k not in components]
    if missing:
        return {"error": f"Missing: {missing}"}

    # Build signal
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

    print("[CRASH PROB] Building features...")
    features = _build_features(components, signal, spy_monthly, vix_data, fred_data)

    print("[CRASH PROB] Building target (3M fwd return < -10%)...")
    target = _build_target(spy_monthly, features.index)

    common = features.index.intersection(target.dropna().index)
    X = features.reindex(common).fillna(0)
    y = target.reindex(common).fillna(0)

    n_crashes = int(y.sum())
    print(f"[CRASH PROB] {len(X)} months, {n_crashes} crash months ({n_crashes/len(X)*100:.1f}%)")

    if n_crashes < 3:
        return {"error": f"Only {n_crashes} crash months — insufficient for logistic regression"}

    # Expanding-window predictions (refit every 3 months for speed)
    min_train = 60
    predictions = pd.Series(np.nan, index=common)
    feature_names = list(X.columns)
    current_model = None

    print(f"[CRASH PROB] Expanding-window logistic regression (refit every 3M)...")
    for i in range(min_train, len(common)):
        # Refit every 3 months or if no model yet
        if current_model is None or i % 3 == 0:
            X_train = X.iloc[:i].values
            y_train = y.iloc[:i].values
            if y_train.sum() < 2:
                predictions.iloc[i] = 0.02
                continue
            try:
                current_model = LogisticRegression(C=1.0, class_weight="balanced",
                                                    max_iter=500, random_state=42)
                current_model.fit(X_train, y_train)
            except Exception as e:
                print(f"[CRASH PROB] Fit error at {i}: {e}")
                predictions.iloc[i] = 0.02
                continue

        try:
            prob = current_model.predict_proba(X.iloc[i:i+1].values)[0, 1]
            predictions.iloc[i] = prob
        except Exception:
            predictions.iloc[i] = 0.02

    # OOS evaluation
    oos_mask = predictions.notna()
    y_oos = y[oos_mask]
    p_oos = predictions[oos_mask]

    if len(y_oos) < 30:
        return {"error": f"Not enough OOS data ({len(y_oos)} months)"}

    try:
        roc_auc = round(roc_auc_score(y_oos, p_oos), 3) if y_oos.sum() >= 2 else None
    except Exception:
        roc_auc = None

    y_pred_20 = (p_oos >= 0.20).astype(int)
    prec_20 = round(precision_score(y_oos, y_pred_20, zero_division=0), 3)
    rec_20 = round(recall_score(y_oos, y_pred_20, zero_division=0), 3)

    print(f"[CRASH PROB] OOS: AUC={roc_auc}, Prec@20%={prec_20}, Rec@20%={rec_20}")

    # Allocation mappings
    def _prob_to_alloc(p):
        if p < 0.10: return 1.0
        if p < 0.20: return 0.80
        if p < 0.40: return 0.50
        if p < 0.60: return 0.20
        return 0.05

    alloc_discrete = predictions.apply(lambda p: _prob_to_alloc(p) if pd.notna(p) else 1.0)
    alloc_continuous = predictions.apply(lambda p: max(0.05, 1.0 - 2.0 * p) if pd.notna(p) else 1.0)

    spy_ret = spy_monthly.pct_change().dropna()
    rf_monthly = rf_from_fred(fred_data, spy_ret.index)
    discrete_metrics = _backtest_prob(alloc_discrete, spy_ret, vix_data, rf_monthly=rf_monthly)
    continuous_metrics = _backtest_prob(alloc_continuous, spy_ret, vix_data, rf_monthly=rf_monthly)

    # Baseline
    quintiles = pd.Series(3, index=signal.index, dtype=int)
    for i in range(20, len(signal)):
        hist = signal.iloc[:i+1]
        pct = float((hist <= hist.iloc[-1]).mean()) * 100
        quintiles.iloc[i] = 1 if pct < 20 else 2 if pct < 40 else 3 if pct < 60 else 4 if pct < 80 else 5
    base_weights = quintiles.map(ALLOCATION_RULES["production"]).astype(float)
    baseline_metrics = _backtest_prob(base_weights, spy_ret, vix_data, rf_monthly=rf_monthly)

    # Crash detection
    crash_probs = []
    for event in TAIL_EVENTS:
        d = pd.Timestamp(event["start"])
        p = float(predictions.get(d, 0)) if d in predictions.index else None
        a = float(alloc_discrete.get(d, 1)) if d in alloc_discrete.index else None
        crash_probs.append({"event": event["name"],
                            "probability": round(p, 3) if p is not None else None,
                            "allocation": round(a, 2) if a is not None else None,
                            "detected": a is not None and a < 0.5})
    detected = sum(1 for c in crash_probs if c["detected"])

    # Calibration
    calibration = []
    for lo, hi in [(0, 0.1), (0.1, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 1.0)]:
        mask = (p_oos >= lo) & (p_oos < hi)
        n = int(mask.sum())
        if n > 0:
            calibration.append({"bin": f"{int(lo*100)}-{int(hi*100)}%", "n": n,
                                "predicted_avg": round(float(p_oos[mask].mean()) * 100, 1),
                                "actual_rate": round(float(y_oos[mask].mean()) * 100, 1)})

    # Feature importance
    feature_importance = []
    try:
        model = LogisticRegression(C=1.0, class_weight="balanced", max_iter=500, random_state=42)
        model.fit(X.values, y.values)
        importance = sorted(zip(feature_names, model.coef_[0]), key=lambda x: abs(x[1]), reverse=True)
        feature_importance = [{"feature": COMP_LABELS.get(f, f), "coefficient": round(float(c), 3)}
                              for f, c in importance[:8]]
    except Exception:
        pass

    return {
        "roc_auc": roc_auc,
        "precision_at_20pct": prec_20,
        "recall_at_20pct": rec_20,
        "n_oos_months": int(oos_mask.sum()),
        "n_crash_months": n_crashes,
        "discrete_metrics": discrete_metrics,
        "continuous_metrics": continuous_metrics,
        "baseline_metrics": baseline_metrics,
        "crash_detection": {"detected": detected, "total": 4, "details": crash_probs},
        "calibration": calibration,
        "feature_importance": feature_importance,
        "current_probability": round(float(predictions.iloc[-1]), 3) if len(predictions) > 0 and pd.notna(predictions.iloc[-1]) else None,
    }


def _backtest_prob(weights, spy_ret, vix_data=None, target_vol=0.10, rf_monthly=None):
    """Backtest from weights series with vol-scaling. Cash leg earns rf_monthly."""
    common = weights.index.intersection(spy_ret.index)
    w = weights.reindex(common).fillna(1.0)
    r = spy_ret.reindex(common).fillna(0)

    if vix_data is not None and len(vix_data) > 12:
        vix_m = vix_data.resample("MS").last().dropna() / 100
        realized = r.rolling(5, min_periods=3).std() * np.sqrt(12)
        realized = realized.clip(lower=0.05)
        vix_al = vix_m.reindex(common, method="ffill")
        vol = vix_al.fillna(realized).clip(lower=0.05)
        vs = (target_vol / vol).clip(upper=2.0)
        w = (w * vs).clip(0, 1)

    rf_m = rf_monthly.reindex(common, method="ffill").fillna(0.0) if rf_monthly is not None else pd.Series(0.0, index=common)
    port_ret = r * w + rf_m * (1 - w)
    eq = (1 + port_ret).cumprod()
    years = len(port_ret) / 12
    ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
    ann_vol = float(port_ret.std() * np.sqrt(12))
    sharpe = sharpe_ratio(port_ret, rf=rf_monthly)
    sharpe_old = _old_sharpe_geometric(r * w)
    sort = sortino_ratio(port_ret, rf=rf_monthly)
    peak = eq.expanding().max()
    max_dd = round(float(((eq - peak) / peak).min()) * 100, 1)
    total = round(float(eq.iloc[-1] - 1) * 100, 1)
    pct_def = round(float((w < 0.5).mean()) * 100, 1)
    return {"sharpe": sharpe, "sharpe_old_geometric": sharpe_old,
            "sortino": sort, "max_dd": max_dd,
            "total_return": total, "ann_return": round(ann_ret * 100, 2),
            "pct_defensive": pct_def}
