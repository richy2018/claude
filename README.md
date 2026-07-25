# Macro Dashboard

React/FastAPI macro dashboard on Render. Modules: rates regimes, GLI liquidity
composite, BIS credit, multi-asset COT positioning (`backend/cot/README.md`),
and Options Positioning (below).

## Options Positioning module

SPX (`I:SPX`) option-chain positioning from the Massive.com API. The backend
takes a daily chain snapshot after the US close and persists it to SQLite
(`options_history.db` on the Render disk). **No metric is ever proxied: missing
inputs render as PENDING/UNAVAILABLE, never as a number.**

What is historical vs forward-only (the honesty boundary):

| Series | Source | Historical? |
|---|---|---|
| Underlying level / **realised vol / VRP** | ^GSPC (Yahoo), 5Y seeded | yes — real index series, same vendor as spot |
| **Surface IV** (ATM 30d, 25Δ RR) + their percentiles | live vendor IV *plus* 2Y **reconstructed** from S3 flat-file closes (`scripts/backfill_surface.py`), rows labelled `source` | yes — reconstructed rows always labelled |
| **ΔOI** 1d/5d, P/C percentiles | our own daily snapshots | **forward-only, permanently** — OPRA aggregates (REST *and* S3 flat files) carry no open interest, so there is no historical source; never approximated from volume |

Reconstructed values are always labelled `reconstructed` and are never blended
with live vendor IV without the `source` column; a validation gate aborts the
backfill if reconstructed and live ATM IV disagree by more than 1.0 vol point.

### Environment variables

| Var | Meaning |
|---|---|
| `MASSIVE_API_KEY` | Massive.com REST API key (set in Render env settings; never committed) |
| `MASSIVE_S3_KEY_ID` / `MASSIVE_S3_SECRET` | Flat-file S3 credentials (Massive dashboard → Accessing Flat Files) — needed only for the 2Y surface backfill |
| `MASSIVE_S3_ENDPOINT` / `MASSIVE_S3_BUCKET` | Override S3 endpoint/bucket (default `https://files.massive.com` / `flatfiles`) |
| `OPTIONS_SNAPSHOT_UTC` | Daily snapshot time, UTC `HH:MM` (default `19:30` ≈ 22:30 Riga summer) |
| `OPTIONS_SCHEDULER` | `off` disables the in-process daily scheduler |

### First-time setup (on the server)

1. **Probe the API tier** — gates every feature on what the key actually
   returns, snapshot tier *and* historical/flat-file reach:
   ```bash
   MASSIVE_API_KEY=... python scripts/probe_massive.py
   ```
   Writes the capability report to the persistent data dir (survives deploys)
   and prints it. The `history` section decides §3/§4: `historical_aggregates`
   gates surface reconstruction; `oi_in_history` gates ΔOI backfill. The app
   also runs this probe best-effort on startup (background) so the banner
   resolves without a manual step.
2. **Take the first snapshot** — button "Run snapshot now" on the OPTIONS tab,
   or `curl -X POST localhost:10000/api/options/snapshot`. The first run also
   seeds 5Y of ^GSPC daily closes, so realised vol / VRP are live immediately.
3. **Reconstruct 2Y of surface history** from the S3 flat files so ATM IV / RR /
   VRP percentiles go live now instead of after 60 forward sessions. Set the S3
   credentials (dashboard → *Accessing Flat Files*) first:
   ```bash
   export MASSIVE_S3_KEY_ID=...  MASSIVE_S3_SECRET=...
   python scripts/backfill_surface.py --dry-run --max-days 20   # preview a slice
   python scripts/backfill_surface.py                           # full 2Y, resumable
   ```
   Streams one `us_options_opra/day_aggs_v1/YYYY/MM/DATE.csv.gz` per trading day,
   keeps SPX-index rows (roots SPX/SPXW) in the 20–45 DTE and ±12% strike band,
   inverts BS→IV, interpolates to 30d. Idempotent; refuses to run without S3
   credentials; validation gate aborts on reconstructed-vs-live drift > 1.0 vol pt.
4. From then on the in-process scheduler snapshots daily (Mon–Fri) at the
   configured UTC time. Snapshots are idempotent upserts; re-running a day is
   safe. A **trading-day guard** in the snapshot job (not just the scheduler)
   skips weekends outright and skips a weekday whose spot is identical to the
   last stored close (a holiday re-serve of the prior session), so a
   non-trading-day "Run snapshot now" can't photograph the previous session
   under a new date. Any such duplicate already stored is auto-pruned at the
   start of the next snapshot (or run `db.prune_duplicate_sessions()` manually).

