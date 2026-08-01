# Crescent Momentum

A self-updating halal momentum system over the holdings of the **SPUS** ETF
(S&P 500 Sharia Industry Exclusions). (MNZL support exists in the code but is
switched off in `config.yaml` — the fund only launched in Nov 2025.) On the 1st of every month, GitHub Actions fetches fresh holdings
and prices, re-runs a walk-forward backtest of six pre-registered momentum
models, lets an adaptive selector pick the current leader for each portfolio,
and publishes:

- a **dashboard** on GitHub Pages (picks, stops, equity curves vs SPY/DIA/QQQ,
  full metrics: CAGR, Sharpe, Sortino, max drawdown, Calmar),
- **`docs/picks.md` / `docs/picks.txt`** — paste-ready summaries for a group chat,
- a **GitHub Release** each month, so anyone watching releases gets an email,
- **`history/picks.csv`** — an append-only audit trail of every published pick.

Two portfolios are maintained: **Focused** (top 8, equal weight — more risk)
and **Balanced** (top 20, inverse-volatility weight — more diversified). Both
stay fully invested; suggested **chandelier stops** (3×ATR-22 below the highest
close since entry) are published with every pick as advisory sell levels.

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
| `tracks.focused.n` / `balanced.n` | number of holdings | 8 / 20 |
| `cost_bps_per_side` | assumed trading cost | 10 |
| `atr_multiple` | chandelier stop distance | 3.0 |
| `selector.window_months` | trailing evaluation window | 24 |
| `selector.switch_margin` | Sortino edge needed to dethrone the incumbent | 0.25 |
| `benchmarks` | comparison ETFs | SPY, DIA, QQQ |

## How it stays honest

- **Walk-forward everywhere.** Signals use only data up to each month-end;
  trades execute at the next session's close; the selector only ever sees
  trailing out-of-sample returns.
- **Fixed menu.** Six momentum definitions (12-1, 6m, 3m, SROC-3m, SROC-6m,
  vol-adjusted 12-1) × stops on/off. Nothing is fitted; the "learning" is
  re-ranking a small pre-registered menu, with hysteresis so it can't churn.
- **Costs modeled.** 10 bps per side on every rebalance and stop exit.

## Known limitations (also shown on the site)

- **Survivorship bias:** the backtest applies *today's* SPUS holdings to the
  past, so historic results are flattered; treat them as a comparison of
  methods, not a promise.
- Stops are evaluated on daily closes; ratios use a 0% risk-free rate;
  taxes are ignored; momentum strategies can draw down hard at trend reversals.
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
