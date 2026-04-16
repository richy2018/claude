"""Configuration for GLI Signal Filter Research."""

import os

# Date range
START_DATE = "2000-01-01"  # data fetch start (need history before signal period)
SIGNAL_START = "2001-01-01"  # first signal date (after mom6 warmup)
SIGNAL_END = "2025-12-31"

# Paths
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
DIAGNOSTICS_CSV = os.path.join(OUTPUT_DIR, "q5_diagnostics.csv")
SUMMARY_TXT = os.path.join(OUTPUT_DIR, "q5_diagnostics_summary.txt")

# FRED API
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

# FRED series needed for macro context
FRED_SERIES = {
    "FEDFUNDS": "Effective Federal Funds Rate",
    "BAMLH0A0HYM2": "BofA HY OAS",
    "DGS10": "10-Year Treasury Yield",
    "DGS2": "2-Year Treasury Yield",
    "T10Y2Y": "10Y-2Y Spread",
    "DFII10": "10Y TIPS Real Yield",
    "NAPM": "ISM Manufacturing PMI",  # reported with ~1 month lag
    "M2SL": "M2 Money Supply",
    "DFF": "Daily Fed Funds Rate",
}

# yfinance tickers
YF_TICKERS = {
    "SPY": "S&P 500 ETF",
    "^VIX": "VIX",
    "DX-Y.NYB": "DXY Dollar Index",
}

# GLI 5F production model config (must match backtest_engine.py)
GLI_5F_KEYS = [
    "quantity_signal", "m2_signal", "spread_signal",
    "dollar_stress_signal", "rate_signal",
]
GLI_5F_WEIGHTS = {
    "quantity_signal": 0.20,
    "m2_signal": 0.20,
    "spread_signal": 0.20,
    "dollar_stress_signal": 0.20,
    "rate_signal": 0.20,
}

# Production allocation rule
ALLOC_MAP = {1: 1.0, 2: 1.0, 3: 1.0, 4: 0.10, 5: 0.10}

# TP/FP thresholds
TP_STRICT_DD = -0.10       # fwd 6m max drawdown <= -10%
TP_MODERATE_DD = -0.07     # fwd 6m max drawdown <= -7%
TP_LOOSE_RETURN = 0.0      # fwd 3m return < 0
TP_COMBINED_DD = -0.07     # fwd 6m max drawdown <= -7% OR fwd 3m return < -5%
TP_COMBINED_RETURN = -0.05
