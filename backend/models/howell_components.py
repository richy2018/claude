"""Howell Liquidity — Phase 3: Fetch Candidate Liquidity Components.

Pulls observable liquidity proxies from FRED, converts to USD quarterly.
Does NOT import from or modify any production pipeline files.
"""

import numpy as np
import pandas as pd


def _fetch_fred_series(series_id, api_key=None):
    """Fetch a single FRED series. Uses fredapi if available, falls back to requests."""
    try:
        from fredapi import Fred
        import os
        key = api_key or os.environ.get("FRED_API_KEY", "")
        if not key:
            print(f"[HOWELL FRED] No API key for {series_id}")
            return pd.Series(dtype=float)
        fred = Fred(api_key=key)
        s = fred.get_series(series_id, observation_start="1999-01-01")
        if s is not None and len(s) > 0:
            s.index = pd.to_datetime(s.index)
            return s.dropna()
    except Exception as e:
        print(f"[HOWELL FRED] {series_id} error: {e}")
    return pd.Series(dtype=float)


def _fetch_fx_rate(series_id, api_key=None):
    """Fetch FX rate from FRED, resample to quarterly."""
    s = _fetch_fred_series(series_id, api_key)
    if len(s) > 0:
        return s.resample("QE").last().dropna()
    return pd.Series(dtype=float)


def _to_quarterly_billions(s):
    """Resample to quarterly end-of-quarter, ensure in billions USD."""
    if len(s) == 0:
        return s
    q = s.resample("QE").last().dropna()
    return q


