# Backend Data Feeds

Manually-refreshed / cached data stores used by the dashboard.

## FINRA Margin Debt (leverage/sentiment overlay)

- **What:** Year-over-year % change of FINRA customer margin debt — "Debit
  Balances in Customers' Securities Margin Accounts" (monthly, USD millions).
  A risk-appetite / leverage / sentiment **overlay**.
- **NOT a GLI factor.** It is deliberately excluded from the 5-factor GLI
  production composite (it is coincident-to-lagging and would contaminate the
  liquidity signal). It lives beside the GLI as a monitoring analytic, like the
  Dollar Stress overlay.
- **Source:** [FINRA Margin Statistics](https://www.finra.org/investors/learn-to-invest/advanced-investing/margin-statistics).
  FINRA provides **no API** — only a downloadable xlsx beginning January 1997.
- **Store:** `backend/data/margin_debt.csv` (tidy: `date,margin_debt_usd_m`).
  The backend reads this CSV; it never live-fetches FINRA per request (Render
  reliability).

### Monthly refresh

FINRA publishes month *M*'s figure in the **third week of month M+1**. After each
release:

```bash
# Download + parse the FINRA xlsx, rewrite margin_debt.csv
python backend/scripts/update_margin_debt.py

# (optional) override the xlsx URL if FINRA moves it
python backend/scripts/update_margin_debt.py --url https://www.finra.org/.../margin-statistics.xlsx

# regenerate the deterministic placeholder seed (non-authoritative)
python backend/scripts/update_margin_debt.py --seed
```

Then commit the updated `margin_debt.csv`. The script is robust to FINRA
column/format drift: it locates the debit-balance column by header keywords and
**fails loudly** if the schema changes, rather than writing garbage. The CSV's
first `# source:` line records provenance; if it contains "SEED"/"PLACEHOLDER"
the API/panel flags the data as non-authoritative.

### Publication-lag discipline (no lookahead)

Every **point-in-time** computation (expanding-window z-score, percentile,
regime classification, forward-return-by-regime analytics) lags the series by
its ~1-month publication delay (`LAG_MONTHS = 1`). The "latest" display shows
the freshest reference month but labels its publication ("as of") date. This is
the same anti-lookahead discipline used for the BIS quarterly Qty factor.

### Regime bands (configurable; defaults in `margin_debt.py`)

| Regime         | YoY%        |
| -------------- | ----------- |
| Froth          | `> +30%`    |
| Neutral        | `0% .. +30%`|
| Contraction    | `< 0%`      |
| Capitulation   | `< -20%`    |

- **Endpoint:** `GET /api/gli/margin-debt` → `{ series, latest, thresholds, meta, analytics }`.
- **Panel:** Liquidity tab → *GLI Signal & Analytics* → "Margin Debt (Sentiment Overlay)".

## Related manually-maintained stores

- **Dollar Stress** (`dollar_stress.py`): cross-currency basis swaps from a
  user-maintained gist. See `GIST_URL` in that module.
- **TIC Major Foreign Holders** (`tic_parser.py`): US Treasury holdings;
  `SUPPLEMENTAL_DATA` holds months not yet in the main TIC text file.
