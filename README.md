# Halal Motion

A self-updating halal momentum system over the combined holdings of the **SPUS**
ETF (S&P 500 Sharia Industry Exclusions) and the **MNZL** ETF (Manzil US Equity)
— roughly 500 Sharia-screened US stocks. On the 1st of every month, GitHub
Actions fetches fresh holdings and prices, re-runs a walk-forward backtest of
eighteen pre-registered ranking variants — nine ranking models (six hand-written
momentum rules, three retrained monthly by machine learning) × stops on/off —
lets an adaptive selector pick the current leader for each sleeve, and
publishes:

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

Two more screens run on top of that, both driven entirely by `config.yaml` so
they're easy to review and extend without touching code:

- **Business-activity screen** (`business_activity_screen` in config,
  `src/halalmo/manual_screen.py`) — a financial-ratio verdict alone can pass a
  company whose core business routinely involves alcohol or gambling revenue
  (cruise operators, casino operators) or runs conventional insurance. This
  screen excludes by GICS sub-industry (sourced from Musaffa's own reported
  classification, same fetch as the compliance check) plus a one-off ticker
  override list, on top of the ratio screen above.
- **BDS / boycott screen** (`bds_screen` in config) — a small, hand-maintained,
  explicitly-sourced list of publicly documented boycott targets. This is a
  separate, non-religious ethical screen, **not a comprehensive database** —
  no clean machine-readable source for this exists, unlike Musaffa's compliance
  data. Every entry cites where the claim comes from; extend it by hand in
  `config.yaml` as you become aware of specific, well-documented cases. Set
  `bds_screen.enabled: false` to turn it off entirely.

Every ticker shown anywhere on the site or in the picks files — current picks,
and all three exclusion lists — carries its **exchange** (from Musaffa's own
data), so a symbol can never be confused with a same-ticker company on a
different market when you look it up directly on musaffa.com.

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
| `data/compliance.csv` | cached Musaffa status/exchange/sub-industry per ticker (not a config key — delete a row to force a re-check) | – |
| `business_activity_screen.excluded_subindustries` | GICS sub-industries hard-excluded regardless of Musaffa's ratio verdict | cruise/casino/insurance lines |
| `business_activity_screen.excluded_tickers` | one-off ticker overrides for the business-activity screen | `[]` |
| `bds_screen.enabled` | turn the boycott screen on/off | `true` |
| `bds_screen.excluded_tickers` | hand-maintained `{ticker, exchange, reason, source}` list | `[SBUX]` |
| `tracks.<name>.n` | number of holdings | 8 / 20 / 25 |
| `tracks.<name>.max_per_sector` | diversification cap | – / 3 / 3 |
| `tracks.<name>.vol_screen_pct` | keep only the calmest X of the universe | – / – / 0.5 |
| `tracks.<name>.require_positive` | hold cash rather than buy falling names | – / – / true |
| `tracks.<name>.stop_min_pct` / `stop_max_pct` | stop band | see table above |
| `cost_bps_per_side` | assumed trading cost | 10 |
| `atr_multiple` | raw stop distance before the band clamps it | 3.0 |
| `selector.window_months` | trailing evaluation window | 24 |
| `selector.switch_margin` | Sortino edge needed to dethrone the incumbent | 0.25 |
| `price_history_start` | history fetched before the first traded month — reaches back far enough that the learned models are past their warm-up by the time trading starts | 2016-01-01 |
| `benchmarks` | comparison ETFs | SPY, QQQ, ^DJI |

The learners' own knobs live in `src/halalmo/ml.py` rather than `config.yaml`,
deliberately: they are part of the pre-registered method, not per-run dials to
be turned until the backtest looks good.

Adding a fourth sleeve is just another block under `tracks:` — the pipeline,
dashboard, picks files and history log all iterate whatever is configured.

## The ranking models

Nine models compete for each sleeve, each with and without stops (18 variants).

**Six written by hand** — 12-1, 6-month and 3-month momentum, SROC over 3 and 6
months, and volatility-adjusted 12-1. Each asserts one fixed opinion about what
a strong trend looks like; none of them is fitted to anything.

