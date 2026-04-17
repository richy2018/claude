"""GLI Forward Horizon Analysis — test signal against 1M/3M/6M/12M forward SPX returns.

Uses SPY adjusted close (total return with dividends) for fair benchmark.
Cash yield = historical monthly Fed Funds rate on uninvested capital.
Includes Sortino ratio, equity curves, and drawdown charts.
Supports multi-model comparison (3FA_EQ, 5F, 2F, etc.).
"""

import numpy as np
import pandas as pd

from .backtest_engine import (
    _extract_components, SIGNAL_TRANSFORMS, PRODUCTION_MODELS,
    ALLOCATION_RULES, _signal_momentum, sortino_ratio, sharpe_ratio,
    _old_sharpe_geometric,
)

HORIZONS = [
    {"months": 1, "label": "1M", "transform": lambda c: _signal_momentum(c, 1)},
    {"months": 3, "label": "3M", "transform": lambda c: _signal_momentum(c, 3)},
    {"months": 6, "label": "6M", "transform": lambda c: _signal_momentum(c, 6)},
    {"months": 12, "label": "12M", "transform": lambda c: _signal_momentum(c, 12)},
]


def _build_composite_for_model(ratio_series, model_key):
    """Build composite for any model config."""
    cfg = PRODUCTION_MODELS.get(model_key)
    if not cfg:
        return None, None, f"Unknown model: {model_key}"
    components = _extract_components(ratio_series)
    keys = cfg["keys"]
    weights = cfg["weights"]
    missing = [k for k in keys if k not in components]
    if missing:
        return None, None, f"Missing for {model_key}: {missing}"
    base_idx = components[keys[0]].index
    for k in keys[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()
    comp = pd.Series(0.0, index=base_idx)
    for k in keys:
        if k in components:
            comp += weights[k] * components[k].reindex(base_idx, method="ffill").fillna(0)
    return comp, components, None


def _backtest_horizon(signal, spy_total_ret, alloc_map, vix_data=None,
                       ff_monthly=None, target_vol=0.10):
    """Run backtest for a signal using total return series + historical cash rates."""
    aligned = pd.concat([signal.rename("sig"), spy_total_ret.rename("ret")], axis=1).dropna()
    if len(aligned) < 30:
        return None

    try:
        quintiles = pd.qcut(aligned["sig"], 5, labels=[1, 2, 3, 4, 5], duplicates='drop')
    except Exception:
        return None

    base_w = quintiles.map(alloc_map).astype(float)

    # Vol-scaling: VIX where available, realized vol fallback
    if vix_data is not None and len(vix_data) > 12:
        vix_m = vix_data.resample("MS").last().dropna() / 100
        realized_vol = spy_total_ret.rolling(5, min_periods=3).std() * np.sqrt(12)
        realized_vol = realized_vol.clip(lower=0.05)
        vix_al = vix_m.reindex(aligned.index, method="ffill")
        vol_series = vix_al.fillna(realized_vol.reindex(aligned.index, method="ffill")).clip(lower=0.05)
        vs = (target_vol / vol_series).clip(upper=2.0)
        weights = (base_w * vs).clip(0, 1)
    else:
        weights = base_w

    cash_weight = 1.0 - weights

    # Historical monthly cash rate
    cash_rate_monthly = pd.Series(0.0, index=aligned.index)
    if ff_monthly is not None and len(ff_monthly) > 0:
        cash_rate_monthly = ff_monthly.reindex(aligned.index, method="ffill").fillna(0) / 100 / 12

    port_ret_no_cash = aligned["ret"] * weights
    eq_no = (1 + port_ret_no_cash).cumprod()

    port_ret_with_cash = aligned["ret"] * weights + cash_weight * cash_rate_monthly
    eq_cash = (1 + port_ret_with_cash).cumprod()

    bh_eq = (1 + aligned["ret"]).cumprod()

    def _metrics(port_ret, eq):
        years = len(port_ret) / 12
        ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
        ann_vol = float(port_ret.std() * np.sqrt(12))
        # Sharpe/Sortino via canonical arithmetic-excess helpers (Subtask A).
        sharpe = sharpe_ratio(port_ret, rf=cash_rate_monthly)
        sharpe_old = _old_sharpe_geometric(port_ret)
        sort = sortino_ratio(port_ret, rf=cash_rate_monthly)
        peak = eq.expanding().max()
        max_dd = round(float(((eq - peak) / peak).min()) * 100, 1)
        calmar = round(ann_ret / abs(max_dd / 100), 2) if abs(max_dd) > 0.1 else 0
        total = round(float(eq.iloc[-1] - 1) * 100, 1)
        return {"sharpe": sharpe, "sharpe_old_geometric": sharpe_old,
                "sortino": sort, "max_dd": max_dd, "calmar": calmar,
                "total_return": total, "ann_return": round(ann_ret * 100, 2),
                "ann_vol": round(ann_vol * 100, 2)}

    m_no_cash = _metrics(port_ret_no_cash, eq_no)
    m_with_cash = _metrics(port_ret_with_cash, eq_cash)

    bh_years = len(aligned) / 12
    bh_ann = float(bh_eq.iloc[-1] ** (1 / max(bh_years, 0.5)) - 1) if bh_eq.iloc[-1] > 0 else 0
    bh_vol = float(aligned["ret"].std() * np.sqrt(12))
    bh_peak = bh_eq.expanding().max()
    bh_dd = round(float(((bh_eq - bh_peak) / bh_peak).min()) * 100, 1)
    bh_total = round(float(bh_eq.iloc[-1] - 1) * 100, 1)

    defensive = (quintiles >= 4)
    pct_defensive = float(defensive.mean()) * 100
    q_changes = (quintiles.astype(int).diff().abs() > 0).sum()
    q_changes_per_year = round(q_changes / (len(quintiles) / 12), 1)

    total_cash_income = float((cash_weight * cash_rate_monthly).sum()) * 100

    dd_no = ((eq_no / eq_no.expanding().max()) - 1) * 100
    dd_cash = ((eq_cash / eq_cash.expanding().max()) - 1) * 100
    dd_bh = ((bh_eq / bh_eq.expanding().max()) - 1) * 100

    chart = []
    for d in eq_no.index:
        chart.append({
            "date": d.strftime("%Y-%m-%d"),
            "no_cash": round(float(eq_no[d]), 4),
            "with_cash": round(float(eq_cash[d]), 4),
            "buyhold": round(float(bh_eq[d]), 4),
            "dd_no_cash": round(float(dd_no[d]), 1),
            "dd_with_cash": round(float(dd_cash[d]), 1),
            "dd_buyhold": round(float(dd_bh[d]), 1),
        })

    return {
        "no_cash_yield": m_no_cash,
        "with_cash_yield": m_with_cash,
        "buyhold": {"total_return": bh_total, "ann_return": round(bh_ann * 100, 2),
                     "sharpe": sharpe_ratio(aligned["ret"], rf=cash_rate_monthly),
                     "sharpe_old_geometric": _old_sharpe_geometric(aligned["ret"]),
                     "sortino": sortino_ratio(aligned["ret"], rf=cash_rate_monthly), "max_dd": bh_dd},
        "pct_defensive": round(pct_defensive, 1),
        "months_defensive_per_year": round(pct_defensive / 100 * 12, 1),
        "q_changes_per_year": q_changes_per_year,
        "n_months": len(aligned),
        "chart": chart,
        "cash_yield_impact": round(m_with_cash["total_return"] - m_no_cash["total_return"], 1),
        "total_cash_income": round(total_cash_income, 1),
        "gap_vs_bh": round(m_with_cash["total_return"] - bh_total, 1),
    }


def _run_single_model(model_key, alloc_map, ratio_series, spy_monthly,
                        ff_monthly, vix_data):
    """Run horizon analysis for a single model."""
    comp, components, err = _build_composite_for_model(ratio_series, model_key)
    if err:
        return {"error": err, "model": model_key}

    cfg = PRODUCTION_MODELS[model_key]
    spy_total_ret = spy_monthly.pct_change().dropna()

    results = []
    for h in HORIZONS:
        signal = h["transform"](comp).dropna()
        if len(signal) < 30:
            continue

        spy_fwd = spy_monthly.pct_change(h["months"]).shift(-h["months"]) * 100
        corr_common = signal.dropna().index.intersection(spy_fwd.dropna().index)
        corr = round(float(signal.reindex(corr_common).corr(spy_fwd.reindex(corr_common))), 4) if len(corr_common) >= 30 else None

        m = _backtest_horizon(signal, spy_total_ret, alloc_map, vix_data, ff_monthly)
        if m is None:
            continue

        m["horizon"] = h["label"]
        m["horizon_months"] = h["months"]
        m["signal_corr"] = corr
        results.append(m)

        nc = m["no_cash_yield"]
        wc = m["with_cash_yield"]
        print(f"[HORIZON] {model_key}/{h['label']}: Sharpe={nc['sharpe']}/{wc['sharpe']}(+cash), "
              f"DD={nc['max_dd']}%, Def={m['pct_defensive']:.0f}%")

    if not results:
        return {"error": "No valid results", "model": model_key}

    summary = []
    for r in results:
        nc = r["no_cash_yield"]
        wc = r["with_cash_yield"]
        bh = r["buyhold"]
        summary.append({
            "horizon": r["horizon"], "signal_corr": r.get("signal_corr"),
            "sharpe_no_cash": nc["sharpe"], "sortino_no_cash": nc["sortino"],
            "sharpe_with_cash": wc["sharpe"], "sortino_with_cash": wc["sortino"],
            "max_dd": nc["max_dd"], "calmar_no_cash": nc["calmar"],
            "calmar_with_cash": wc["calmar"],
            "total_return_no_cash": nc["total_return"],
            "total_return_with_cash": wc["total_return"],
            "ann_return_with_cash": wc["ann_return"],
            "bh_total_return": bh["total_return"], "bh_sharpe": bh["sharpe"],
            "pct_defensive": r["pct_defensive"],
            "months_def_per_yr": r["months_defensive_per_year"],
            "q_changes_per_yr": r["q_changes_per_year"],
            "cash_yield_impact": r["cash_yield_impact"],
            "total_cash_income": r["total_cash_income"],
            "gap_vs_bh": r["gap_vs_bh"],
        })

    best_idx = max(range(len(summary)), key=lambda i: summary[i]["sharpe_with_cash"])
    for i, s in enumerate(summary):
        s["is_best"] = (i == best_idx)

    return {
        "model": model_key,
        "model_label": cfg["label"],
        "alloc_rule": alloc_map,
        "horizons": results,
        "summary": summary,
        "best_horizon": summary[best_idx]["horizon"],
    }


def run_horizon_analysis(ratio_series, spy_monthly, fred_data=None, vix_data=None):
    """Run forward horizon analysis for 3FA_EQ, 5F, and 2F models."""
    ff_monthly = None
    if fred_data is not None and isinstance(fred_data, pd.DataFrame):
        for col in ["FEDFUNDS", "DFF"]:
            if col in fred_data.columns:
                ff_monthly = fred_data[col].dropna().resample("MS").last()
                print(f"[HORIZON] Fed Funds: {len(ff_monthly)} obs, "
                      f"range {ff_monthly.iloc[0]:.2f}%-{ff_monthly.iloc[-1]:.2f}%, "
                      f"avg={ff_monthly.mean():.2f}%")
                break

    # Models to compare with their allocation rules
    models_to_run = [
        ("5f", ALLOCATION_RULES["production"]),      # Production: 5F + 100/100/100/10/10
        ("3fa_eq", {1: 1.0, 2: 0.8, 3: 0.8, 4: 0.6, 5: 0.2}),  # Former production
        ("2f", ALLOCATION_RULES["production"]),       # Market-only with production alloc
    ]

    model_results = {}
    for model_key, alloc in models_to_run:
        if model_key not in PRODUCTION_MODELS:
            continue
        print(f"\n[HORIZON] === {model_key.upper()} ({PRODUCTION_MODELS[model_key]['label']}) ===")
        result = _run_single_model(model_key, alloc, ratio_series, spy_monthly,
                                    ff_monthly, vix_data)
        model_results[model_key] = result

    # Cross-model comparison at 6M horizon (production transform)
    cross_comparison = []
    for mk, mr in model_results.items():
        if "error" in mr:
            continue
        h6 = next((s for s in mr.get("summary", []) if s["horizon"] == "6M"), None)
        if h6:
            cross_comparison.append({
                "model": mk,
                "model_label": PRODUCTION_MODELS[mk]["label"],
                "sharpe": h6["sharpe_with_cash"],
                "sortino": h6["sortino_with_cash"],
                "max_dd": h6["max_dd"],
                "calmar": h6["calmar_with_cash"],
                "total_return": h6["total_return_with_cash"],
                "gap_vs_bh": h6["gap_vs_bh"],
                "pct_defensive": h6["pct_defensive"],
            })
    cross_comparison.sort(key=lambda x: x["sharpe"], reverse=True)

    return {
        "models": model_results,
        "cross_comparison_6m": cross_comparison,
        "has_cash_yield": ff_monthly is not None,
        "current_ff_rate": round(float(ff_monthly.iloc[-1]), 2) if ff_monthly is not None and len(ff_monthly) > 0 else None,
        "avg_ff_rate": round(float(ff_monthly.mean()), 2) if ff_monthly is not None else None,
        "uses_total_return": True,
    }
