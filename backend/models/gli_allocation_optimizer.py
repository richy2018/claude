"""GLI Allocation Optimizer — Equity/Cash Split Per Quintile.

Phase 1: Brute-force grid search over quintile allocations with vol-scaling.
Phase 2: Continuous mapping functions (linear, sigmoid, piecewise, etc.)
"""

import numpy as np
import pandas as pd
from itertools import product
from scipy.optimize import minimize

from .backtest_engine import (
    _extract_components, SIGNAL_TRANSFORMS, PRODUCTION_MODELS,
)

_3FA = PRODUCTION_MODELS["3fa_eq"]
_3FA_KEYS = _3FA["keys"]
_3FA_WEIGHTS = _3FA["weights"]
_SIG_FN = SIGNAL_TRANSFORMS["mom6"][1]


def _build_signal(ratio_series):
    """Build production 3FA_EQ Mom6M signal."""
    components = _extract_components(ratio_series)
    missing = [k for k in _3FA_KEYS if k not in components]
    if missing:
        return None, f"Missing: {missing}"
    base_idx = components[_3FA_KEYS[0]].index
    for k in _3FA_KEYS[1:]:
        if k in components:
            base_idx = base_idx.intersection(components[k].index)
    base_idx = base_idx.sort_values()
    comp = pd.Series(0.0, index=base_idx)
    for k in _3FA_KEYS:
        if k in components:
            comp += _3FA_WEIGHTS[k] * components[k].reindex(base_idx, method="ffill").fillna(0)
    return _SIG_FN(comp).dropna(), None


def _backtest(signal, spy_ret, alloc_map, vix_data=None, target_vol=0.10):
    """Run backtest with optional vol-scaling. Returns metrics dict."""
    aligned = pd.concat([signal.rename("sig"), spy_ret.rename("ret")], axis=1).dropna()
    if len(aligned) < 30:
        return None
    try:
        q = pd.qcut(aligned["sig"], 5, labels=[1, 2, 3, 4, 5], duplicates='drop')
    except Exception:
        return None

    base_w = q.map(alloc_map).astype(float)

    # Vol-scaling
    if vix_data is not None and len(vix_data) > 12:
        vix_m = vix_data.resample("MS").last().dropna() / 100
        vix_al = vix_m.reindex(aligned.index, method="ffill").clip(lower=0.05)
        vs = (target_vol / vix_al).clip(upper=2.0)
        weights = (base_w * vs).clip(-1.0, 1.0)
    else:
        weights = base_w

    port_ret = aligned["ret"] * weights
    eq = (1 + port_ret).cumprod()
    years = len(port_ret) / 12
    ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
    ann_vol = float(port_ret.std() * np.sqrt(12))
    sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 1e-8 else 0
    peak = eq.expanding().max()
    max_dd = round(float(((eq - peak) / peak).min()) * 100, 1)
    calmar = round(ann_ret / abs(max_dd / 100), 2) if abs(max_dd) > 0.1 else 0
    total = round(float(eq.iloc[-1] - 1) * 100, 1)
    turnover = round(float(weights.diff().abs().mean()), 4)

    return {
        "sharpe": sharpe, "max_dd": max_dd, "calmar": calmar,
        "total_return": total, "ann_return": round(ann_ret * 100, 2),
        "ann_vol": round(ann_vol * 100, 2), "turnover": turnover,
    }


