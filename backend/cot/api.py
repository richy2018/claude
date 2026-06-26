"""COT API (§7) — FastAPI router.

  GET /api/cot/universe                          -> heatmap source (assets + latest primary cohort index)
  GET /api/cot/heatmap?cohort=primary&lookback=  -> matrix [asset x latest cot_index] + 1w/4w change
  GET /api/cot/{symbol}?report_type=&lookback=   -> per-cohort net/OI/cot_index/zscore series (detail chart)
  GET /api/cot/health                            -> fetch/validation health for the staleness banner

COT index / z-score are computed on read here (transform.build_series), never
stored denormalised. The price overlay is intentionally NOT served: per the
licensing guardrail it must come from a licensed provider and stays off by
default (the detail endpoint exposes a `price_overlay: null` contract the
frontend can light up once a licensed feed is wired).

NON-ADVISORY: every payload carries the standing disclaimer — this module
presents positioning data and base rates only, never buy/sell advice.
"""

from fastapi import APIRouter, HTTPException, Query

from . import db, alerts
from .config import (
    CONTRACTS, REPORT_TYPES, PRIMARY_COHORT, COHORTS_BY_REPORT, COHORT_LABELS,
    COHORT_COLORS, CLASS_ORDER, CLASS_LABELS, DEFAULT_LOOKBACK,
)
from .transform import build_series, latest_cot_index

router = APIRouter(prefix="/api/cot", tags=["cot"])

DISCLAIMER = (
    "Positioning data from CFTC Commitments of Traders (public domain). For "
    "information only — presents positioning, extremes and base rates as data. "
    "Not investment advice, and no buy/sell recommendation on any asset."
)


def _primary_report(symbol: str) -> str:
    return CONTRACTS[symbol]["report"]


@router.get("/universe")
async def universe(lookback: int = Query(DEFAULT_LOOKBACK, ge=20, le=520)):
    """Assets with class + latest primary-cohort COT index (powers the heatmap)."""
    assets = []
    for symbol, cfg in CONTRACTS.items():
        report = cfg["report"]
        cohort = PRIMARY_COHORT[report]
        rows = db.fetch_series(symbol, report)
        latest = latest_cot_index(rows, cohort, lookback) if rows else None
        assets.append({
            "symbol": symbol,
            "class": cfg["class"],
            "class_label": CLASS_LABELS[cfg["class"]],
            "report_type": report,
            "primary_cohort": cohort,
            "primary_cohort_label": COHORT_LABELS[cohort],
            "latest": latest,
            "has_data": bool(rows),
        })
    return {
        "assets": assets,
        "class_order": CLASS_ORDER,
        "lookback": lookback,
        "disclaimer": DISCLAIMER,
    }


@router.get("/heatmap")
async def heatmap(cohort: str = Query("primary"),
                  lookback: int = Query(DEFAULT_LOOKBACK, ge=20, le=520)):
    """Matrix [asset x latest cot_index] grouped by class, with 1w/4w change and
    a recent sparkline. `cohort=primary` uses each asset's primary speculative
    cohort; otherwise a specific cohort key is applied where present."""
    groups = {cls: [] for cls in CLASS_ORDER}
    for symbol, cfg in CONTRACTS.items():
        report = cfg["report"]
        coh = PRIMARY_COHORT[report] if cohort == "primary" else cohort
        rows = db.fetch_series(symbol, report)
        cell = latest_cot_index(rows, coh, lookback) if rows else None
        flag = None
        if cell and cell["value"] is not None:
            if cell["value"] >= 90:
                flag = "high"
            elif cell["value"] <= 10:
                flag = "low"
        groups[cfg["class"]].append({
            "symbol": symbol,
            "cohort": coh,
            "cohort_label": COHORT_LABELS.get(coh, coh),
            "value": cell["value"] if cell else None,
            "net": cell["net"] if cell else None,
            "date": cell["date"] if cell else None,
            "chg_1w": cell["chg_1w"] if cell else None,
            "chg_4w": cell["chg_4w"] if cell else None,
            "spark": cell["spark"] if cell else [],
            "flag": flag,
        })
    rows_out = [{
        "class": cls,
        "class_label": CLASS_LABELS[cls],
        "assets": groups[cls],
    } for cls in CLASS_ORDER]
    return {
        "groups": rows_out,
        "cohort": cohort,
        "lookback": lookback,
        "color_scale": {"low": "#5b9dff", "mid": "#1a1a1e", "high": "#f0463a"},
        "disclaimer": DISCLAIMER,
    }


@router.get("/health")
async def health():
    """Fetch + validation health (staleness banner / alert-path confirmation)."""
    return alerts.health_snapshot()


@router.get("/{symbol}")
async def detail(symbol: str,
                 report_type: str = Query(None),
                 lookback: int = Query(DEFAULT_LOOKBACK, ge=20, le=520)):
    """Per-cohort net / OI / cot_index / z-score series for one symbol (detail
    chart). `report_type` toggles legacy 3-way vs the asset's TFF/disagg split;
    defaults to the asset-appropriate report."""
    symbol = symbol.upper()
    if symbol not in CONTRACTS:
        raise HTTPException(404, f"unknown symbol '{symbol}'")
    cfg = CONTRACTS[symbol]

    if report_type is None:
        report_type = cfg["report"]
    if report_type not in REPORT_TYPES:
        raise HTTPException(400, f"report_type must be one of {list(REPORT_TYPES)}")

    rows = db.fetch_series(symbol, report_type)
    series = build_series(rows, lookback)

    cohorts_meta = [{
        "key": c,
        "label": COHORT_LABELS[c],
        "color": COHORT_COLORS.get(c, "#888"),
        "primary": c == PRIMARY_COHORT[report_type],
    } for c in COHORTS_BY_REPORT[report_type] if c in series["cohorts"]]

    contract_name = rows[-1]["contract_name"] if rows else None
    return {
        "symbol": symbol,
        "class": cfg["class"],
        "class_label": CLASS_LABELS[cfg["class"]],
        "contract_name": contract_name,
        "report_type": report_type,
        "available_reports": sorted({cfg["report"], "legacy_fut"}),
        "primary_cohort": PRIMARY_COHORT[report_type],
        "lookback": lookback,
        "cohorts_meta": cohorts_meta,
        "series": series,
        "n_weeks": len(series.get("dates", [])),
        # Price overlay is licensed data — off by default until a licensed
        # provider is wired (see guardrails). Frontend keeps the toggle dark.
        "price_overlay": None,
        "price_overlay_enabled": False,
        "disclaimer": DISCLAIMER,
    }
