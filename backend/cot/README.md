# Multi-Asset COT Positioning Module

Cross-asset CFTC Commitment-of-Traders positioning for the macro dashboard.
Pulls free, public-domain CFTC data for indices, FX, rates and commodities;
normalises positioning to a 0–100 COT index; serves a cross-asset positioning
heatmap (signature) plus a per-asset detail chart; auto-updates weekly.

Built to `cot_module_build_brief.md`. The financial logic (report-type mapping,
cohort selection, COT-index transform, validation gates) is implemented exactly
as specified and validated against `backend/data/cot_nq_processed.csv`
(2026-06-16 NQ legacy nets tie out: Non-Comm −8,908 / Comm +4,087 / Non-Rept
+4,821; the computed COT index reproduces the reference to < 1e-6).

## Layout
```
backend/cot/
  config.py     CONTRACTS universe, report-type rule, cohort keys/colors, column-resolution tokens
  db.py         SQLAlchemy schema (§6 DDL). Postgres via DATABASE_URL; SQLite fallback on the Render disk
  transform.py  net_position, cot_index (156w stochastic), z-score, cohort normalisation, read view
  validate.py   §5 gates: sum-to-zero, tie-out, freshness, COT-index warmup — all fail loud via alerts
  fetcher.py    pycot incremental + cftc-cot/direct-CFTC backfill wrappers; name resolution; alert-wrapped
  alerts.py     failure sink -> /api/cot/health (+ optional COT_ALERT_WEBHOOK)
  api.py        /api/cot/{universe,heatmap,{symbol},health}
backend/scripts/
  cot_resolve_names.py   PRE-BACKFILL CHECKPOINT — resolve CONTRACTS -> verbatim CFTC names, review before backfill
  cot_backfill.py        one-time historical backfill (~2010 -> present) + gates
  cot_weekly_update.py    incremental weekly upsert (Render cron)
frontend/src/components/
  COTModule.jsx       container (heatmap -> detail) + health strip
  COTHeatmap.jsx      signature cross-asset heatmap
  COTDetailChart.jsx  canvas port of cot_nq_chart.html (report toggle, off-by-default price overlay)
```

## Operating sequence
1. `python -m backend.scripts.cot_resolve_names`  ← review the resolved names first.
2. `python -m backend.scripts.cot_backfill`        ← one-time ~2010→present load + gates.
3. Weekly cron runs `cot_weekly_update` (render.yaml: Fri 22:00 UTC, retry Sat 14:00 UTC).

Requires egress to `www.cftc.gov` (allowed on Render). The COT index / z-score
are computed on read, never stored denormalised.

## Guardrails honoured
- **Package fragility:** every fetch is try/except + alert-routed, with a
  documented direct-CFTC ZIP fallback (`fetcher.fetch_raw_direct`).
- **Price-data licensing:** COT is public-domain. The price overlay is pluggable
  and **off by default** — the detail endpoint returns `price_overlay: null` and
  the chart toggle is disabled until a licensed feed is wired.
- **Inform, never advise:** every API payload and both views carry a standing
  non-advisory disclaimer (MiFID II boundary). No per-asset buy/sell calls.
- Raw `contract_name` is preserved verbatim on every row.
