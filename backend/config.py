"""Configuration for the macro regime dashboard backend."""

import os

# FRED API key - set via environment variable
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

# FRED series definitions
FRED_SERIES = {
    # Treasury Yields
    "DFF": "Effective Federal Funds Rate",
    "DGS1": "1-Year Treasury Yield",
    "DGS2": "2-Year Treasury Yield",
    "DGS5": "5-Year Treasury Yield",
    "DGS10": "10-Year Treasury Yield",
    "DGS30": "30-Year Treasury Yield",
    "DGS3MO": "3-Month Treasury Yield",
    # Spreads
    "T10Y2Y": "10Y-2Y Spread",
    "T10Y3M": "10Y-3M Spread",
    # Credit Spreads
    # The ICE BofA series are licensed data: FRED serves only a ~3-year rolling
    # window regardless of observation_start, so they CANNOT carry a backtest.
    # Verified 2026-08-14: a request from 2000-01-01 returned 795 observations
    # beginning 2023-08-14. Keep them for the live dashboard; use BAA10Y for
    # anything historical (see CREDIT_SPREAD_SERIES below).
    "BAMLH0A0HYM2": "ICE BofA HY OAS (rolling 3y only)",
    "BAMLC0A4CBBB": "ICE BofA BBB OAS (rolling 3y only)",
    # Moody's Baa over 10Y Treasury — unrestricted, daily, back to 1986. This is
    # the credit spread the signal actually uses. Investment-grade rather than
    # high-yield, so it moves less violently in a crisis, but it is a real
    # credit spread with real history instead of a component pinned at neutral.
    "BAA10Y": "Moody's Baa Corporate Yield minus 10Y Treasury",
    # Dollar
    "DTWEXBGS": "Trade-Weighted Dollar Index",
    # Inflation (monthly, index level)
    "CPIAUCSL": "CPI All Items",
    "CPILFESL": "Core CPI",
    "PCEPI": "PCE Price Index",
    "PCEPILFE": "Core PCE",
    "PPIFIS": "PPI Final Demand",
    # Labor
    "UNRATE": "Unemployment Rate",
    "PAYEMS": "Nonfarm Payrolls",
    "ICSA": "Initial Jobless Claims",
    # GDP
    "GDP": "Gross Domestic Product",
    # Fed Funds
    "FEDFUNDS": "Federal Funds Rate (Monthly)",
    # Breakevens & TIPS
    "T5YIE": "5-Year Breakeven Inflation",
    "T10YIE": "10-Year Breakeven Inflation",
    "DFII5": "5-Year TIPS Real Yield",
    "DFII10": "10-Year TIPS Real Yield",
    "DFII20": "20-Year TIPS Real Yield",
    "DFII30": "30-Year TIPS Real Yield",
    "THREEFYTP10": "NY Fed ACM 10-Year Term Premium",
    "M2SL": "M2 Money Supply",
}

# GLI — Fed Net Liquidity components
# WALCL: Millions of USD (weekly)
# WTREGEN: Millions of USD (weekly)
# RRPONTSYD: Billions of USD (daily) — needs *1000 to align with WALCL
# WCURCIR: Millions of USD (weekly) — replaces discontinued CURRCIR
GLI_FED_SERIES = {
    "WALCL": "Fed Total Assets",
    "WTREGEN": "Treasury General Account",
    "RRPONTSYD": "Overnight Reverse Repo",
    "WCURCIR": "Currency in Circulation",
}

# GLI — FX rates for USD conversion of CB balance sheets
GLI_FX_SERIES = {
    "DEXUSEU": "EUR/USD",
    "DEXJPUS": "JPY/USD",
    "DEXCHUS": "CNY/USD",
}

# GLI — Central bank balance sheets available on FRED
GLI_CB_SERIES = {
    "JPNASSETS": "BoJ Total Assets",
    # PBoC: use IMF IFS SDMX API (no FRED series exists)
    # ECB: use ECB SDMX REST API (no key needed)
}

# Monthly series (need MoM%, YoY%, annualized rates)
MONTHLY_SERIES = ["CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE", "PPIFIS"]

# Credit-spread source for the GLI spread_signal, in order of preference. The
# first series with enough history wins — see pick_credit_spread() in
# models/gli_engine.py.
#
# Why this list exists: spread_signal carries 20% of the 5F composite but was
# sourced from BAMLH0A0HYM2, which FRED serves only as a ~3-year rolling window.
# The component was therefore absent for 96% of the backtest and, because
# missing components used to be zero-filled, read as a confident "neutral"
# rather than as missing. BAA10Y has history back to 1986 and no licence cap.
CREDIT_SPREAD_SERIES = ["BAA10Y", "BAMLH0A0HYM2", "BAMLC0A4CBBB"]

# A credit series shorter than this cannot support the signal's own transforms:
# diff(12) then a 36-month rolling z-score needs ~48 months before it emits
# anything, and the Rule A filter wants a 60-month percentile window on top.
MIN_CREDIT_SPREAD_MONTHS = 120

# Yahoo Finance tickers
YAHOO_TICKERS = {
    "^GSPC": "S&P 500",
    "^NDX": "Nasdaq 100",
    "DX-Y.NYB": "US Dollar Index (DXY)",
    "^VIX": "VIX",
    "CL=F": "WTI Crude Oil",
    "GC=F": "Gold",
    "^TYX": "30Y Treasury Yield",
    "^TNX": "10Y Treasury Yield",
    "^FVX": "5Y Treasury Yield",
}

# Sector ETFs
SECTOR_ETFS = {
    "XLE": "Energy",
    "XLB": "Materials",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLV": "Health Care",
    "XLF": "Financials",
    "XLK": "Info Tech",
    "XLC": "Communication Services",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "SPY": "S&P 500 ETF",
}

# Regime definitions — colors matched to frontend spec
REGIME_DEFINITIONS = {
    "R1": {"spx": "Up", "rates": "Up", "dxy": "Up", "color": "#00cc44", "label": "Risk-On Hawkish Strong$"},
    "R2": {"spx": "Up", "rates": "Up", "dxy": "Down", "color": "#008833", "label": "Risk-On Hawkish Weak$"},
    "R3": {"spx": "Up", "rates": "Down", "dxy": "Up", "color": "#00cccc", "label": "Risk-On Dovish Strong$"},
    "R4": {"spx": "Up", "rates": "Down", "dxy": "Down", "color": "#4488ff", "label": "Risk-On Dovish Weak$"},
    "R5": {"spx": "Down", "rates": "Up", "dxy": "Up", "color": "#ff4444", "label": "Risk-Off Hawkish Strong$"},
    "R6": {"spx": "Down", "rates": "Up", "dxy": "Down", "color": "#ff8800", "label": "Risk-Off Hawkish Weak$"},
    "R7": {"spx": "Down", "rates": "Down", "dxy": "Up", "color": "#8844cc", "label": "Risk-Off Dovish Strong$"},
    "R8": {"spx": "Down", "rates": "Down", "dxy": "Down", "color": "#cc44aa", "label": "Risk-Off Dovish Weak$"},
}
