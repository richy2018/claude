"""COT module configuration — contract universe, report types, cohorts.

CFTC `Market_and_Exchange_Names` strings are messy and change over time, so we
keep a config of friendly symbol -> report + candidate name substrings, and
resolve them against `list_available_contracts()` at runtime (exactly how NQ
was resolved in the reference build). Adding an asset = one config line.

Report-type rule (the rule from the brief, §2):
  - Equity indices / FX / Rates -> TFF, primary cohort = Leveraged Funds
  - Commodities                  -> Disaggregated, primary cohort = Managed Money
  - Any (universal fallback)     -> Legacy, primary cohort = Non-Commercial

We ALWAYS also pull legacy_fut for every contract: legacy gives a consistent
3-way shape across all assets (the reference chart); TFF/disagg gives the
sharper cohort split. The heatmap uses each asset's primary speculative cohort
COT index; the detail chart lets the user toggle report type.
"""

# ── Internal report keys -> pycot-reports cot_report_type strings ────────────
# The DB stores the canonical key on the left (matches the schema CHECK set).
REPORT_TYPES = {
    "legacy_fut": "legacy_fut",
    "tff_fut": "traders_in_financial_futures_fut",
    "disaggregated_fut": "disaggregated_fut",
}

# Sanity-check tokens used to confirm the right report was loaded (§2):
# TFF shows Leveraged Funds (raw col Lev_Money) / Asset Manager (Asset_Mgr);
# disaggregated shows Producer/Merchant (Prod_Merc) / Swap Dealer; legacy shows
# Noncommercial. Tokens are matched against raw columns with '_' -> ' '. If the
# category tokens are absent, the wrong report was loaded.
REPORT_IDENTITY_TOKENS = {
    "tff_fut": ["lev money", "asset mgr"],
    "disaggregated_fut": ["prod merc", "swap"],
    "legacy_fut": ["noncommercial"],
}

# ── Contract universe ────────────────────────────────────────────────────────
# class:  index | fx | rates | commodity
# report: the asset-appropriate report (we also pull legacy_fut for every one)
# names:  candidate substrings resolved against list_available_contracts()
CONTRACTS = {
    # equity indices  -> TFF
    "ES":  {"class": "index", "report": "tff_fut", "names": ["E-MINI S&P 500", "S&P 500 STOCK INDEX"]},
    "NQ":  {"class": "index", "report": "tff_fut", "names": ["NASDAQ MINI", "E-MINI NASDAQ-100", "NASDAQ-100 STOCK INDEX (MINI)"]},
    "RTY": {"class": "index", "report": "tff_fut", "names": ["E-MINI RUSSELL 2000", "RUSSELL E-MINI", "RUSSELL 2000 MINI"]},
    "YM":  {"class": "index", "report": "tff_fut", "names": ["DJIA", "E-MINI DOW", "DOW JONES"]},
    # FX  -> TFF
    "EUR": {"class": "fx", "report": "tff_fut", "names": ["EURO FX"]},
    "JPY": {"class": "fx", "report": "tff_fut", "names": ["JAPANESE YEN"]},
    "GBP": {"class": "fx", "report": "tff_fut", "names": ["BRITISH POUND"]},
    "CHF": {"class": "fx", "report": "tff_fut", "names": ["SWISS FRANC"]},
    "AUD": {"class": "fx", "report": "tff_fut", "names": ["AUSTRALIAN DOLLAR"]},
    "CAD": {"class": "fx", "report": "tff_fut", "names": ["CANADIAN DOLLAR"]},
    "MXN": {"class": "fx", "report": "tff_fut", "names": ["MEXICAN PESO"]},
    # rates -> TFF
    "ZN":   {"class": "rates", "report": "tff_fut", "names": ["UST 10Y NOTE", "10-YEAR U.S. TREASURY", "10 YEAR U.S. TREASURY"]},
    "ZB":   {"class": "rates", "report": "tff_fut", "names": ["UST BOND", "U.S. TREASURY BONDS"]},
    "ZF":   {"class": "rates", "report": "tff_fut", "names": ["UST 5Y NOTE", "5-YEAR U.S. TREASURY"]},
    "ZT":   {"class": "rates", "report": "tff_fut", "names": ["UST 2Y NOTE", "2-YEAR U.S. TREASURY"]},
    "SOFR": {"class": "rates", "report": "tff_fut", "names": ["SOFR-3M", "3-MONTH SOFR"]},
    # commodities -> disaggregated
    # CL: prefer the NYMEX benchmark over the ICE Futures Europe WTI look-alike.
    "CL": {"class": "commodity", "report": "disaggregated_fut", "exchange": "NEW YORK MERCANTILE", "names": ["CRUDE OIL, LIGHT SWEET", "WTI-PHYSICAL", "CRUDE OIL LIGHT SWEET"]},
    "NG": {"class": "commodity", "report": "disaggregated_fut", "names": ["NAT GAS NYME", "NATURAL GAS"]},
    "GC": {"class": "commodity", "report": "disaggregated_fut", "names": ["GOLD - COMMODITY EXCHANGE"]},
    "SI": {"class": "commodity", "report": "disaggregated_fut", "names": ["SILVER - COMMODITY EXCHANGE"]},
    "HG": {"class": "commodity", "report": "disaggregated_fut", "names": ["COPPER- #1", "COPPER"]},
    "ZC": {"class": "commodity", "report": "disaggregated_fut", "names": ["CORN - CHICAGO BOARD OF TRADE"]},
    # ZW: CFTC names Chicago wheat "WHEAT-SRW" (Soft Red Winter).
    "ZW": {"class": "commodity", "report": "disaggregated_fut", "names": ["WHEAT-SRW", "WHEAT - CHICAGO BOARD OF TRADE", "WHEAT"]},
    "ZS": {"class": "commodity", "report": "disaggregated_fut", "names": ["SOYBEANS - CHICAGO BOARD OF TRADE"]},
}

