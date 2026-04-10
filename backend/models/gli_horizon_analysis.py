"""GLI Forward Horizon Analysis — test signal against 1M/3M/6M/12M forward SPX returns.

Uses SPY adjusted close (total return with dividends) for fair benchmark.
Cash yield = historical monthly Fed Funds rate on uninvested capital.
Includes Sortino ratio, equity curves, and drawdown charts.
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


def _sortino(monthly_returns, mar=0.0):
    """Sortino ratio: annualized return / annualized downside deviation."""
    if len(monthly_returns) < 12:
        return 0
    excess = monthly_returns - mar / 12  # monthly MAR
    downside = excess.clip(upper=0)
    downside_dev = float(np.sqrt((downside ** 2).mean()) * np.sqrt(12))
    eq = (1 + monthly_returns).cumprod()
    years = len(monthly_returns) / 12
    ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
    return round(ann_ret / downside_dev, 3) if downside_dev > 1e-8 else 0


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


def _backtest_horizon(signal, spy_total_ret, vix_data=None, ff_monthly=None,
                       target_vol=0.10):
    """Run backtest for a signal using total return series + historical cash rates."""
    aligned = pd.concat([signal.rename("sig"), spy_total_ret.rename("ret")], axis=1).dropna()
    if len(aligned) < 30:
        return None

    try:
        quintiles = pd.qcut(aligned["sig"], 5, labels=[1, 2, 3, 4, 5], duplicates='drop')
    except Exception:
        return None

    base_w = quintiles.map(_ALLOC).astype(float)

    # Vol-scaling: VIX where available, realized vol fallback for early dates
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

    # Historical monthly cash rate (Fed Funds / 12)
    cash_rate_monthly = pd.Series(0.0, index=aligned.index)
    if ff_monthly is not None and len(ff_monthly) > 0:
        cash_rate_monthly = ff_monthly.reindex(aligned.index, method="ffill").fillna(0) / 100 / 12

    # --- Without cash yield (price return only) ---
    port_ret_no_cash = aligned["ret"] * weights
    eq_no = (1 + port_ret_no_cash).cumprod()

    # --- With historical cash yield ---
    port_ret_with_cash = aligned["ret"] * weights + cash_weight * cash_rate_monthly
    eq_cash = (1 + port_ret_with_cash).cumprod()

    # --- Buy & hold total return benchmark ---
    bh_eq = (1 + aligned["ret"]).cumprod()

    def _metrics(port_ret, eq):
        years = len(port_ret) / 12
        ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
        ann_vol = float(port_ret.std() * np.sqrt(12))
        sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 1e-8 else 0
        sortino = _sortino(port_ret)
        peak = eq.expanding().max()
        max_dd = round(float(((eq - peak) / peak).min()) * 100, 1)
        calmar = round(ann_ret / abs(max_dd / 100), 2) if abs(max_dd) > 0.1 else 0
        total = round(float(eq.iloc[-1] - 1) * 100, 1)
        return {
            "sharpe": sharpe, "sortino": sortino, "max_dd": max_dd, "calmar": calmar,
            "total_return": total, "ann_return": round(ann_ret * 100, 2),
            "ann_vol": round(ann_vol * 100, 2),
        }

    m_no_cash = _metrics(port_ret_no_cash, eq_no)
    m_with_cash = _metrics(port_ret_with_cash, eq_cash)

    # B&H metrics (total return with dividends)
    bh_years = len(aligned) / 12
    bh_ann = float(bh_eq.iloc[-1] ** (1 / max(bh_years, 0.5)) - 1) if bh_eq.iloc[-1] > 0 else 0
    bh_vol = float(aligned["ret"].std() * np.sqrt(12))
    bh_peak = bh_eq.expanding().max()
    bh_dd = round(float(((bh_eq - bh_peak) / bh_peak).min()) * 100, 1)
    bh_total = round(float(bh_eq.iloc[-1] - 1) * 100, 1)

    # Defensive metrics
    defensive = (quintiles >= 4)
    pct_defensive = float(defensive.mean()) * 100
    months_defensive_per_year = round(pct_defensive / 100 * 12, 1)
    q_changes = (quintiles.astype(int).diff().abs() > 0).sum()
    q_changes_per_year = round(q_changes / (len(quintiles) / 12), 1)

    # Total cash yield contribution over backtest
    total_cash_income = float((cash_weight * cash_rate_monthly).sum()) * 100
    avg_cash_rate = float(cash_rate_monthly.mean()) * 12 * 100  # Annualized average

    # Drawdown series for chart
    dd_no = ((eq_no / eq_no.expanding().max()) - 1) * 100
    dd_cash = ((eq_cash / eq_cash.expanding().max()) - 1) * 100
    dd_bh = ((bh_eq / bh_eq.expanding().max()) - 1) * 100

    # Chart data
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
        "buyhold": {
            "total_return": bh_total,
            "ann_return": round(bh_ann * 100, 2),
            "sharpe": round(bh_ann / bh_vol, 3) if bh_vol > 1e-8 else 0,
            "sortino": _sortino(aligned["ret"]),
            "max_dd": bh_dd,
        },
        "pct_defensive": round(pct_defensive, 1),
        "months_defensive_per_year": months_defensive_per_year,
        "q_changes_per_year": q_changes_per_year,
        "n_months": len(aligned),
        "chart": chart,
        "cash_yield_impact": round(m_with_cash["total_return"] - m_no_cash["total_return"], 1),
        "cash_yield_sharpe_impact": round(m_with_cash["sharpe"] - m_no_cash["sharpe"], 3),
        "total_cash_income": round(total_cash_income, 1),
        "avg_cash_rate": round(avg_cash_rate, 2),
        "gap_vs_bh": round(m_with_cash["total_return"] - bh_total, 1),
    }


def run_horizon_analysis(ratio_series, spy_monthly, fred_data=None, vix_data=None):
    """Run forward horizon analysis across 1M/3M/6M/12M.

    Uses SPY adjusted close (total return) and historical Fed Funds for cash.
    """
    comp, components, err = _build_composite(ratio_series)
    if err:
        return {"error": err}

    # Get Fed Funds rate for historical cash yield
    ff_monthly = None
    if fred_data is not None and isinstance(fred_data, pd.DataFrame):
        for col in ["FEDFUNDS", "DFF"]:
            if col in fred_data.columns:
                ff_monthly = fred_data[col].dropna().resample("MS").last()
                print(f"[HORIZON] Fed Funds: {len(ff_monthly)} obs, "
                      f"range {ff_monthly.iloc[0]:.2f}%-{ff_monthly.iloc[-1]:.2f}%, "
                      f"avg={ff_monthly.mean():.2f}%")
                break
    if ff_monthly is None:
        print("[HORIZON] No Fed Funds data — cash yield will be 0")

    # Use SPY total return (adjusted close includes dividends)
    spy_total_ret = spy_monthly.pct_change().dropna()

    results = []
    for h in HORIZONS:
        print(f"[HORIZON] Testing {h['label']} signal transform...")
        signal = h["transform"](comp).dropna()
        if len(signal) < 30:
            print(f"[HORIZON] {h['label']}: not enough data ({len(signal)} pts)")
            continue

        # Correlation with forward SPX returns at this horizon
        spy_fwd = spy_monthly.pct_change(h["months"]).shift(-h["months"]) * 100
        corr_common = signal.dropna().index.intersection(spy_fwd.dropna().index)
        corr = round(float(signal.reindex(corr_common).corr(spy_fwd.reindex(corr_common))), 4) if len(corr_common) >= 30 else None

        m = _backtest_horizon(signal, spy_total_ret, vix_data, ff_monthly)
        if m is None:
            continue

        m["horizon"] = h["label"]
        m["horizon_months"] = h["months"]
        m["signal_corr"] = corr
        results.append(m)

        nc = m["no_cash_yield"]
        wc = m["with_cash_yield"]
        print(f"[HORIZON] {h['label']}: Sharpe={nc['sharpe']}/{wc['sharpe']}(+cash), "
              f"Sortino={nc['sortino']}/{wc['sortino']}(+cash), "
              f"DD={nc['max_dd']}%, Def={m['pct_defensive']:.0f}%, "
              f"CashΔ={m['cash_yield_impact']}%, Gap={m['gap_vs_bh']}%")

    if not results:
        return {"error": "No valid horizon results"}

    # Summary table
    summary = []
    for r in results:
        nc = r["no_cash_yield"]
        wc = r["with_cash_yield"]
        bh = r["buyhold"]
        summary.append({
            "horizon": r["horizon"],
            "signal_corr": r.get("signal_corr"),
            "sharpe_no_cash": nc["sharpe"],
            "sortino_no_cash": nc["sortino"],
            "sharpe_with_cash": wc["sharpe"],
            "sortino_with_cash": wc["sortino"],
            "max_dd": nc["max_dd"],
            "calmar_no_cash": nc["calmar"],
            "calmar_with_cash": wc["calmar"],
            "total_return_no_cash": nc["total_return"],
            "total_return_with_cash": wc["total_return"],
            "ann_return_with_cash": wc["ann_return"],
            "bh_total_return": bh["total_return"],
            "bh_sharpe": bh["sharpe"],
            "bh_sortino": bh["sortino"],
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

    prod_idx = next((i for i, s in enumerate(summary) if s["horizon"] == "6M"), None)

    print(f"\n[HORIZON] Best: {summary[best_idx]['horizon']} "
          f"(Sharpe={summary[best_idx]['sharpe_with_cash']}, "
          f"Sortino={summary[best_idx]['sortino_with_cash']})")

    return {
        "horizons": results,
        "summary": summary,
        "best_horizon": summary[best_idx]["horizon"],
        "production_horizon": "6M",
        "has_cash_yield": ff_monthly is not None,
        "current_ff_rate": round(float(ff_monthly.iloc[-1]), 2) if ff_monthly is not None and len(ff_monthly) > 0 else None,
        "avg_ff_rate": round(float(ff_monthly.mean()), 2) if ff_monthly is not None else None,
        "uses_total_return": True,
    }


if __name__ == "__main__":
    print("GLI Forward Horizon Analysis")
    print("Call run_horizon_analysis(ratio_series, spy_monthly, fred_data, vix_data)")
    print("spy_monthly should be from SPY Adj Close (includes dividends)")