def run_grid_search(ratio_series, spy_monthly, vix_data=None):
    """Phase 1: Brute-force grid search over quintile allocations."""
    signal, err = _build_signal(ratio_series)
    if err:
        return {"error": err}

    spy_ret = spy_monthly.pct_change().dropna()

    # Grid values per quintile
    q1_vals = [1.0, 0.9, 0.8, 0.7, 0.6]
    q2_vals = [1.0, 0.9, 0.8, 0.7, 0.6]
    q3_vals = [1.0, 0.8, 0.6, 0.4, 0.2]
    q4_vals = [0.8, 0.6, 0.4, 0.2, 0.0]
    q5_vals = [0.5, 0.3, 0.2, 0.1, 0.0, -0.2, -0.5]

    print(f"[ALLOC GRID] Testing grid with monotonicity constraint...")
    results = []
    tested = 0

    for q1, q2, q3, q4, q5 in product(q1_vals, q2_vals, q3_vals, q4_vals, q5_vals):
        # Monotonicity constraint
        if not (q1 >= q2 >= q3 >= q4 >= q5):
            continue
        tested += 1
        alloc = {1: q1, 2: q2, 3: q3, 4: q4, 5: q5}
        m = _backtest(signal, spy_ret, alloc, vix_data)
        if m is None:
            continue
        m["alloc"] = alloc
        m["label"] = f"{int(q1*100)}/{int(q2*100)}/{int(q3*100)}/{int(q4*100)}/{int(q5*100)}"
        results.append(m)

    print(f"[ALLOC GRID] Tested {tested} valid combinations, {len(results)} produced results")

    if not results:
        return {"error": "No valid results"}

    # Top 10 by Sharpe
    by_sharpe = sorted(results, key=lambda x: x["sharpe"], reverse=True)[:10]
    # Top 10 by Calmar
    by_calmar = sorted(results, key=lambda x: x["calmar"], reverse=True)[:10]
    # Top 10 by total return
    by_return = sorted(results, key=lambda x: x["total_return"], reverse=True)[:10]

    # Current production rule for comparison
    current = _backtest(signal, spy_ret, {1: 1.0, 2: 0.8, 3: 0.8, 4: 0.6, 5: 0.2}, vix_data)
    if current:
        current["label"] = "Production (100/80/80/60/20)"
        current["alloc"] = {1: 1.0, 2: 0.8, 3: 0.8, 4: 0.6, 5: 0.2}

    best = by_sharpe[0]
    print(f"[ALLOC GRID] Best Sharpe: {best['sharpe']} → {best['label']}")
    print(f"[ALLOC GRID] Best Calmar: {by_calmar[0]['calmar']} → {by_calmar[0]['label']}")
    if current:
        print(f"[ALLOC GRID] Current: Sharpe={current['sharpe']}, Calmar={current['calmar']}")

    # Monte Carlo: shuffle quintile assignments, apply best alloc, compare Sharpe
    best_alloc = best["alloc"]
    aligned = pd.concat([signal.rename("sig"), spy_ret.rename("ret")], axis=1).dropna()
    try:
        quintiles = pd.qcut(aligned["sig"], 5, labels=[1, 2, 3, 4, 5], duplicates='drop')
    except Exception:
        quintiles = None

    mc_result = None
    if quintiles is not None:
        real_sharpe = best["sharpe"]
        q_vals = quintiles.values.copy()
        ret_vals = aligned["ret"].values

        vix_m = None
        if vix_data is not None and len(vix_data) > 12:
            vix_m = vix_data.resample("MS").last().dropna() / 100
            vix_al = vix_m.reindex(aligned.index, method="ffill").clip(lower=0.05).values
        else:
            vix_al = None

        print(f"[ALLOC MC] Running 5000 permutations...")
        null_sharpes = np.empty(5000)
        for i in range(5000):
            shuf_q = np.random.permutation(q_vals)
            w = np.array([best_alloc[int(q)] for q in shuf_q])
            if vix_al is not None:
                vs = np.clip(0.10 / vix_al, 0, 2.0)
                w = np.clip(w * vs, -1, 1)
            pr = ret_vals * w
            eq_c = np.cumprod(1 + pr)
            yrs = len(pr) / 12
            ar = float(eq_c[-1] ** (1 / max(yrs, 0.5)) - 1) if eq_c[-1] > 0 else 0
            av = float(np.std(pr) * np.sqrt(12))
            null_sharpes[i] = round(ar / av, 3) if av > 1e-8 else 0

        p_value = float(np.mean(null_sharpes >= real_sharpe))
        print(f"[ALLOC MC] Real={real_sharpe:.3f}, null_mean={np.mean(null_sharpes):.3f}, p={p_value:.4f}")
        mc_result = {
            "real_sharpe": real_sharpe,
            "p_value": round(p_value, 4),
            "null_mean": round(float(np.mean(null_sharpes)), 3),
        }

    return {
        "n_tested": tested,
        "n_valid": len(results),
        "top_by_sharpe": by_sharpe,
        "top_by_calmar": by_calmar,
        "top_by_return": by_return,
        "best_sharpe": best,
        "current_production": current,
        "monte_carlo": mc_result,
    }