# Contract variants we avoid unless the matched candidate explicitly asks for
# them — the resolver demotes a name containing these so the STANDARD contract
# wins (e.g. avoid MICRO SILVER / ULTRA UST BOND / MINI SOYBEANS, but keep the
# intended E-MINI S&P 500 because its candidate contains "MINI").
DEMOTE_VARIANT_TOKENS = ["micro", "ultra", "mini"]

# Display ordering of classes for the heatmap (indices / FX / rates / commodities).
CLASS_ORDER = ["index", "fx", "rates", "commodity"]
CLASS_LABELS = {
    "index": "Equity Indices",
    "fx": "FX",
    "rates": "Rates",
    "commodity": "Commodities",
}

# ── Cohort canonical keys (match the schema CHECK / UNIQUE set) ───────────────
# The primary speculative cohort per report drives the COT index / heatmap.
PRIMARY_COHORT = {
    "tff_fut": "lev_funds",
    "disaggregated_fut": "managed_money",
    "legacy_fut": "non_comm",
}

# Cohorts stored per report type, in display order. The first entry is primary.
COHORTS_BY_REPORT = {
    "tff_fut": ["lev_funds", "asset_mgr", "dealer", "other"],
    "disaggregated_fut": ["managed_money", "producer_merchant", "swap_dealer", "other"],
    "legacy_fut": ["non_comm", "commercial", "non_rept"],
}

# Human labels + the reference chart palette (blue / red / yellow / green).
COHORT_LABELS = {
    "lev_funds": "Leveraged Funds",
    "asset_mgr": "Asset Manager",
    "dealer": "Dealer/Intermediary",
    "managed_money": "Managed Money",
    "producer_merchant": "Producer/Merchant",
    "swap_dealer": "Swap Dealer",
    "other": "Other Reportables",
    "non_comm": "Non-Commercial",
    "commercial": "Commercial",
    "non_rept": "Non-Reportable",
}

COHORT_COLORS = {
    # speculative cohorts -> blue (matches reference Non-Comm blue)
    "lev_funds": "#5b9dff",
    "managed_money": "#5b9dff",
    "non_comm": "#5b9dff",
    # hedger/commercial cohorts -> red
    "commercial": "#f0463a",
    "producer_merchant": "#f0463a",
    "dealer": "#f0463a",
    # small/other -> yellow
    "non_rept": "#f5c451",
    "other": "#f5c451",
    "asset_mgr": "#27c08a",
    "swap_dealer": "#27c08a",
}

# ── Cohort column resolution patterns ────────────────────────────────────────
# CFTC column names vary across reports AND naming styles: legacy uses spaced
# names ("Noncommercial Positions-Long (All)") while TFF/disagg use underscores
# ("Lev_Money_Positions_Long_All", "M_Money_Positions_Long_All"). The matcher
# (transform.py) normalises _ - ( ) to spaces, then requires a column to contain
# 'positions', 'all', a side token (long/short), no EXCLUDE token, and to match
# ANY one of the cohort's alternative token-groups (every token in the group
# present). Alternatives cover both raw underscore codes and friendlier variants.
COHORT_COLUMN_TOKENS = {
    "tff_fut": {
        "lev_funds": [["lev", "money"], ["leveraged"]],          # Lev_Money_Positions_*
        "asset_mgr": [["asset"]],                                  # Asset_Mgr_Positions_*
        "dealer": [["dealer"]],                                    # Dealer_Positions_*
        "other": [["other"]],                                      # Other_Rept_Positions_*
    },
    "disaggregated_fut": {
        "managed_money": [["money"], ["managed"]],                 # M_Money_Positions_*
        "producer_merchant": [["prod"], ["producer"]],             # Prod_Merc_Positions_*
        "swap_dealer": [["swap"]],                                 # Swap_Positions_*
        "other": [["other"]],                                      # Other_Rept_Positions_*
    },
    "legacy_fut": {
        "non_comm": [["noncommercial"]],                           # Noncommercial Positions-*
        "commercial": [["commercial"]],   # NB: disambiguated from 'noncommercial'
        "non_rept": [["nonreportable"]],                           # Nonreportable Positions-*
    },
}

# Tokens that disqualify a column from being an All-period long/short position
# column (spreading, % of OI, trader counts, week-over-week changes,
# concentration ratios, crop-year Old/Other variants — those lack 'all').
COHORT_COLUMN_EXCLUDE = [
    "spread", "pct", "percent", "%", "number", "trader", "change",
    "ratio", "conc", "open interest",
]

# A real position column must contain these (after normalisation).
COHORT_COLUMN_REQUIRE = ["positions", "all"]

LONG_TOKENS = ["long"]
SHORT_TOKENS = ["short"]

OPEN_INTEREST_TOKENS = ["open interest", "open_interest"]

# Raw CFTC market-name columns (resolve friendly symbol -> verbatim name).
MARKET_NAME_COLUMNS = ["Market_and_Exchange_Names", "Market and Exchange Names"]

DEFAULT_LOOKBACK = 156  # weeks (3y) — the validated COT-index window
