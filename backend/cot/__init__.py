"""Multi-asset COT (Commitment of Traders) positioning module.

Cross-asset CFTC positioning: pulls free, public-domain CFTC data for
indices, FX, rates and commodities; normalises positioning to a 0-100 COT
index; serves a cross-asset positioning heatmap plus per-asset detail charts.

See cot_module_build_brief.md for the financial logic (report-type mapping,
cohort selection, COT-index transform, validation gates) — implemented as
specified, not reinvented.
"""
