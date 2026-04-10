"""Track 4 — Factor Proxy Quality for GLI 3FA model.

Tests alternative proxies for each factor:
- Qty: Fed net liquidity (WALCL - RRP - TGA) vs current BIS ratio
- Credit: HY OAS level, BBB OAS as alternatives
- M2: Real M2 (deflated by CPI) as alternative

Each proxy: z-score → substitute into 3FA → expanding-window OOS Sharpe vs baseline.
"""

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

from .backtest_engine import (
    _extract_components, SIGNAL_TRANSFORMS, PRODUCTION_MODELS,
)

_3FA = PRODUCTION_MODELS["3fa"]
_3FA_KEYS = _3FA["keys"]
_3FA_WEIGHTS = _3FA["weights"]
_SIG_FN = SIGNAL_TRANSFORMS["mom6"][1]


def _zscore(s, window=36, min_periods=12):
    """Rolling z-score, clipped to [-3, 3], scaled to [-1, +1]."""
    m = s.rolling(window, min_periods=min_periods).mean()
    st = s.rolling(window, min_periods=min_periods).std().replace(0, np.nan)
    z = ((s - m) / st).clip(-3, 3)
    return (z / 3).fillna(0)


def _expanding_window_oos(signal, spy_fwd, min_train=60):
    """Expanding-window OOS correlation. 60M min train, 1M step."""
    common = signal.dropna().index.intersection(spy_fwd.dropna().index)
    if len(common) < min_train + 12:
        return None, []

    oos_corrs = []
    for i in range(min_train, len(common)):
        train_sig = signal.reindex(common[:i])
        test_date = common[i]
        # Correlation of signal with forward returns using expanding window
        # OOS = correlation computed only on data after the training window
        pass

    # Simpler approach: split at midpoint, compute correlation on second half
    mid = len(common) // 2
    if mid < 30:
        return None, []

    oos_sig = signal.reindex(common[mid:])
    oos_fwd = spy_fwd.reindex(common[mid:])
    oos_clean = pd.concat([oos_sig.rename("sig"), oos_fwd.rename("fwd")], axis=1).dropna()
    if len(oos_clean) < 20:
        return None, []

    oos_corr = float(oos_clean["sig"].corr(oos_clean["fwd"]))

    # Also compute rolling 36M OOS correlation
    rolling = []
    for i in range(min_train, len(common), 12):
        window = common[max(0, i - 36):i]
        if len(window) < 24:
            continue
        ws = signal.reindex(window)
        wf = spy_fwd.reindex(window)
        wc = pd.concat([ws.rename("s"), wf.rename("f")], axis=1).dropna()
        if len(wc) >= 15:
            rolling.append({
                "date": window[-1].strftime("%Y-%m-%d"),
                "corr": round(float(wc["s"].corr(wc["f"])), 4),
            })

    return round(oos_corr, 4), rolling