**Three learned** (`src/halalmo/ml.py`) — these don't assert a formula, they fit
one. Every month a model is retrained on a 16-feature panel per stock (momentum
over four horizons, smoothed variants, volatility at two speeds and whether it's
expanding, distance below the 52-week high, gap to the 200-day average, biggest
up-day, skew, share of up days) against next month's return:

| Key | Model | What it adds |
|---|---|---|
| `ml_ridge` | ridge regression, alpha by leave-one-out CV | a learned *blend* — which momentum measures have actually been paying, and in what proportion |
| `ml_gbm` | gradient-boosted trees, depth 3 | conditional effects a blend can't express, e.g. 6-month momentum only paying while volatility isn't expanding |
| `ml_ens` | rank consensus of the two | the usual ensemble benefit — two models' mistakes tend not to be the same mistakes |

A learned signal is the one component that could quietly cheat, so the
no-lookahead discipline is explicit and tested:

- features at month-end `t` use only closes up to `t`; the training target for
  month `s` is the realized return from `s` to the next month-end, so a pair is
  only usable once that month-end has passed. Predicting for `t` therefore
  trains on `s < t` — the most recent training target ends exactly on `t`.
- a live run lands a day or two into a new month, so the newest "month-end" is a
  stub; spans shorter than 15 days are dropped from the target rather than
  taught as a month.
- the model is refit from scratch at every month-end. Nothing is fitted once on
  the full sample and applied backwards.
- `tests/test_ml_no_lookahead.py` verifies this rather than asserting it: the
  score for a month is recomputed from a price history with every later day
  physically deleted, and must come out identical.

Overfitting guards on the learners: features are cross-sectionally
rank-transformed each month (the model sees relative standing, so outliers can't
dominate and there's no scale drift), the target is winsorized at ±30%, ridge
alpha is tuned inside the training window only, and the trees are capped at
depth 3 with a large minimum leaf size — deliberately too weak to memorize.
During the 18-month warm-up before enough realized history exists, the learners
fall back to the same pre-registered default the selector uses, plain 12-1
momentum.

## How it stays honest

- **Walk-forward everywhere.** Signals use only data up to each month-end;
  trades execute at the next session's close; the selector only ever sees
  trailing out-of-sample returns.
- **Fixed menu.** The nine models above × stops on/off. The learned ones are
  fitted, but only on data strictly older than the month they rank, and they
  still have to win the same trailing-Sortino contest as everything else —
  with hysteresis, so the system can't churn.
- **Costs modeled.** 10 bps per side on every rebalance and stop exit.
- **Stops are backtested, not decorative.** The same clamped band that appears
  on the site is what the `+stops` variants use in the simulation.
- **Full-period results are shown but never selected on.** The leaderboard
  reports each variant's whole-backtest Sortino, CAGR and drawdown next to the
  trailing window. Only the trailing window drives selection; the rest is
  context, because choosing on whole-sample results is the exact mistake the
  walk-forward design exists to prevent.

## Known limitations (also shown on the site)

- **Survivorship bias:** the backtest applies *today's* SPUS + MNZL holdings to
  the past, so historic results are flattered; treat them as a comparison of
  methods, not a promise. This matters more now that the universe includes
  MNZL's small- and mid-caps. It also flatters the learned models specifically:
  they are trained on a cross-section that only contains survivors.
- **The leaderboard is noisier than it looks.** Six-odd years of monthly returns
  is ~79 observations. Across 18 variants the gap between first and second place
  is usually well inside the noise, so "the selector switched models" is weaker
  evidence than it appears. The hysteresis margin exists to blunt this, not to
  fix it.
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
PYTHONPATH=src pytest tests/ -q                         # no-lookahead tests for the learned signals
```

A live run takes a few minutes: most of it is the price download, plus one
walk-forward training pass (~100 monthly refits × 2 models) shared by all three
learned signals and all three sleeves.

`data/snapshot_prices.parquet` is a committed real-price validation panel
(196 SPUS names + SPY/QQQ/^DJI, dividend/split-adjusted, through 2024-04-24)
so the backtest can be reproduced without any network access. The GitHub
Actions run always uses live yfinance data through the present.