# ─── Phase 2: Continuous Mapping Functions ──────────────────────────────────

def _backtest_continuous(signal, spy_ret, map_fn, vix_data=None, target_vol=0.10):
    """Backtest using a continuous signal→allocation mapping function."""
    aligned = pd.concat([signal.rename("sig"), spy_ret.rename("ret")], axis=1).dropna()
    if len(aligned) < 30:
        return None

    # Apply mapping function to get base weights
    base_w = aligned["sig"].apply(map_fn).clip(-1, 1)

    if vix_data is not None and len(vix_data) > 12:
        vix_m = vix_data.resample("MS").last().dropna() / 100
        vix_al = vix_m.reindex(aligned.index, method="ffill").clip(lower=0.05)
        vs = (target_vol / vix_al).clip(upper=2.0)
        weights = (base_w * vs).clip(-1, 1)
    else:
        weights = base_w

    port_ret = aligned["ret"] * weights
    eq = (1 + port_ret).cumprod()
    years = len(port_ret) / 12
    ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
    ann_vol = float(port_ret.std() * np.sqrt(12))
    sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 1e-8 else 0
    peak = eq.expanding().max()
    max_dd = round(float(((eq - peak) / peak).min()) * 100, 1)
    calmar = round(ann_ret / abs(max_dd / 100), 2) if abs(max_dd) > 0.1 else 0
    total = round(float(eq.iloc[-1] - 1) * 100, 1)
    turnover = round(float(weights.diff().abs().mean()), 4)

    return {
        "sharpe": sharpe, "max_dd": max_dd, "calmar": calmar,
        "total_return": total, "ann_return": round(ann_ret * 100, 2),
        "turnover": turnover,
    }


