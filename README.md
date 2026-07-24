# Macro Dashboard

React/FastAPI macro dashboard on Render. Modules: rates regimes, GLI liquidity
composite, BIS credit, multi-asset COT positioning (`backend/cot/README.md`),
and Options Positioning (below).

## Options Positioning module

SPX (`I:SPX`) option-chain positioning from the Massive.com API. Because the
API only serves *today's* open interest, the backend takes a daily chain
snapshot after the US close and persists it to SQLite
(`options_history.db` on the Render disk) — the ΔOI time series, realised
vol, and every percentile are built forward from our own snapshots only.
**Nothing is backfilled from third parties and no metric is ever proxied:
missing inputs render as PENDING/UNAVAILABLE, never as a number.**

### Environment variables

| Var | Meaning |
|---|---|
| `MASSIVE_API_KEY` | Massive.com API key (set in Render env settings; never committed) |
| `OPTIONS_SNAPSHOT_UTC` | Daily snapshot time, UTC `HH:MM` (default `19:30` ≈ 22:30 Riga summer) |
| `OPTIONS_SCHEDULER` | `off` disables the in-process daily scheduler |

### First-time setup (on the server)

1. **Probe the API tier** — gates every feature on what the key actually returns:
   ```bash
   MASSIVE_API_KEY=... python scripts/probe_massive.py
   ```
   Writes `backend/data/massive_capabilities.json` (also shown in the page
   footer). If the plan has no open interest, the page shows a "requires
   Options Starter plan" state instead of empty charts.
2. **Take the first snapshot** — button "Run snapshot now" on the OPTIONS tab,
   or:
   ```bash
   curl -X POST localhost:10000/api/options/snapshot
   ```
3. From then on the in-process scheduler snapshots daily (Mon–Fri) at the
   configured UTC time. Snapshots are idempotent upserts; re-running a day is
   safe.

### What PENDING means

- **ΔOI 1d/5d**: needs 1 / 5 prior *sessions* in our store. Day one shows
  "PENDING — history from <first snapshot date>".
- **Realised vol / VRP**: needs 10/20/30 of our own daily closes.
- **Percentiles** (ATM IV, risk reversal, VRP, P/C ratios): PENDING until
  **60 sessions** accumulate; then shown with the session count.
- **Trade-flow classification**: only if the probe found trades *and* quotes
  on the plan; otherwise "unavailable on current plan" (no tick-test
  approximation).

### Honesty rules (encoded in `backend/options/`)

- Hygiene filters run before any aggregate and their exclusions are
  *reported*: strikes outside ±20% of spot, and stale strikes
  (volume/OI < 0.10 — dead LEAPS OI is not live positioning).
- OI/volume are never presented as what the market is "pricing"; pricing
  claims come from the surface metrics only.
- The dealer-gamma panel is a **[MODEL]**: "Dealers assumed long call OI,
  short put OI. Assumption, not observation." — printed in the panel, with
  the spot-sweep run at dealer-long-call shares a = 1.00/0.75/0.50/0.25 and
  flip levels listed per scenario, never collapsed to one number.
- No holder-type attribution, no motive language, anywhere.

### Tests

```bash
python -m pytest tests/test_options_module.py    # gamma vs Hull values, sweep
                                                 # crossings, filters, PENDING
```
