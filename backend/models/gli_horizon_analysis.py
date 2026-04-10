"""GLI Forward Horizon Analysis — test signal against 1M/3M/6M/12M forward SPX returns.

For each horizon: correlation, full backtest with production allocation + vol-scaling,
time in Q4+Q5, turnover. Also tests cash yield from Fed Funds on uninvested capital.
"""

import numpy as np
import pandas as pd

from .backtest_engine import (
    _extract_components, SIGNAL_TRANSFORMS, PRODUCTION_MODELS,
    ALLOCATION_RULES, _signal_momentum,
)

_3FA = PRODUCTION_MODELS["3fa_eq"]
_3FA_KEYS = _3FA["keys"]
_3FA_WEIGHTS = _3FA["weights"]
_ALLOC = ALLOCATION_RULES["production"]

HORIZONS = [
    {"months": 1, "label": "1M", "transform": lambda c: _signal_momentum(c, 1)},
    {"months": 3, "label": "3M", "transform": lambda c: _signal_momentum(c, 3)},
    {"months": 6, "label": "6M", "transform": lambda c: _signal_momentum(c, 6)},
    {"months": 12, "label": "12M", "transform": lambda c: _signal_momentum(c, 12)},
]


def _build_composite(ratio_series):
    """Build equal-weight 3FA composite (pre-transform)."""
    components = _extract_components(ratio_series)
    missing = [k for k in _3FA_KEYS if k not in components]
    if missing:
        return None, None, f"Missing: {missing}"
    base_idx = components[_3FA_KEYS[0]].index
    for k in _3FA_KEYS[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()
    comp = pd.Series(0.0, index=base_idx)
    for k in _3FA_KEYS:
        if k in components:
            comp += _3FA_WEIGHTS[k] * components[k].reindex(base_idx, method="ffill").fillna(0)
    return comp, components, None


def _backtest_horizon(signal, spy_monthly, vix_data=None, ff_monthly=None,
                       target_vol=0.10):
    """Run backtest for a signal. Returns metrics with and without cash yield."""
    spy_ret = spy_monthly.pct_change().dropna()
    aligned = pd.concat([signal.rename("sig"), spy_ret.rename("ret")], axis=1).dropna()
    if len(aligned) < 30:
        return None

    try:
        quintiles = pd.qcut(aligned["sig"], 5, labels=[1, 2, 3, 4, 5], duplicates='drop')
    except Exception:
        return None

    base_w = quintiles.map(_ALLOC).astype(float)

    # Vol-scaling
    if vix_data is not None and len(vix_data) > 12:
        vix_m = vix_data.resample("MS").last().dropna() / 100
        vix_al = vix_m.reindex(aligned.index, method="ffill").clip(lower=0.05)
        vs = (target_vol / vix_al).clip(upper=2.0)
        weights = (base_w * vs).clip(0, 1)
    else:
        weights = base_w

    cash_weight = 1.0 - weights  # Fraction in cash

    # --- Without cash yield ---
    port_ret_no_cash = aligned["ret"] * weights
    eq_no = (1 + port_ret_no_cash).cumprod()

    # --- With cash yield (Fed Funds / 12 monthly) ---
    port_ret_with_cash = port_ret_no_cash.copy()
    if ff_monthly is not None and len(ff_monthly) > 0:
        ff_m = ff_monthly.reindex(aligned.index, method="ffill").fillna(0) / 100 / 12
        cash_return = cash_weight * ff_m
        port_ret_with_cash = port_ret_no_cash + cash_return

    eq_cash = (1 + port_ret_with_cash).cumprod()
    bh_eq = (1 + aligned["ret"]).cumprod()

    # Metrics helper
    def _metrics(port_ret, eq):
        years = len(port_ret) / 12
        ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
        ann_vol = float(port_ret.std() * np.sqrt(12))
        sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 1e-8 else 0
        peak = eq.expanding().max()
        max_dd = round(float(((eq - peak) / peak).min()) * 100, 1)
        calmar = round(ann_ret / abs(max_dd / 100), 2) if abs(max_dd) > 0.1 else 0
        total = round(float(eq.iloc[-1] - 1) * 100, 1)
        return {
            "sharpe": sharpe, "max_dd": max_dd, "calmar": calmar,
            "total_return": total, "ann_return": round(ann_ret * 100, 2),
            "ann_vol": round(ann_vol * 100, 2),
        }

    m_no_cash = _metrics(port_ret_no_cash, eq_no)
    m_with_cash = _metrics(port_ret_with_cash, eq_cash)

    # Buy & hold metrics
    bh_years = len(aligned) / 12
    bh_ann = float(bh_eq.iloc[-1] ** (1 / max(bh_years, 0.5)) - 1) if bh_eq.iloc[-1] > 0 else 0
    bh_vol = float(aligned["ret"].std() * np.sqrt(12))
    bh_peak = bh_eq.expanding().max()
    bh_dd = round(float(((bh_eq - bh_peak) / bh_peak).min()) * 100, 1)

    # Time in Q4+Q5 (defensive months per year)
    defensive = (quintiles >= 4)
    pct_defensive = float(defensive.mean()) * 100
    months_defensive_per_year = round(pct_defensive / 100 * 12, 1)

    # Quintile changes per year (turnover)
    q_changes = (quintiles.astype(int).diff().abs() > 0).sum()
    q_changes_per_year = round(q_changes / (len(quintiles) / 12), 1)

    # Allocation turnover
    alloc_turnover = round(float(weights.diff().abs().mean()), 4)

    # Correlation with forward SPX
    spy_fwd = {}
    for h in [1, 3, 6, 12]:
        fwd = spy_monthly.pct_change(h).shift(-h) * 100
        common = signal.dropna().index.intersection(fwd.dropna().index)
        if len(common) >= 30:
            spy_fwd[f"corr_{h}m"] = round(float(signal.reindex(common).corr(fwd.reindex(common))), 4)
        else:
            spy_fwd[f"corr_{h}m"] = None

    # Equity curve chart (sampled)
    chart = []
    for d in eq_no.index[::max(1, len(eq_no) // 200)]:
        chart.append({
            "date": d.strftime("%Y-%m-%d"),
            "no_cash": round(float(eq_no[d]), 4),
            "with_cash": round(float(eq_cash[d]), 4),
            "buyhold": round(float(bh_eq[d]), 4),
        })

    return {
        "no_cash_yield": m_no_cash,
        "with_cash_yield": m_with_cash,
        "buyhold": {
            "total_return": round(float(bh_eq.iloc[-1] - 1) * 100, 1),
            "ann_return": round(bh_ann * 100, 2),
            "sharpe": round(bh_ann / bh_vol, 3) if bh_vol > 1e-8 else 0,
            "max_dd": bh_dd,
        },
        "correlations": spy_fwd,
        "pct_defensive": round(pct_defensive, 1),
        "months_defensive_per_year": months_defensive_per_year,
        "q_changes_per_year": q_changes_per_year,
        "alloc_turnover": alloc_turnover,
        "n_months": len(aligned),
        "chart": chart,
        "cash_yield_impact": round(m_with_cash["total_return"] - m_no_cash["total_return"], 1),
        "cash_yield_sharpe_impact": round(m_with_cash["sharpe"] - m_no_cash["sharpe"], 3),
    }


def run_horizon_analysis(ratio_series, spy_monthly, fred_data=None, vix_data=None):
    """Run forward horizon analysis across 1M/3M/6M/12M signal transforms."""
    comp, components, err = _build_composite(ratio_series)
    if err:
        return {"error": err}

    # Get Fed Funds rate for cash yield
    ff_monthly = None
    if fred_data is not None and isinstance(fred_data, pd.DataFrame):
        for col in ["FEDFUNDS", "DFF"]:
            if col in fred_data.columns:
                ff_monthly = fred_data[col].dropna().resample("MS").last()
                print(f"[HORIZON] Fed Funds: {len(ff_monthly)} obs, latest={ff_monthly.iloc[-1]:.2f}%")
                break
    if ff_monthly is None:
        print("[HORIZON] No Fed Funds data — cash yield will be 0")

    results = []
    for h in HORIZONS:
        print(f"[HORIZON] Testing {h['label']} signal transform...")
        signal = h["transform"](comp).dropna()
        if len(signal) < 30:
            print(f"[HORIZON] {h['label']}: not enough data ({len(signal)} pts)")
            continue

        m = _backtest_horizon(signal, spy_monthly, vix_data, ff_monthly)
        if m is None:
            continue

        m["horizon"] = h["label"]
        m["horizon_months"] = h["months"]
        results.append(m)

        nc = m["no_cash_yield"]
        wc = m["with_cash_yield"]
        print(f"[HORIZON] {h['label']}: Sharpe={nc['sharpe']} (no cash) / {wc['sharpe']} (with cash), "
              f"DD={nc['max_dd']}%, Def={m['pct_defensive']:.0f}%, Turn={m['q_changes_per_year']}/yr")

    if not results:
        return {"error": "No valid horizon results"}

    # Summary table
    summary = []
    for r in results:
        nc = r["no_cash_yield"]
        wc = r["with_cash_yield"]
        summary.append({
            "horizon": r["horizon"],
            "sharpe_no_cash": nc["sharpe"],
            "sharpe_with_cash": wc["sharpe"],
            "max_dd": nc["max_dd"],
            "calmar_no_cash": nc["calmar"],
            "calmar_with_cash": wc["calmar"],
            "total_return_no_cash": nc["total_return"],
            "total_return_with_cash": wc["total_return"],
            "ann_return_with_cash": wc["ann_return"],
            "pct_defensive": r["pct_defensive"],
            "months_def_per_yr": r["months_defensive_per_year"],
            "q_changes_per_yr": r["q_changes_per_year"],
            "cash_yield_impact": r["cash_yield_impact"],
            "correlations": r.get("correlations", {}),
        })

    # Find best by Sharpe (with cash yield)
    best_idx = max(range(len(summary)), key=lambda i: summary[i]["sharpe_with_cash"])
    for i, s in enumerate(summary):
        s["is_best"] = (i == best_idx)

    # Production baseline (6M) identification
    prod_idx = next((i for i, s in enumerate(summary) if s["horizon"] == "6M"), None)

    print(f"\n[HORIZON] Best: {summary[best_idx]['horizon']} (Sharpe={summary[best_idx]['sharpe_with_cash']} with cash)")
    if prod_idx is not None:
        print(f"[HORIZON] Production (6M): Sharpe={summary[prod_idx]['sharpe_with_cash']} with cash")

    return {
        "horizons": results,
        "summary": summary,
        "best_horizon": summary[best_idx]["horizon"],
        "production_horizon": "6M",
        "has_cash_yield": ff_monthly is not None,
        "current_ff_rate": round(float(ff_monthly.iloc[-1]), 2) if ff_monthly is not None and len(ff_monthly) > 0 else None,
    }


if __name__ == "__main__":
    print("=" * 60)
    print("GLI Forward Horizon Analysis")
    print("=" * 60)
    print("Call run_horizon_analysis(ratio_series, spy_monthly, fred_data, vix_data)")
