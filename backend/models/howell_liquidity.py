"""Howell Liquidity — Refinancing Stress Index.

Phase 1: BIS Advanced Economy total debt numerator (C+G sectors).
Stress Index: Debt_z - GLI_z (debt pressure minus liquidity support).
"""

import numpy as np
import pandas as pd


ADVANCED_ECONOMY_CODES = {
    "US": "United States", "JP": "Japan", "GB": "United Kingdom",
    "DE": "Germany", "FR": "France", "IT": "Italy", "ES": "Spain",
    "CA": "Canada", "AU": "Australia", "KR": "Korea",
    "NL": "Netherlands", "CH": "Switzerland", "SE": "Sweden",
}


def _fetch_bis_country(country_code, borrowing_sector="C"):
    """Fetch BIS total credit for one country."""
    import requests
    from io import StringIO

    headers = {"User-Agent": "Mozilla/5.0"}
    base_url = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_TC/2.0"
    key = f"Q.{country_code}.{borrowing_sector}.A.M.USD.A"
    url = f"{base_url}/{key}?format=csv"

    try:
        resp = requests.get(url, headers=headers, timeout=60)
        if resp.status_code == 200 and len(resp.text) > 100:
            df = pd.read_csv(StringIO(resp.text))
            time_col = val_col = None
            for c in df.columns:
                cl = c.lower()
                if time_col is None and ("time_period" in cl or "period" in cl):
                    time_col = c
                if val_col is None and ("obs_value" in cl or cl == "value"):
                    val_col = c
            if time_col and val_col:
                df["date"] = pd.to_datetime(df[time_col])
                df["value"] = pd.to_numeric(df[val_col], errors="coerce")
                return df.set_index("date")["value"].dropna().sort_index()
    except Exception as e:
        print(f"[HOWELL BIS] {country_code} sector={borrowing_sector}: {e}")
    return pd.Series(dtype=float)


def build_debt_numerator():
    """Phase 1: Build Advanced Economy total debt (C+G sectors) from BIS."""
    print("[HOWELL] Fetching BIS total credit (sector C + G)...")

    country_data = {}
    for code, name in ADVANCED_ECONOMY_CODES.items():
        series_c = _fetch_bis_country(code, "C")
        series_g = _fetch_bis_country(code, "G")
        if len(series_c) > 10:
            total = series_c.copy()
            if len(series_g) > 10:
                common = series_c.index.intersection(series_g.index)
                ratio = float((series_c.reindex(common) + series_g.reindex(common)).iloc[-1] / series_c.reindex(common).iloc[-1])
                if ratio > 1.2:  # Gov is additive
                    total = series_c.reindex(common) + series_g.reindex(common)
            country_data[name] = total
            print(f"[HOWELL]   {code}: ${total.iloc[-1]:.0f}B")

    if len(country_data) < 5:
        return None, "Not enough countries"

    combined = pd.DataFrame(country_data)
    combined.index = pd.to_datetime(combined.index)
    total_debt = combined.sum(axis=1).dropna().sort_index() / 1000  # B → T
    print(f"[HOWELL] AE debt: ${total_debt.iloc[-1]:.1f}T ({len(country_data)} countries)")
    return total_debt, None


def _normalize_qtr(s):
    """Normalize to quarter-end dates."""
    if len(s) == 0:
        return s
    s = s.copy()
    s.index = pd.to_datetime(s.index).to_period('Q').to_timestamp('Q')
    s = s[~s.index.duplicated(keep='last')]
    return s.sort_index()