### What PENDING means

- **ΔOI 1d/5d**: needs 1 / 5 prior *sessions* in our store. Day one shows
  "PENDING — history from <first snapshot date>". **Forward-only, permanently** —
  OPRA aggregates carry no open interest (confirmed for REST and S3 flat files),
  so ΔOI has no historical source and is never approximated from volume.
- **Realised vol / VRP**: live immediately — 5Y of ^GSPC closes is seeded on the
  first snapshot (no longer waits to accumulate our own closes).
- **Surface percentiles** (ATM IV, risk reversal, VRP): live once the 2Y
  reconstruction is run; the pricing card shows a "history: N reconstructed +
  M live" note. Without the backfill they stay PENDING until 60 pooled sessions.
- **P/C ratio percentiles**: forward-only — PENDING until 60 of our own sessions
  (positioning is never reconstructed).
- **Trade-flow classification**: only if the probe found trades *and* quotes
  on the plan; otherwise "unavailable on current plan" (no tick-test
  approximation).

### Surface IV reconstruction constants (Black-Scholes inversion)

`scripts/backfill_surface.py` inverts each contract's daily close to an implied
vol (`backend/options/iv_inversion.py`), then interpolates to a 30d constant
maturity linear in total variance (σ²·T). Constants match the gamma model:

- `r = 0.04`, `q = 0.015` (RISK_FREE / DIV_YIELD)
- contracts used per day: **20–45 DTE**; target maturity **30d**
- inversions outside **3%–150%** vol, or priced below intrinsic, are discarded
- lookback **2Y**; validation gate aborts if reconstructed vs live ATM IV
  mean-absolute-difference **> 1.0 vol point**

### Volatility surface

`GET /api/options/surface` builds a delta × tenor constant-maturity IV grid plus
per-expiry smiles from the chain rows already stored (vendor `iv`/`delta`) — no
new API access, no backfill. It reads RAW rows (not the ±20%/stale positioning
filter, which would delete the wings) and applies an IV-quality filter whose
exclusions are counted. The grid interpolates linear in total variance (its
ATM/30d cell equals the "ATM IV 30D" card); the delta axis interpolates in
|delta| with no extrapolation past the observed range. Calendar (total-variance
monotonicity) and butterfly (price convexity) no-arb checks run and their
violations are **reported, never smoothed**. Limits stated in the payload:
IV is vendor-computed from last prints (no quotes on plan), r/q are held constant
so expiries past 400d are excluded, and it is one EOD snapshot (no intraday).

### Spot sourcing

The chain snapshot embeds the underlying index value only on plans with an
indices entitlement (probe field `underlying_price`). On chain-only plans the
snapshot falls back to the S&P 500 index itself (`^GSPC` via yfinance — the
dashboard's existing equity source): the same underlying observed at a
different vendor, not a proxy or model estimate. The origin is recorded as
`spot_source` in the daily payload and shown in the panel header whenever it
isn't chain-embedded. If both sources fail, the day renders as an honest
"empty" — spot is never estimated from the chain.

Note: the capability report is written to the persistent data dir
(`/opt/render/data` on Render) so it survives deploys, and the app re-runs the
probe best-effort on startup if the report is missing or >20h old — so the
"unprobed" banner resolves on its own after a deploy.

### Honesty rules (encoded in `backend/options/`)

- Hygiene filters run before any aggregate and their exclusions are
  *reported*: strikes outside ±20% of spot, and stale strikes
  (volume/OI < 0.10 — dead LEAPS OI is not live positioning).
- OI/volume are never presented as what the market is "pricing"; pricing
  claims come from the surface metrics only.
- The dealer-gamma panel is a **[MODEL]**: "Dealers assumed long call OI,
  short put OI. Assumption, not observation." — printed in the panel, with
  the spot-sweep run at dealer-long-call shares a = 1.00/0.75/0.50/0.25 over
  ±25% and
  flip levels listed per scenario, never collapsed to one number.
- No holder-type attribution, no motive language, anywhere.

### Tests

```bash
python -m pytest tests/test_options_module.py    # gamma vs Hull, sweep crossings,
                                                 # filters, PENDING, BS IV inversion
                                                 # round-trip, surface reconstruction,
                                                 # validation gate, pooled percentiles
```