def run_continuous_functions(ratio_series, spy_monthly, vix_data=None):
    """Phase 2: Test continuous signal→allocation mapping functions."""
    signal, err = _build_signal(ratio_series)
    if err:
        return {"error": err}

    spy_ret = spy_monthly.pct_change().dropna()
    sig_std = float(signal.std())
    sig_mean = float(signal.mean())

    print(f"[ALLOC CONT] Signal stats: mean={sig_mean:.4f}, std={sig_std:.4f}")

    results = []

    # 1. Linear: w = clip(a + b * signal, 0, 1)
    def _opt_linear(params):
        a, b = params
        fn = lambda s: max(0, min(1, a + b * s))
        m = _backtest_continuous(signal, spy_ret, fn, vix_data)
        return -(m["sharpe"] if m else 0)

    for a0, b0 in [(0.5, -5), (0.7, -3), (0.6, -10)]:
        try:
            res = minimize(_opt_linear, [a0, b0], method='Nelder-Mead', options={'maxiter': 300})
            a, b = res.x
            fn = lambda s, a=a, b=b: max(0, min(1, a + b * s))
            m = _backtest_continuous(signal, spy_ret, fn, vix_data)
            if m:
                m["name"] = f"Linear (a={a:.2f}, b={b:.2f})"
                m["type"] = "linear"
                m["params"] = {"a": round(a, 3), "b": round(b, 3)}
                m["mapping"] = [{"signal": round(float(s), 3), "weight": round(fn(s), 3)}
                                for s in np.linspace(signal.min(), signal.max(), 20)]
                results.append(m)
        except Exception:
            pass

    # 2. Sigmoid: w = 1 / (1 + exp(-k * (signal - mid)))
    def _opt_sigmoid(params):
        k, mid = params
        fn = lambda s: 1.0 / (1.0 + np.exp(-k * (s - mid)))
        m = _backtest_continuous(signal, spy_ret, fn, vix_data)
        return -(m["sharpe"] if m else 0)

    for k0, m0 in [(-10, 0), (-5, sig_mean), (-20, 0)]:
        try:
            res = minimize(_opt_sigmoid, [k0, m0], method='Nelder-Mead', options={'maxiter': 300})
            k, mid = res.x
            fn = lambda s, k=k, mid=mid: 1.0 / (1.0 + np.exp(-k * (s - mid)))
            m = _backtest_continuous(signal, spy_ret, fn, vix_data)
            if m:
                m["name"] = f"Sigmoid (k={k:.1f}, mid={mid:.3f})"
                m["type"] = "sigmoid"
                m["params"] = {"k": round(k, 2), "midpoint": round(mid, 4)}
                m["mapping"] = [{"signal": round(float(s), 3), "weight": round(fn(s), 3)}
                                for s in np.linspace(signal.min(), signal.max(), 20)]
                results.append(m)
        except Exception:
            pass

    # 3. Piecewise linear: 100% above hi, 0% below lo, linear between
    def _opt_piecewise(params):
        lo, hi = sorted(params)
        def fn(s):
            if s >= hi: return 1.0
            if s <= lo: return 0.0
            return (s - lo) / (hi - lo)
        m = _backtest_continuous(signal, spy_ret, fn, vix_data)
        return -(m["sharpe"] if m else 0)

    for lo0, hi0 in [(-0.05, 0.02), (-0.03, 0.01), (-0.08, 0.03)]:
        try:
            res = minimize(_opt_piecewise, [lo0, hi0], method='Nelder-Mead', options={'maxiter': 300})
            lo, hi = sorted(res.x)
            def fn(s, lo=lo, hi=hi):
                if s >= hi: return 1.0
                if s <= lo: return 0.0
                return (s - lo) / (hi - lo)
            m = _backtest_continuous(signal, spy_ret, fn, vix_data)
            if m:
                m["name"] = f"Piecewise (lo={lo:.3f}, hi={hi:.3f})"
                m["type"] = "piecewise"
                m["params"] = {"lo": round(lo, 4), "hi": round(hi, 4)}
                m["mapping"] = [{"signal": round(float(s), 3), "weight": round(fn(s), 3)}
                                for s in np.linspace(signal.min(), signal.max(), 20)]
                results.append(m)
        except Exception:
            pass

    # Deduplicate: keep best per type
    best_per_type = {}
    for r in results:
        t = r["type"]
        if t not in best_per_type or r["sharpe"] > best_per_type[t]["sharpe"]:
            best_per_type[t] = r

    final = sorted(best_per_type.values(), key=lambda x: x["sharpe"], reverse=True)
    if final:
        final[0]["is_best"] = True

    print(f"[ALLOC CONT] Tested {len(results)} functions, best: {final[0]['name']} Sharpe={final[0]['sharpe']}" if final else "[ALLOC CONT] No valid results")

    return {
        "functions": final,
        "best": final[0] if final else None,
    }


def run_allocation_study(ratio_series, spy_monthly, vix_data=None):
    """Run full allocation optimization study (Phase 1 + 2)."""
    print("[ALLOC] === Phase 1: Grid Search ===")
    grid = run_grid_search(ratio_series, spy_monthly, vix_data)

    print("\n[ALLOC] === Phase 2: Continuous Functions ===")
    continuous = run_continuous_functions(ratio_series, spy_monthly, vix_data)

    # Summary comparison
    summary = []
    if grid.get("current_production"):
        cp = grid["current_production"]
        summary.append({"name": "Production (100/80/80/60/20)", **{k: cp[k] for k in ["sharpe", "max_dd", "calmar", "total_return", "turnover"] if k in cp}})
    if grid.get("best_sharpe"):
        bs = grid["best_sharpe"]
        summary.append({"name": f"Grid Best ({bs['label']})", **{k: bs[k] for k in ["sharpe", "max_dd", "calmar", "total_return", "turnover"] if k in bs}})
    if continuous.get("best"):
        cb = continuous["best"]
        summary.append({"name": cb["name"], **{k: cb[k] for k in ["sharpe", "max_dd", "calmar", "total_return", "turnover"] if k in cb}})

    return {
        "grid_search": grid,
        "continuous": continuous,
        "summary": summary,
    }


if __name__ == "__main__":
    print("=" * 60)
    print("GLI Allocation Optimizer")
    print("=" * 60)
    print("Call run_allocation_study(ratio_series, spy_monthly, vix_data)")
