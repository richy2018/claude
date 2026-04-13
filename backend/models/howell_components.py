"""Howell Liquidity — Phase 3: Fetch Candidate Liquidity Components.

Pulls observable liquidity proxies from FRED, converts to USD quarterly.
Does NOT import from or modify any production pipeline files.

FRED Series Units (verified):
- WALCL: Millions of USD (weekly)
- ECBASSETSW: Millions of EUR (weekly)
- JPNASSETS: 100 Million JPY / 億円 (weekly)
- MMMFFAQ027S: Millions of USD (quarterly)
- TLAACBW027SBOG: Billions of USD (weekly)
- RRPONTSYD: Billions of USD (daily)
- WTREGEN: Millions of USD (weekly)
- COMPOUT: Millions of USD (monthly)
- BUSLOANS: Billions of USD (monthly)
- M2SL: Billions of USD (monthly)
- MYAGM3EZM196N: National Currency EUR (monthly)
"""

import numpy as np
import pandas as pd


def _fetch_fred_series(series_id, api_key=None):
    """Fetch a single FRED series with detailed error reporting."""
    try:
        from fredapi import Fred
        import os
        key = api_key or os.environ.get("FRED_API_KEY", "")
        if not key:
            print(f"[HOWELL FRED] No API key — cannot fetch {series_id}")
            return pd.Series(dtype=float)
        fred = Fred(api_key=key)
        s = fred.get_series(series_id, observation_start="1999-01-01")
        if s is not None and len(s) > 0:
            s.index = pd.to_datetime(s.index)
            s = s.dropna()
            print(f"[HOWELL FRED] {series_id}: OK, {len(s)} obs, latest={s.iloc[-1]:.2f} ({s.index[-1].strftime('%Y-%m')})")
            return s
        else:
            print(f"[HOWELL FRED] {series_id}: returned None or empty")
    except Exception as e:
        print(f"[HOWELL FRED] {series_id}: FAILED — {type(e).__name__}: {e}")
    return pd.Series(dtype=float)


def _to_quarterly(s):
    """Resample to quarterly end-of-quarter."""
    if len(s) == 0:
        return s
    return s.resample("QE").last().dropna()


