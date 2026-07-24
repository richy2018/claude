"""Options Positioning module (Massive.com API, I:SPX).

Daily chain snapshots persisted to SQLite build the OI time series the API
itself doesn't provide (it only serves *today's* OI — positioning analysis
needs ΔOI). Metrics are computed on read from the store.

DELIBERATELY PANDAS-FREE throughout (stdlib sqlite3/csv/math + requests):
the snapshot job and metrics run in-process next to the live dashboard on a
512 MB instance — same constraint that shaped the COT streaming backfill.

Honesty rules (enforced in code, not just UI):
  - No metric is ever silently fabricated or proxied. Missing = labelled
    missing ("PENDING — history from <first snapshot date>").
  - OI/volume are positioning facts, never "what the market is pricing" —
    pricing claims come from the surface metrics only.
  - The dealer-gamma panel is a [MODEL]: its inventory assumption is printed
    in the panel verbatim, and the a-share sweep shows how much the
    assumption drives the output.
  - No holder-type attribution, no motive language, anywhere.
"""
