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
    "BAMLH0A0HYM2": "ICE BofA HY OAS",
    "BAMLC0A4CBBB": "ICE BofA BBB OAS",
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
}

# Monthly series (need MoM%, YoY%, annualized rates)
MONTHLY_SERIES = ["CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE", "PPIFIS"]

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