def fetch_liquidity_candidates(api_key=None):
    """Fetch all candidate liquidity components from FRED.

    Returns DataFrame with quarterly data, columns are component names.
    All values in USD trillions.
    """
    import os
    key = api_key or os.environ.get("FRED_API_KEY", "")
    components = {}
    meta = {}

    # FX rates for conversion
    print("[HOWELL P3] Fetching FX rates...")
    eurusd = _fetch_fx_rate("DEXUSEU", key)  # EUR per USD → multiply EUR values
    jpyusd = _fetch_fx_rate("DEXJPUS", key)  # JPY per USD → divide JPY values
    gbpusd = _fetch_fx_rate("DEXUSUK", key)  # USD per GBP → multiply GBP values

    # ─── Block A: Central Bank Balance Sheets ────────────────────────────

    print("[HOWELL P3] Block A: Central Bank Balance Sheets...")

    # Fed (WALCL) — millions USD
    walcl = _fetch_fred_series("WALCL", key)
    if len(walcl) > 0:
        fed = _to_quarterly_billions(walcl) / 1000  # millions → trillions
        components["fed_assets"] = fed
        meta["fed_assets"] = f"Fed WALCL: {len(fed)} obs to {fed.index[-1].strftime('%Y-%m')}"
        print(f"[HOWELL P3]   Fed: ${fed.iloc[-1]:.1f}T")

    # ECB (ECBASSETSW) — millions EUR
    ecb_raw = _fetch_fred_series("ECBASSETSW", key)
    if len(ecb_raw) > 0 and len(eurusd) > 0:
        ecb_q = _to_quarterly_billions(ecb_raw)
        fx = eurusd.reindex(ecb_q.index, method="ffill")
        ecb = ecb_q * fx / 1e6  # millions EUR × EUR/USD → trillions USD
        components["ecb_assets"] = ecb
        print(f"[HOWELL P3]   ECB: ${ecb.iloc[-1]:.1f}T")

    # BOJ (JPNASSETS) — 100 million JPY (億円)
    boj_raw = _fetch_fred_series("JPNASSETS", key)
    if len(boj_raw) > 0 and len(jpyusd) > 0:
        boj_q = _to_quarterly_billions(boj_raw)
        fx = jpyusd.reindex(boj_q.index, method="ffill")
        boj = boj_q / (fx * 10)  # 100M JPY / (JPY/USD × 10) → trillions USD
        components["boj_assets"] = boj
        print(f"[HOWELL P3]   BOJ: ${boj.iloc[-1]:.1f}T")

    # G4 CB total (Fed + ECB + BOJ, skip BOE for now)
    g4_keys = ["fed_assets", "ecb_assets", "boj_assets"]
    g4_available = [k for k in g4_keys if k in components]
    if len(g4_available) >= 2:
        g4_df = pd.DataFrame({k: components[k] for k in g4_available})
        components["g4_cb_assets"] = g4_df.sum(axis=1).dropna()
        print(f"[HOWELL P3]   G4 CB: ${components['g4_cb_assets'].iloc[-1]:.1f}T ({len(g4_available)} banks)")

    # ─── Block B: US Financial System ────────────────────────────────────

    print("[HOWELL P3] Block B: US Financial System...")

    # Money Market Funds
    mmf = _fetch_fred_series("BOGZ1FL794104005Q", key)
    if len(mmf) > 0:
        components["mmf_assets"] = _to_quarterly_billions(mmf) / 1e6  # millions → trillions
        print(f"[HOWELL P3]   MMF: ${components['mmf_assets'].iloc[-1]:.1f}T")

    # Commercial bank total assets
    bank = _fetch_fred_series("TLAACBW027SBOG", key)
    if len(bank) > 0:
        components["bank_assets"] = _to_quarterly_billions(bank) / 1e6  # millions → trillions
        print(f"[HOWELL P3]   Banks: ${components['bank_assets'].iloc[-1]:.1f}T")

    # Fed net liquidity = WALCL - TGA - RRP
    tga = _fetch_fred_series("WTREGEN", key)
    rrp = _fetch_fred_series("RRPONTSYD", key)
    if len(walcl) > 0 and len(tga) > 0 and len(rrp) > 0:
        walcl_q = _to_quarterly_billions(walcl)
        tga_q = _to_quarterly_billions(tga)
        rrp_q = _to_quarterly_billions(rrp) * 1000  # billions → millions (match WALCL units)
        common = walcl_q.index.intersection(tga_q.index).intersection(rrp_q.index)
        net_liq = (walcl_q.reindex(common) - tga_q.reindex(common) - rrp_q.reindex(common)) / 1e6
        components["fed_net_liquidity"] = net_liq.dropna()
        print(f"[HOWELL P3]   Fed Net Liq: ${components['fed_net_liquidity'].iloc[-1]:.1f}T")

    # ─── Block C: Credit Proxies ─────────────────────────────────────────

    print("[HOWELL P3] Block C: Credit Proxies...")

    cp = _fetch_fred_series("COMPOUT", key)
    if len(cp) > 0:
        components["commercial_paper"] = _to_quarterly_billions(cp) / 1e6
        print(f"[HOWELL P3]   Commercial Paper: ${components['commercial_paper'].iloc[-1]:.2f}T")

    busloans = _fetch_fred_series("BUSLOANS", key)
    if len(busloans) > 0:
        components["bank_loans"] = _to_quarterly_billions(busloans) / 1e6
        print(f"[HOWELL P3]   Bank Loans: ${components['bank_loans'].iloc[-1]:.1f}T")

    # ─── Block D: Broad Money (control group) ────────────────────────────

    print("[HOWELL P3] Block D: Broad Money (control)...")

    m2 = _fetch_fred_series("M2SL", key)
    if len(m2) > 0:
        us_m2 = _to_quarterly_billions(m2) / 1e6  # billions → trillions
        components["us_m2"] = us_m2
        print(f"[HOWELL P3]   US M2: ${us_m2.iloc[-1]:.1f}T")

    ez_m3 = _fetch_fred_series("MYAGM3EZM196N", key)
    if len(ez_m3) > 0 and len(eurusd) > 0:
        ez_q = _to_quarterly_billions(ez_m3)
        fx = eurusd.reindex(ez_q.index, method="ffill")
        ez_usd = ez_q * fx / 1e6  # millions EUR → trillions USD
        components["ez_m3"] = ez_usd
        print(f"[HOWELL P3]   EZ M3: ${ez_usd.iloc[-1]:.1f}T")

    # Global M2 proxy = US M2 + EZ M3
    m2_keys = [k for k in ["us_m2", "ez_m3"] if k in components]
    if m2_keys:
        m2_df = pd.DataFrame({k: components[k] for k in m2_keys})
        components["global_m2_proxy"] = m2_df.sum(axis=1).dropna()
        print(f"[HOWELL P3]   Global M2 proxy: ${components['global_m2_proxy'].iloc[-1]:.1f}T")

    # ─── Combine ─────────────────────────────────────────────────────────

    print(f"[HOWELL P3] Total: {len(components)} components fetched")

    # Build combined DataFrame on common quarterly dates
    if not components:
        return pd.DataFrame(), {}

    combined = pd.DataFrame(components)
    combined.index = pd.to_datetime(combined.index)
    combined = combined.sort_index()

    return combined, meta
