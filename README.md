# Halal Motion

A self-updating halal momentum system over the combined holdings of the **SPUS**
ETF (S&P 500 Sharia Industry Exclusions) and the **MNZL** ETF (Manzil US Equity)
— roughly 500 Sharia-screened US stocks. On the 1st of every month, GitHub
Actions fetches fresh holdings and prices, re-runs a walk-forward backtest of
twelve pre-registered momentum variants, lets an adaptive selector pick the
current leader for each sleeve, and publishes:

- a **dashboard** on GitHub Pages (picks, sell levels, equity curves vs SPY/DIA/QQQ,
  full metrics: CAGR, Sharpe, Sortino, max drawdown, Calmar — every financial term
  on the page explains itself on hover),
- **`docs/picks.md` / `docs/picks.txt`** — paste-ready summaries for a group chat,
- a **GitHub Release** each month, so anyone watching releases gets an email,
- **`history/picks.csv`** — an append-only audit trail of every published pick.

## Compliance screen

SPUS and MNZL each run their own Shariah board's methodology, and holdings can
drift out of compliance between a fund's own rebalances — or simply read
differently under another screen's ratios. Before any backtest or ranking runs,
every ticker in the combined universe is checked a second time against
**Musaffa**'s AAOIFI-based screen (`src/halalmo/compliance.py`, cached in
`data/compliance.csv`, refreshed incrementally like the sector map). Only
`COMPLIANT` names stay in the tradeable universe — `QUESTIONABLE` (doubtful,
e.g. borderline debt ratios) and anything Musaffa doesn't cover are dropped,
not guessed at. A live run currently excludes roughly 30% of the raw SPUS+MNZL
union on this basis; the excluded tickers and reasons are published on the
dashboard (`Compliance screen` panel) and at the top of `docs/picks.md`.

## The three sleeves

| Sleeve | Holdings | Sector cap | Extra screens | Stop band |
|---|---|---|---|---|
| **Aggressive** | 8 | none | — | 10–15% |
| **Balanced** | 20 | max 3 per sector | — | 8–12% |
| **Conservative** | 25 | max 3 per sector | calmest half of the universe only; cash instead of negative-momentum picks | 5–8% |

All three size positions by inverse volatility. Every sleeve publishes a
suggested **trailing sell level** per holding: the raw distance is 3×ATR(22)
below the highest close since entry, then **clamped into that sleeve's band, so
no stop is ever wider than 15%**. The bracketed percentage next to each sell
price is how far the stock must fall *from today's close* to trigger it — the
full band for a fresh pick, less for a name that has already pulled back.

## 10-minute setup

1. Create a new GitHub repository (public is fine) and push this folder to it:

   ```bash
   git init && git add -A && git commit -m "initial"
   git branch -M main
   git remote add origin https://github.com/YOURNAME/YOURREPO.git
   git push -u origin main
   ```

2. In the repo: **Settings → Pages → Build and deployment → Source: GitHub Actions.**

3. Go to the **Actions** tab, enable workflows if prompted, open
   **monthly-refresh**, and press **Run workflow** once. The first run fetches
   real holdings + prices, backtests from 2020, and deploys the site
   (usually 5–10 minutes).

4. Your dashboard lives at `https://YOURNAME.github.io/YOURREPO/`. Done — it
   refreshes itself on the 1st of every month.

## Sharing with friends (all free)

- Send them the Pages link — it's mobile-friendly.
- Tell them to hit **Watch → Custom → Releases** on the repo: GitHub emails
  them the full picks table every month automatically.
- Or just paste `docs/picks.txt` into the group chat each month.

## Tuning knobs (`config.yaml`)

| Key | Meaning | Default |
|---|---|---|
| `funds` | universe sources | `[spus, mnzl]` |
| `data/compliance.csv` | cached Musaffa status per ticker (not a config key — delete a row to force a re-check) | – |
| `tracks.<name>.n` | number of holdings | 8 / 20 / 25 |
| `tracks.<name>.max_per_sector` | diversification cap | – / 3 / 3 |
| `tracks.<name>.vol_screen_pct` | keep only the calmest X of the universe | – / – / 0.5 |
| `tracks.<name>.require_positive` | hold cash rather than buy falling names | – / – / true |
| `tracks.<name>.stop_min_pct` / `stop_max_pct` | stop band | see table above |
| `cost_bps_per_side` | assumed trading cost | 10 |
| `atr_multiple` | raw stop distance before the band clamps it | 3.0 |
| `selector.window_months` | trailing evaluation window | 24 |
| `selector.switch_margin` | Sortino edge needed to dethrone the incumbent | 0.25 |
| `benchmarks` | comparison ETFs | SPY, QQQ, ^DJI |

Adding a fourth sleeve is just another block under `tracks:` — the pipeline,
dashboard, picks files and history log all iterate whatever is configured.

## How it stays honest

- **Walk-forward everywhere.** Signals use only data up to each month-end;
  trades execute at the next session's close; the selector only ever sees
  trailing out-of-sample returns.
- **Fixed menu.** Six momentum definitions (12-1, 6m, 3m, SROC-3m, SROC-6m,
  vol-adjusted 12-1) × stops on/off. Nothing is fitted; the "learning" is
  re-ranking a small pre-registered menu, with hysteresis so it can't churn.
- **Costs modeled.** 10 bps per side on every rebalance and stop exit.
- **Stops are backtested, not decorative.** The same clamped band that appears
  on the site is what the `+stops` variants use in the simulation.

## Known limitations (also shown on the site)

- **Survivorship bias:** the backtest applies *today's* SPUS + MNZL holdings to
  the past, so historic results are flattered; treat them as a comparison of
  methods, not a promise. This matters more now that the universe includes
  MNZL's small- and mid-caps.
- Stops are evaluated on daily closes; ratios use a 0% risk-free rate;
  taxes are ignored; momentum strategies can draw down hard at trend reversals.
- Sector labels come from Yahoo Finance's own classification, cached in
  `data/sectors.csv`.
- **This is an educational project, not investment advice.**

## Local development

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m halalmo.run                    # live data via yfinance (production path)
PYTHONPATH=src python -m halalmo.run --source snapshot  # committed real-price panel (Jun 2017 – Apr 2024)
PYTHONPATH=src python -m halalmo.run --source synthetic # plumbing test, fake prices
```

`data/snapshot_prices.parquet` is a committed real-price validation panel
(196 SPUS names + SPY/QQQ/^DJI, dividend/split-adjusted, through 2024-04-24)
so the backtest can be reproduced without any network access. The GitHub
Actions run always uses live yfinance data through the present.