def fetch_liquidity_candidates(api_key=None):
    """Fetch all candidate liquidity components from FRED.

    Returns DataFrame with quarterly data in USD TRILLIONS.
    """
    import os
    key = api_key or os.environ.get("FRED_API_KEY", "")
    components = {}
    meta = {}

    print(f"[HOWELL P3] API key present: {bool(key)} (len={len(key)})")

    # FX rates for conversion
    print("[HOWELL P3] Fetching FX rates...")
    eurusd = _to_quarterly(_fetch_fred_series("DEXUSEU", key))  # EUR per USD
    jpyusd = _to_quarterly(_fetch_fred_series("DEXJPUS", key))  # JPY per USD

    # ─── Block A: Central Bank Balance Sheets ────────────────────────────

    print("[HOWELL P3] Block A: Central Bank Balance Sheets...")

    # Fed (WALCL) — MILLIONS of USD
    walcl = _fetch_fred_series("WALCL", key)
    if len(walcl) > 0:
        walcl_q = _to_quarterly(walcl)
        fed = walcl_q / 1e6  # millions → trillions
        components["fed_assets"] = fed
        print(f"[HOWELL P3]   Fed: raw={walcl_q.iloc[-1]:.0f} (millions USD) → ${fed.iloc[-1]:.2f}T")

    # ECB (ECBASSETSW) — MILLIONS of EUR
    ecb_raw = _fetch_fred_series("ECBASSETSW", key)
    if len(ecb_raw) > 0 and len(eurusd) > 0:
        ecb_q = _to_quarterly(ecb_raw)
        fx = eurusd.reindex(ecb_q.index, method="ffill")
        ecb = ecb_q * fx / 1e6  # millions EUR × (USD/EUR) / 1e6 → trillions USD
        components["ecb_assets"] = ecb
        print(f"[HOWELL P3]   ECB: raw={ecb_q.iloc[-1]:.0f} (millions EUR), FX={fx.iloc[-1]:.3f} → ${ecb.iloc[-1]:.2f}T")

    # BOJ (JPNASSETS) — 100 MILLION JPY (億円)
    # Value like 7,641,238 means 764,123,800,000,000 JPY = 764 trillion JPY
    boj_raw = _fetch_fred_series("JPNASSETS", key)
    if len(boj_raw) > 0 and len(jpyusd) > 0:
        boj_q = _to_quarterly(boj_raw)
        fx = jpyusd.reindex(boj_q.index, method="ffill")
        # raw × 1e8 (100M JPY units) / JPY_per_USD / 1e12 = trillions USD
        boj = boj_q * 1e8 / fx / 1e12
        components["boj_assets"] = boj
        print(f"[HOWELL P3]   BOJ: raw={boj_q.iloc[-1]:.0f} (100M JPY), FX={fx.iloc[-1]:.1f} → ${boj.iloc[-1]:.2f}T")

    # BOE — try multiple FRED series for Bank of England total assets
    gbpusd = _to_quarterly(_fetch_fred_series("DEXUSUK", key))  # USD per GBP
    for boe_id in ["BOEAESTAM", "BOABOROAM"]:
        boe_raw = _fetch_fred_series(boe_id, key)
        if len(boe_raw) > 10:
            break
    if len(boe_raw) > 10 and len(gbpusd) > 0:
        boe_q = _to_quarterly(boe_raw)
        fx_gbp = gbpusd.reindex(boe_q.index, method="ffill")
        raw_val = float(boe_q.iloc[-1])
        # Auto-detect units and convert GBP → USD → trillions
        if raw_val > 1e9:
            boe = boe_q * fx_gbp / 1e12  # raw GBP → trillions USD
        elif raw_val > 1e6:
            boe = boe_q * fx_gbp / 1e6   # millions GBP → trillions USD
        else:
            boe = boe_q * fx_gbp / 1e3   # billions GBP → trillions USD
        components["boe_assets"] = boe
        print(f"[HOWELL P3]   BOE ({boe_id}): raw={raw_val:.0f}, FX={fx_gbp.iloc[-1]:.3f} → ${boe.iloc[-1]:.2f}T")
    else:
        print(f"[HOWELL P3]   BOE: no FRED series found")

    # G4 CB total (Fed + ECB + BOJ + BOE)
    g4_keys = ["fed_assets", "ecb_assets", "boj_assets", "boe_assets"]
    g4_available = [k for k in g4_keys if k in components]
    if len(g4_available) >= 2:
        g4_df = pd.DataFrame({k: components[k] for k in g4_available})
        components["g4_cb_assets"] = g4_df.sum(axis=1).dropna()
        print(f"[HOWELL P3]   G4 CB total: ${components['g4_cb_assets'].iloc[-1]:.1f}T ({len(g4_available)} banks)")

    # ─── Block B: US Financial System ────────────────────────────────────

    print("[HOWELL P3] Block B: US Financial System...")

    # Money Market Funds — MILLIONS of USD (quarterly)
    mmf = _fetch_fred_series("MMMFFAQ027S", key)
    if len(mmf) > 0:
        mmf_q = _to_quarterly(mmf)
        components["mmf_assets"] = mmf_q / 1e6  # millions → trillions
        print(f"[HOWELL P3]   MMF: raw={mmf_q.iloc[-1]:.0f} → ${components['mmf_assets'].iloc[-1]:.2f}T")

    # Commercial bank total assets — BILLIONS of USD (weekly)
    bank = _fetch_fred_series("TLAACBW027SBOG", key)
    if len(bank) > 0:
        bank_q = _to_quarterly(bank)
        components["bank_assets"] = bank_q / 1e3  # billions → trillions
        print(f"[HOWELL P3]   Banks: raw={bank_q.iloc[-1]:.0f} (billions) → ${components['bank_assets'].iloc[-1]:.1f}T")

    # Fed net liquidity = WALCL - TGA - RRP
    tga = _fetch_fred_series("WTREGEN", key)  # millions USD
    rrp = _fetch_fred_series("RRPONTSYD", key)  # billions USD
    if len(walcl) > 0 and len(tga) > 0 and len(rrp) > 0:
        walcl_q = _to_quarterly(walcl)  # millions
        tga_q = _to_quarterly(tga)      # millions
        rrp_q = _to_quarterly(rrp) * 1000  # billions → millions (match WALCL units)
        common = walcl_q.index.intersection(tga_q.index).intersection(rrp_q.index)
        net_liq = (walcl_q.reindex(common) - tga_q.reindex(common) - rrp_q.reindex(common)) / 1e6  # millions → trillions
        components["fed_net_liquidity"] = net_liq.dropna()
        print(f"[HOWELL P3]   Fed Net Liq: ${components['fed_net_liquidity'].iloc[-1]:.2f}T")

    # ─── Block C: Credit Proxies ─────────────────────────────────────────

    print("[HOWELL P3] Block C: Credit Proxies...")

    # Commercial Paper — BILLIONS of USD (monthly)
    cp = _fetch_fred_series("COMPOUT", key)
    if len(cp) > 0:
        cp_q = _to_quarterly(cp)
        components["commercial_paper"] = cp_q / 1e3  # billions → trillions
        print(f"[HOWELL P3]   Commercial Paper: raw={cp_q.iloc[-1]:.0f} (billions) → ${components['commercial_paper'].iloc[-1]:.3f}T")

    # Bank Loans (C&I) — BILLIONS of USD (monthly)
    busloans = _fetch_fred_series("BUSLOANS", key)
    if len(busloans) > 0:
        bl_q = _to_quarterly(busloans)
        components["bank_loans"] = bl_q / 1e3  # billions → trillions
        print(f"[HOWELL P3]   Bank Loans: raw={bl_q.iloc[-1]:.0f} (billions) → ${components['bank_loans'].iloc[-1]:.2f}T")

    # ─── Block D: Broad Money (control group) ────────────────────────────

    print("[HOWELL P3] Block D: Broad Money (control)...")

    # US M2 — BILLIONS of USD (monthly)
    m2 = _fetch_fred_series("M2SL", key)
    if len(m2) > 0:
        m2_q = _to_quarterly(m2)
        components["us_m2"] = m2_q / 1e3  # billions → trillions
        print(f"[HOWELL P3]   US M2: raw={m2_q.iloc[-1]:.0f} (billions) → ${components['us_m2'].iloc[-1]:.1f}T")

    # Eurozone M3 — try multiple series (MYAGM3EZM196N discontinued 2017)
    ez_m3_series = ["MANMM101EZM189S", "MABMM301EZM189S", "MYAGM3EZM196N"]
    for ez_id in ez_m3_series:
        ez_m3 = _fetch_fred_series(ez_id, key)
        if len(ez_m3) > 0 and float(ez_m3.index[-1].year) >= 2020:
            break  # Found a current series
    if len(ez_m3) > 0 and len(eurusd) > 0:
        ez_q = _to_quarterly(ez_m3)
        fx = eurusd.reindex(ez_q.index, method="ffill")
        raw_val = float(ez_q.iloc[-1])
        # Auto-scale: detect if raw EUR, millions, or billions
        if raw_val > 1e11:
            ez_usd = ez_q * fx / 1e12
        elif raw_val > 1e8:
            ez_usd = ez_q * fx / 1e9
        else:
            ez_usd = ez_q * fx / 1e3
        components["ez_m3"] = ez_usd
        print(f"[HOWELL P3]   EZ M3 ({ez_id}): raw={raw_val:.0f}, FX={fx.iloc[-1]:.3f} → ${ez_usd.iloc[-1]:.1f}T")
    else:
        print(f"[HOWELL P3]   EZ M3: all series failed or discontinued")

    # Global M2 proxy
    m2_keys = [k for k in ["us_m2", "ez_m3"] if k in components]
    if m2_keys:
        m2_df = pd.DataFrame({k: components[k] for k in m2_keys})
        components["global_m2_proxy"] = m2_df.sum(axis=1).dropna()
        print(f"[HOWELL P3]   Global M2 proxy: ${components['global_m2_proxy'].iloc[-1]:.1f}T")

    # ─── Summary ─────────────────────────────────────────────────────────

    print(f"\n[HOWELL P3] === COMPONENT SUMMARY ===")
    for name, s in components.items():
        if len(s) > 0:
            print(f"[HOWELL P3]   {name:25s}: ${s.iloc[-1]:10.2f}T  ({len(s)} quarters, {s.index[0].strftime('%Y')}-{s.index[-1].strftime('%Y')})")
    print(f"[HOWELL P3] Total: {len(components)} components fetched")

    if not components:
        return pd.DataFrame(), {}

    combined = pd.DataFrame(components)
    combined.index = pd.to_datetime(combined.index)
    combined = combined.sort_index()

    return combined, meta