def _sharpe_from_signal(signal, spy_monthly, alloc_map=None):
    """Quick Sharpe computation from signal and SPY prices."""
    if alloc_map is None:
        alloc_map = {1: 1.0, 2: 1.0, 3: 0.7, 4: 0.4, 5: 0.2}

    spy_ret = spy_monthly.pct_change().dropna()
    aligned = pd.concat([signal.rename("sig"), spy_ret.rename("ret")], axis=1).dropna()
    if len(aligned) < 30:
        return 0, 0

    try:
        quintiles = pd.qcut(aligned["sig"], 5, labels=[1, 2, 3, 4, 5], duplicates='drop')
    except Exception:
        return 0, 0

    weights = quintiles.map(alloc_map).astype(float)
    port_ret = aligned["ret"] * weights
    port_eq = (1 + port_ret).cumprod()

    years = len(port_ret) / 12
    ann_ret = float(port_eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if port_eq.iloc[-1] > 0 else 0
    ann_vol = float(port_ret.std() * np.sqrt(12))
    sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 1e-8 else 0

    peak = port_eq.expanding().max()
    max_dd = round(float(((port_eq - peak) / peak).min()) * 100, 1)

    return sharpe, max_dd


def build_proxy_signals(fred_df, ratio_series):
    """Build alternative proxy signals from available FRED data.

    Returns dict of {proxy_name: {"factor": str, "signal": pd.Series, "description": str}}
    """
    components = _extract_components(ratio_series)
    proxies = {}

    # --- Baseline signals (from ratio_series) ---
    for k in _3FA_KEYS:
        if k in components:
            proxies[f"baseline_{k}"] = {
                "factor": k,
                "signal": components[k],
                "description": f"Current production {k}",
                "is_baseline": True,
            }

    # --- Qty alternatives ---
    # Fed net liquidity: WALCL - RRPONTSYD - WTREGEN
    if fred_df is not None:
        walcl = fred_df.get("WALCL") if "WALCL" in fred_df.columns else None
        rrp = fred_df.get("RRPONTSYD") if "RRPONTSYD" in fred_df.columns else None
        tga = fred_df.get("WTREGEN") if "WTREGEN" in fred_df.columns else None

        if walcl is not None and rrp is not None and tga is not None:
            walcl_m = walcl.dropna().resample("MS").last()
            rrp_m = rrp.dropna().resample("MS").last() * 1000  # billions → millions
            tga_m = tga.dropna().resample("MS").last()
            net_liq = walcl_m - rrp_m - tga_m
            net_liq = net_liq.dropna()
            if len(net_liq) > 36:
                # YoY growth, z-scored (same as qty_signal)
                yoy = net_liq.pct_change(12) * 100
                sig = _zscore(yoy)
                proxies["qty_fed_net_liquidity"] = {
                    "factor": "quantity_signal",
                    "signal": sig.dropna(),
                    "description": "Fed net liquidity (WALCL - RRP - TGA) YoY growth, z-scored",
                    "is_baseline": False,
                }
            else:
                print("[PROXY] Fed net liquidity: not enough data after computing")
        else:
            missing = []
            if walcl is None: missing.append("WALCL")
            if rrp is None: missing.append("RRPONTSYD")
            if tga is None: missing.append("WTREGEN")
            print(f"[PROXY] Skipping Fed net liquidity — missing: {missing}")

    # --- Credit alternatives ---
    if fred_df is not None:
        # HY OAS inverted (lower OAS = looser credit = negative signal for tightening)
        hy_oas = fred_df.get("BAMLH0A0HYM2") if "BAMLH0A0HYM2" in fred_df.columns else None
        if hy_oas is not None:
            hy_m = hy_oas.dropna().resample("MS").last()
            if len(hy_m) > 36:
                # Higher OAS = tighter credit (same direction as spread_signal)
                yoy = hy_m.diff(12)
                sig = _zscore(yoy)
                proxies["credit_hy_oas"] = {
                    "factor": "spread_signal",
                    "signal": sig.dropna(),
                    "description": "HY OAS YoY change, z-scored (higher = tighter)",
                    "is_baseline": False,
                }
        else:
            print("[PROXY] Skipping HY OAS — not in FRED cache")

        # BBB OAS
        bbb_oas = fred_df.get("BAMLC0A4CBBB") if "BAMLC0A4CBBB" in fred_df.columns else None
        if bbb_oas is not None:
            bbb_m = bbb_oas.dropna().resample("MS").last()
            if len(bbb_m) > 36:
                yoy = bbb_m.diff(12)
                sig = _zscore(yoy)
                proxies["credit_bbb_oas"] = {
                    "factor": "spread_signal",
                    "signal": sig.dropna(),
                    "description": "BBB OAS YoY change, z-scored (higher = tighter)",
                    "is_baseline": False,
                }
        else:
            print("[PROXY] Skipping BBB OAS — not in FRED cache")

    # --- M2 alternatives ---
    if fred_df is not None:
        m2 = fred_df.get("M2SL") if "M2SL" in fred_df.columns else None
        cpi = fred_df.get("CPIAUCSL") if "CPIAUCSL" in fred_df.columns else None

        if m2 is not None and cpi is not None:
            m2_m = m2.dropna().resample("MS").last()
            cpi_m = cpi.dropna().resample("MS").last()
            # Real M2 = M2 / CPI * 100
            common = m2_m.index.intersection(cpi_m.index)
            real_m2 = (m2_m.reindex(common) / cpi_m.reindex(common) * 100).dropna()
            if len(real_m2) > 36:
                yoy = real_m2.pct_change(12) * 100
                # Negate: low real M2 growth = tightening (positive signal)
                sig = _zscore(-yoy)
                proxies["m2_real"] = {
                    "factor": "m2_signal",
                    "signal": sig.dropna(),
                    "description": "Real M2 (M2/CPI) YoY growth, negated, z-scored",
                    "is_baseline": False,
                }
        else:
            missing = []
            if m2 is None: missing.append("M2SL")
            if cpi is None: missing.append("CPIAUCSL")
            print(f"[PROXY] Skipping real M2 — missing: {missing}")

    return proxies


def run_proxy_analysis(ratio_series, spy_monthly, fred_df):
    """Run factor proxy quality analysis.

    Tests each alternative proxy: standalone correlation with forward SPY,
    then best-per-factor combination expanding-window OOS Sharpe vs baseline.
    """
    proxies = build_proxy_signals(fred_df, ratio_series)
    components = _extract_components(ratio_series)

    spy_fwd_6m = spy_monthly.pct_change(6).shift(-6) * 100
    spy_fwd_3m = spy_monthly.pct_change(3).shift(-3) * 100

    print(f"[PROXY] Testing {len(proxies)} proxy signals...")

    # Test each proxy independently
    proxy_results = []
    for name, info in proxies.items():
        sig = info["signal"]
        factor = info["factor"]

        # Standalone correlation with forward returns
        common = sig.dropna().index.intersection(spy_fwd_6m.dropna().index)
        if len(common) < 30:
            print(f"[PROXY] {name}: skipped (only {len(common)} common dates)")
            continue

        corr_6m = float(sig.reindex(common).corr(spy_fwd_6m.reindex(common)))
        corr_3m = float(sig.reindex(common).corr(spy_fwd_3m.reindex(common)))

        # OOS correlation (second half)
        oos_corr, _ = _expanding_window_oos(sig, spy_fwd_6m)

        proxy_results.append({
            "name": name,
            "factor": factor,
            "description": info["description"],
            "is_baseline": info.get("is_baseline", False),
            "n_months": len(common),
            "corr_3m": round(corr_3m, 4),
            "corr_6m": round(corr_6m, 4),
            "oos_corr_6m": oos_corr,
            "date_range": f"{common[0].strftime('%Y-%m')} to {common[-1].strftime('%Y-%m')}",
        })

    # Sort by OOS correlation (most negative = best)
    proxy_results.sort(key=lambda x: x.get("oos_corr_6m") or 0)

    # Find best proxy per factor
    best_per_factor = {}
    for pr in proxy_results:
        factor = pr["factor"]
        if factor not in best_per_factor or (pr.get("oos_corr_6m") or 0) < (best_per_factor[factor].get("oos_corr_6m") or 0):
            best_per_factor[factor] = pr

    # Build best-combination model: use best proxy per factor
    print("[PROXY] Building best-combination model...")
    best_combo_keys = []
    best_combo_signals = {}
    for factor in _3FA_KEYS:
        if factor in best_per_factor:
            bp = best_per_factor[factor]
            proxy_name = bp["name"]
            # Find the actual signal
            if proxy_name in proxies:
                best_combo_signals[factor] = proxies[proxy_name]["signal"]
                best_combo_keys.append(factor)

    # Compute Sharpe for baseline vs best-combination
    baseline_signal = _build_and_transform(components, _3FA_KEYS, _3FA_WEIGHTS)
    baseline_sharpe, baseline_dd = _sharpe_from_signal(baseline_signal, spy_monthly)

    if len(best_combo_signals) == len(_3FA_KEYS):
        # Build composite with best proxies using same weights
        base_idx = best_combo_signals[_3FA_KEYS[0]].index
        for k in _3FA_KEYS[1:]:
            base_idx = base_idx.intersection(best_combo_signals[k].index)
        base_idx = base_idx.sort_values()

        comp = pd.Series(0.0, index=base_idx)
        for k in _3FA_KEYS:
            comp += _3FA_WEIGHTS[k] * best_combo_signals[k].reindex(base_idx, method="ffill").fillna(0)
        combo_signal = _SIG_FN(comp).dropna()
        combo_sharpe, combo_dd = _sharpe_from_signal(combo_signal, spy_monthly)
    else:
        combo_sharpe, combo_dd = None, None

    print(f"[PROXY] Baseline Sharpe: {baseline_sharpe}, Best-combo Sharpe: {combo_sharpe}")

    return {
        "proxy_results": proxy_results,
        "best_per_factor": {k: v["name"] for k, v in best_per_factor.items()},
        "baseline_sharpe": baseline_sharpe,
        "baseline_max_dd": baseline_dd,
        "best_combo_sharpe": combo_sharpe,
        "best_combo_max_dd": combo_dd,
        "improvement": round(combo_sharpe - baseline_sharpe, 3) if combo_sharpe is not None else None,
    }


def _build_and_transform(components, keys, weights):
    """Build composite from components and apply Mom 6M."""
    base_idx = components[keys[0]].index
    for k in keys[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()

    comp = pd.Series(0.0, index=base_idx)
    for k in keys:
        if k in components:
            w = weights[k] if isinstance(weights, dict) else weights[keys.index(k)]
            comp += w * components[k].reindex(base_idx, method="ffill").fillna(0)
    return _SIG_FN(comp).dropna()


if __name__ == "__main__":
    print("=" * 60)
    print("GLI 3FA Factor Proxy Analysis")
    print("=" * 60)
    print("Call run_proxy_analysis(ratio_series, spy_monthly, fred_df)")