def compute_refinancing_stress(debt_series, gli_signal_chart):
    """Compute Refinancing Stress Index = Debt_z - GLI_z.

    Args:
        debt_series: Quarterly AE total debt in $T
        gli_signal_chart: List of {date, comp_z} from production signal cache
    """
    # Extract GLI z-score from production cache chart
    gli_z = pd.Series(
        {pd.Timestamp(p["date"]): p.get("comp_z") for p in gli_signal_chart if p.get("comp_z") is not None},
        dtype=float).dropna().sort_index()

    if len(gli_z) < 20:
        return {"error": f"Only {len(gli_z)} GLI data points"}

    # Normalize to quarterly
    debt_q = _normalize_qtr(debt_series)
    gli_q = _normalize_qtr(gli_z.resample("QE").last().dropna())

    # Debt z-score: YoY growth rate, then rolling z-score
    debt_yoy = debt_q.pct_change(4)  # 4 quarters = YoY
    debt_mean = debt_yoy.rolling(20, min_periods=8).mean()
    debt_std = debt_yoy.rolling(20, min_periods=8).std().replace(0, np.nan)
    debt_z = ((debt_yoy - debt_mean) / debt_std).clip(-3, 3)

    # Align
    common = debt_z.dropna().index.intersection(gli_q.dropna().index)
    if len(common) < 10:
        return {"error": f"Only {len(common)} common dates"}

    dz = debt_z.reindex(common)
    gz = gli_q.reindex(common)

    # Stress = debt pressure - liquidity support
    stress = dz - gz
    stress = stress.dropna()

    # Current reading
    current = float(stress.iloc[-1])
    pct = float((stress <= current).mean()) * 100

    if pct < 25: regime = "LOW STRESS"
    elif pct < 50: regime = "NORMAL"
    elif pct < 75: regime = "ELEVATED"
    elif pct < 90: regime = "HIGH STRESS"
    else: regime = "CRISIS RISK"

    # Validation checks
    def _check_peak(series, start, end):
        window = series[start:end]
        rest = series.drop(window.index, errors='ignore')
        return len(window) > 0 and len(rest) > 0 and float(window.max()) > float(rest.quantile(0.75))

    def _check_trough(series, start, end):
        window = series[start:end]
        rest = series.drop(window.index, errors='ignore')
        return len(window) > 0 and len(rest) > 0 and float(window.min()) < float(rest.quantile(0.25))

    validation = {
        "peaks_2008": _check_peak(stress, "2007-06", "2009-06"),
        "peaks_2011": _check_peak(stress, "2010-06", "2012-06"),
        "trough_2021": _check_trough(stress, "2020-01", "2022-01"),
        "rising_now": len(stress) > 8 and float(stress.iloc[-1]) > float(stress.iloc[-8]),
        "above_median": current > float(stress.median()),
    }
    n_pass = sum(1 for v in validation.values() if v)

    # Chart data
    chart = []
    for d in stress.index:
        chart.append({
            "date": d.strftime("%Y-%m-%d"),
            "stress": round(float(stress[d]), 3),
            "debt_z": round(float(dz.get(d, 0)), 3),
            "gli_z": round(float(gz.get(d, 0)), 3),
        })

    # Interpretation
    dz_curr = float(dz.iloc[-1])
    gz_curr = float(gz.iloc[-1])
    if dz_curr > 0.5 and gz_curr < -0.5:
        interp = "Debt growth above trend + liquidity tightening = elevated refinancing stress"
    elif dz_curr > 0 and gz_curr < 0:
        interp = "Moderately rising debt + mildly tight liquidity = building stress"
    elif dz_curr < 0 and gz_curr > 0:
        interp = "Slowing debt growth + loose liquidity = low stress environment"
    else:
        interp = f"Debt-z={dz_curr:.2f}, GLI-z={gz_curr:.2f} — mixed signals"

    print(f"[HOWELL STRESS] Current: {current:.2f} ({pct:.0f}th pct, {regime})")
    print(f"[HOWELL STRESS] Debt-z={dz_curr:.2f}, GLI-z={gz_curr:.2f}")
    print(f"[HOWELL STRESS] Validation: {n_pass}/5 checks pass")

    return {
        "stress_index": {
            "current": round(current, 3),
            "percentile": round(pct, 0),
            "regime": regime,
            "series": chart,
        },
        "components": {
            "debt_z_current": round(dz_curr, 3),
            "gli_z_current": round(gz_curr, 3),
            "interpretation": interp,
        },
        "validation": validation,
        "n_validation_pass": n_pass,
        "n_quarters": len(chart),
    }


def run_spy_window_analysis(stress_result, spy_monthly):
    """Test SPY forward return z-score at multiple rolling windows vs stress index.

    For each window: correlation with stress index, bootstrap p-value,
    and comparison correlation with -GLI_z alone.
    """
    if not stress_result or "error" in stress_result:
        return {"error": "No stress data"}

    # Build stress and GLI series from the result
    chart = stress_result.get("stress_index", {}).get("series", [])
    if len(chart) < 20:
        return {"error": "Not enough stress data"}

    stress = pd.Series(
        {pd.Timestamp(p["date"]): p["stress"] for p in chart}, dtype=float).dropna().sort_index()
    neg_gli = pd.Series(
        {pd.Timestamp(p["date"]): -p["gli_z"] for p in chart if p.get("gli_z") is not None},
        dtype=float).dropna().sort_index()

    # SPY 6M forward return (quarterly)
    spy_ret = spy_monthly.pct_change(6).shift(-6) * 100
    spy_q = spy_ret.resample("QE").last().dropna()
    spy_q.index = pd.to_datetime(spy_q.index).to_period('Q').to_timestamp('Q')
    spy_q = spy_q[~spy_q.index.duplicated(keep='last')]

    # Align
    common = stress.index.intersection(spy_q.index)
    if len(common) < 20:
        return {"error": f"Only {len(common)} common dates with SPY"}

    stress_al = stress.reindex(common)
    neg_gli_al = neg_gli.reindex(common).fillna(0)
    spy_al = spy_q.reindex(common)

    windows = [
        ("36M", 36), ("60M", 60), ("72M", 72), ("120M", 120), ("Expanding", None),
    ]

    results = []
    for label, window in windows:
        # Z-score SPY forward return
        if window is not None:
            m = spy_al.rolling(window // 3, min_periods=max(8, window // 9)).mean()
            s = spy_al.rolling(window // 3, min_periods=max(8, window // 9)).std().replace(0, np.nan)
        else:
            m = spy_al.expanding(min_periods=8).mean()
            s = spy_al.expanding(min_periods=8).std().replace(0, np.nan)

        spy_z = ((spy_al - m) / s).clip(-3, 3)
        inv_spy_z = -spy_z  # Invert: negative fwd return = high stress

        # Correlation with stress index
        valid = inv_spy_z.dropna().index.intersection(stress_al.dropna().index)
        if len(valid) < 15:
            results.append({"window": label, "corr_stress": None, "p_value": None, "corr_gli": None})
            continue

        corr_stress = round(float(stress_al.reindex(valid).corr(inv_spy_z.reindex(valid))), 4)
        corr_gli = round(float(neg_gli_al.reindex(valid).corr(inv_spy_z.reindex(valid))), 4)

        # Bootstrap p-value (10,000 shuffles)
        stress_vals = stress_al.reindex(valid).values
        spy_vals = inv_spy_z.reindex(valid).values
        n_perms = 10000
        null_corrs = np.empty(n_perms)
        for i in range(n_perms):
            null_corrs[i] = np.corrcoef(np.random.permutation(stress_vals), spy_vals)[0, 1]
        p_value = round(float(np.mean(null_corrs >= corr_stress)), 4)

        results.append({
            "window": label,
            "corr_stress": corr_stress,
            "corr_gli": corr_gli,
            "p_value": p_value,
            "n_obs": len(valid),
        })
        print(f"[HOWELL WINDOW] {label}: stress corr={corr_stress}, GLI corr={corr_gli}, p={p_value}")

    # Find best window
    valid_results = [r for r in results if r.get("corr_stress") is not None]
    best = max(valid_results, key=lambda x: x["corr_stress"]) if valid_results else None

    return {
        "windows": results,
        "best_window": best["window"] if best else None,
        "best_corr": best["corr_stress"] if best else None,
        "confirms_65m_cycle": best is not None and best["window"] in ("60M", "72M"),
    }


def run_signal_backtest(stress_result, spy_monthly):
    """Directional backtest: signal above median → long SPY, below → cash.

    Tests both -GLI_z alone and Stress (Debt_z - GLI_z) at multiple horizons.
    Bootstrap 10,000 shuffles for p-values.
    """
    chart = stress_result.get("stress_index", {}).get("series", [])
    if len(chart) < 20:
        return {"error": "Not enough stress data"}

    stress = pd.Series(
        {pd.Timestamp(p["date"]): p["stress"] for p in chart}, dtype=float).dropna()
    neg_gli = pd.Series(
        {pd.Timestamp(p["date"]): -p["gli_z"] for p in chart if p.get("gli_z") is not None},
        dtype=float).dropna()

    # SPY monthly returns
    spy_ret = spy_monthly.pct_change().dropna()
    # Resample signals to monthly (ffill quarterly to monthly)
    stress_m = stress.resample("MS").ffill().dropna()
    gli_m = neg_gli.resample("MS").ffill().dropna()

    common = stress_m.index.intersection(gli_m.index).intersection(spy_ret.index)
    if len(common) < 60:
        return {"error": f"Only {len(common)} common monthly dates"}

    stress_m = stress_m.reindex(common)
    gli_m = gli_m.reindex(common)
    spy = spy_ret.reindex(common)

    horizons = [3, 6, 12, 18, 24]
    signals = {
        "-GLI_z": gli_m,
        "Stress (Debt_z - GLI_z)": stress_m,
    }

    def _backtest_signal(sig, ret, horizon):
        """Long when signal above expanding median, cash otherwise. Returns at given horizon."""
        fwd = ret.rolling(horizon).sum().shift(-horizon)  # Approx N-month fwd return
        aligned = pd.DataFrame({"sig": sig, "fwd": fwd}).dropna()
        if len(aligned) < 30:
            return None

        median = aligned["sig"].expanding(min_periods=20).median()
        is_long = aligned["sig"] > median
        strat_ret_monthly = ret.reindex(aligned.index) * is_long.astype(float)

        # Metrics
        eq = (1 + strat_ret_monthly).cumprod()
        years = len(strat_ret_monthly) / 12
        ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
        ann_vol = float(strat_ret_monthly.std() * np.sqrt(12))
        sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 1e-8 else 0
        peak = eq.expanding().max()
        max_dd = round(float(((eq - peak) / peak).min()) * 100, 1)
        hit = round(float((strat_ret_monthly[is_long] > 0).mean()) * 100, 1) if is_long.sum() > 0 else 0

        return sharpe, max_dd, hit, strat_ret_monthly

    def _bootstrap_p(sig, ret, horizon, real_sharpe, n_perms=10000):
        """Shuffle signal, recompute Sharpe, get p-value."""
        sig_vals = sig.values.copy()
        ret_vals = ret.values
        n = len(sig_vals)
        null_sharpes = np.empty(n_perms)
        for i in range(n_perms):
            shuf = np.random.permutation(sig_vals)
            median = pd.Series(shuf).expanding(min_periods=20).median().values
            is_long = shuf > median
            sr = ret_vals * is_long.astype(float)
            eq = np.cumprod(1 + sr)
            yrs = n / 12
            ar = float(eq[-1] ** (1 / max(yrs, 0.5)) - 1) if eq[-1] > 0 else 0
            av = float(np.std(sr) * np.sqrt(12))
            null_sharpes[i] = ar / av if av > 1e-8 else 0
        return round(float(np.mean(null_sharpes >= real_sharpe)), 4)

    results = []
    for sig_name, sig_series in signals.items():
        for h in horizons:
            bt = _backtest_signal(sig_series, spy, h)
            if bt is None:
                continue
            sharpe, max_dd, hit, _ = bt
            p = _bootstrap_p(sig_series, spy, h, sharpe)
            results.append({
                "signal": sig_name, "horizon": f"{h}M",
                "sharpe": sharpe, "max_dd": max_dd, "hit_rate": hit, "p_value": p,
            })
            print(f"[HOWELL BT] {sig_name} {h}M: Sharpe={sharpe}, DD={max_dd}%, Hit={hit}%, p={p}")

    return {"backtest": results, "n_months": len(common)}


def run_stress_comparison(stress_result, gli_signal_chart, spy_monthly):
    """Apples-to-apples: run stress index through GLI production pipeline.

    Test 1: Same mom6 transform + quintile allocation for both signals.
    Test 2: Divergence analysis — when do the signals disagree?
    All output goes to logs. No frontend.
    """
    from .backtest_engine import sortino_ratio

    chart = stress_result.get("stress_index", {}).get("series", [])
    if len(chart) < 20:
        return

    # Build monthly series
    # Stress: quarterly, interpolate to monthly via ffill
    stress_q = pd.Series(
        {pd.Timestamp(p["date"]): p["stress"] for p in chart}, dtype=float).dropna()
    stress_m = stress_q.resample("MS").ffill().dropna()

    # GLI: the chart contains comp_z (z-scored composite LEVEL).
    # Production pipeline applies mom6 to the RAW composite, not to comp_z.
    # comp_z IS the signal input — mom6 is applied INSIDE _run_pipeline.
    # BUT: comp_z is already z-scored, so diff(6) on a z-score != mom6 on raw.
    # For fair comparison, use comp_z directly as the signal (it's what the
    # production signal card displays) and DON'T apply mom6 again.
    # The production backtest (run_signal_validation) builds its own composite
    # from raw components, applies mom6, then uses that as the signal.
    # We can't replicate that here without importing production code.
    # Instead: use comp_z as-is (the z-scored level) for both signals.
    gli_z = pd.Series(
        {pd.Timestamp(p["date"]): p.get("comp_z") for p in gli_signal_chart if p.get("comp_z") is not None},
        dtype=float).dropna()

    spy_ret = spy_monthly.pct_change().dropna()

    # === Test 1: Production pipeline comparison ===
    print("\n" + "=" * 70)
    print("TEST 1: PRODUCTION PIPELINE COMPARISON")
    print("=" * 70)

    alloc = {1: 1.0, 2: 1.0, 3: 1.0, 4: 0.1, 5: 0.1}

    def _run_pipeline(signal, label, apply_mom6=False):
        if apply_mom6:
            sig = signal.diff(6).dropna()
            transform = "mom6 applied"
        else:
            sig = signal.dropna()
            transform = "level (no mom6)"

        common = sig.index.intersection(spy_ret.index)
        if len(common) < 60:
            print(f"  {label}: only {len(common)} common months, skipping")
            return None

        s = sig.reindex(common)
        r = spy_ret.reindex(common)

        # Log diagnostics
        print(f"  {label}:")
        print(f"    Period: {common[0].strftime('%Y-%m')} to {common[-1].strftime('%Y-%m')} ({len(common)} months)")
        print(f"    Frequency: {'monthly' if (common[1] - common[0]).days < 45 else 'quarterly ffilled'}")
        print(f"    Transform: {transform}")
        print(f"    Signal range: [{s.min():.3f}, {s.max():.3f}], std={s.std():.3f}")

        # Expanding quintiles
        q = pd.Series(3, index=common, dtype=int)
        for i in range(20, len(s)):
            hist = s.iloc[:i+1]
            pct = float((hist <= hist.iloc[-1]).mean()) * 100
            q.iloc[i] = 1 if pct < 20 else 2 if pct < 40 else 3 if pct < 60 else 4 if pct < 80 else 5
        w = q.map(alloc).astype(float)
        port = r * w
        eq = (1 + port).cumprod()
        years = len(port) / 12
        ann_ret = float(eq.iloc[-1] ** (1 / max(years, 0.5)) - 1) if eq.iloc[-1] > 0 else 0
        ann_vol = float(port.std() * np.sqrt(12))
        sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 1e-8 else 0
        sort = sortino_ratio(port)
        peak = eq.expanding().max()
        max_dd = round(float(((eq - peak) / peak).min()) * 100, 1)
        hit = round(float((port[w < 0.5] <= 0).mean()) * 100, 1) if (w < 0.5).sum() > 0 else 0
        total = round(float(eq.iloc[-1] - 1) * 100, 1)
        # Bootstrap p-value (5000 shuffles)
        sig_vals = s.values.copy()
        ret_vals = r.values
        null_sharpes = np.empty(5000)
        for i in range(5000):
            shuf_q = pd.Series(3, index=common, dtype=int)
            shuf_sig = np.random.permutation(sig_vals)
            for j in range(20, len(shuf_sig)):
                hist = shuf_sig[:j+1]
                pct = float((hist <= hist[j]).mean()) * 100
                shuf_q.iloc[j] = 1 if pct < 20 else 2 if pct < 40 else 3 if pct < 60 else 4 if pct < 80 else 5
            sw = shuf_q.map(alloc).astype(float).values
            sp = ret_vals * sw
            seq = np.cumprod(1 + sp)
            yrs = len(sp) / 12
            ar = float(seq[-1] ** (1 / max(yrs, 0.5)) - 1) if seq[-1] > 0 else 0
            av = float(np.std(sp) * np.sqrt(12))
            null_sharpes[i] = ar / av if av > 1e-8 else 0
        p_val = round(float(np.mean(null_sharpes >= sharpe)), 4)
        print(f"  {label:30s}: Sharpe={sharpe}, Sortino={sort}, DD={max_dd}%, Ret={total}%, p={p_val}")
        return {"sharpe": sharpe, "sortino": sort, "max_dd": max_dd, "total": total, "p": p_val}

    # Run GLI both ways to diagnose the Sharpe discrepancy
    print("\n  --- GLI comp_z as LEVEL (no mom6) ---")
    gli_level = _run_pipeline(gli_z, "GLI 5f level (comp_z)", apply_mom6=False)
    print("\n  --- GLI comp_z with mom6 applied ---")
    gli_mom6 = _run_pipeline(gli_z, "GLI 5f mom6(comp_z)", apply_mom6=True)
    print("\n  --- Stress index as LEVEL (no mom6) ---")
    stress_level = _run_pipeline(stress_m, "Stress level", apply_mom6=False)
    print("\n  --- Stress index with mom6 applied ---")
    stress_mom6 = _run_pipeline(stress_m, "Stress mom6", apply_mom6=True)

    print(f"\n  NOTE: Production GLI validation builds signal from RAW components,")
    print(f"  applies mom6 to the raw composite, THEN quintiles. The comp_z in")
    print(f"  the chart is already z-scored, so applying mom6 to it is different.")
    print(f"  The level version (no mom6) may be closer to the production result")
    print(f"  since comp_z already captures the signal regime.")

    # === Test 2: Divergence analysis ===
    print("\n" + "=" * 70)
    print("TEST 2: DIVERGENCE ANALYSIS")
    print("=" * 70)

    common = stress_m.index.intersection(gli_z.index).intersection(spy_ret.index)
    if len(common) < 60:
        print("  Not enough common data for divergence analysis")
        return

    sm = stress_m.reindex(common)
    gm = gli_z.reindex(common)
    sr = spy_ret.reindex(common)

    # Normalize
    sm_z = (sm - sm.mean()) / sm.std()
    gm_z = (gm - gm.mean()) / gm.std()
    divergence = sm_z + gm_z  # stress high + GLI negative (both = bad) → divergence positive when stress warns more

    # SPY forward returns
    spy_6m = sr.rolling(6).sum().shift(-6)
    spy_12m = sr.rolling(12).sum().shift(-12)

    # Stress warns, GLI doesn't (divergence > 1 std: stress is much more negative than GLI)
    stress_warns = divergence > 1.0
    gli_warns = divergence < -1.0

    print(f"\n  Divergence: stress_z + gli_z (positive = stress sees more risk than GLI)")
    print(f"  Threshold: |divergence| > 1.0 std")
    print(f"  Months where stress warns but GLI doesn't: {stress_warns.sum()}")
    print(f"  Months where GLI warns but stress doesn't: {gli_warns.sum()}")

    print(f"\n  STRESS WARNS, GLI DOESN'T:")
    print(f"  {'Date':12s} {'Stress_z':>10s} {'GLI_z':>10s} {'SPY 6M':>10s} {'SPY 12M':>10s}")
    warn_dates = common[stress_warns]
    for d in warn_dates[:15]:
        s6 = f"{spy_6m.get(d, np.nan)*100:.1f}%" if pd.notna(spy_6m.get(d)) else "N/A"
        s12 = f"{spy_12m.get(d, np.nan)*100:.1f}%" if pd.notna(spy_12m.get(d)) else "N/A"
        print(f"  {d.strftime('%Y-%m'):12s} {sm_z[d]:10.2f} {gm_z[d]:10.2f} {s6:>10s} {s12:>10s}")

    if len(warn_dates) > 0:
        avg_6m = spy_6m.reindex(warn_dates).dropna().mean() * 100
        avg_12m = spy_12m.reindex(warn_dates).dropna().mean() * 100
        print(f"  Avg fwd return when stress warns: 6M={avg_6m:.1f}%, 12M={avg_12m:.1f}%")

    print(f"\n  GLI WARNS, STRESS DOESN'T:")
    gli_dates = common[gli_warns]
    for d in gli_dates[:15]:
        s6 = f"{spy_6m.get(d, np.nan)*100:.1f}%" if pd.notna(spy_6m.get(d)) else "N/A"
        s12 = f"{spy_12m.get(d, np.nan)*100:.1f}%" if pd.notna(spy_12m.get(d)) else "N/A"
        print(f"  {d.strftime('%Y-%m'):12s} {sm_z[d]:10.2f} {gm_z[d]:10.2f} {s6:>10s} {s12:>10s}")

    if len(gli_dates) > 0:
        avg_6m = spy_6m.reindex(gli_dates).dropna().mean() * 100
        avg_12m = spy_12m.reindex(gli_dates).dropna().mean() * 100
        print(f"  Avg fwd return when GLI warns: 6M={avg_6m:.1f}%, 12M={avg_12m:.1f}%")

    print("=" * 70)
