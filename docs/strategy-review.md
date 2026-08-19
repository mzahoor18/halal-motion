# Strategy review — benchmarking the picks & searching for a better method

_Prepared 2026-08-19. Educational analysis, not investment advice._

This answers two questions: **are the sleeve changes we just made supported by
evidence**, and **is there a better picking strategy than the current adaptive
selector?** It accompanies the new *realized picks* tracker on the dashboard,
which measures how the actually-published picks have done out of sample.

## How the tests were run (and their limits)

- **Panel:** the committed real-price snapshot — 194 names + SPY/QQQ/^DJI,
  dividend/split-adjusted, **Jun 2017 – Apr 2024**, traded from Jun 2018.
- **Survivorship bias:** it applies today's holdings to the past, so absolute
  numbers are flattered. Read everything below as a *comparison of methods*, not
  a promised return — the same caveat the site already makes.
- **Small sample:** ~70 traded months. Differences inside ~0.2 Sortino are noise.
- **Menu:** the six hand-written signals × stops on/off, with the live
  walk-forward selector. Learned signals were left out for speed; they don't bear
  on the counts/stops question.

## Q1 & Q2 — do the new sleeve settings help? (adaptive selector each)

New = **5 / 10 / 15** holdings and stops **8–10 / 6–8 / 5–7%**.
Old = 8 / 20 / 25 and stops 10–15 / 8–12 / 5–8%.

| Sleeve | | CAGR | Sharpe | Sortino | Max DD |
|---|---|---|---|---|---|
| Aggressive | old | 23.6% | 0.95 | 1.88 | −23.6% |
| Aggressive | **new** | **29.9%** | **1.15** | **2.11** | −26.3% |
| Balanced | old | 20.1% | 1.11 | 1.93 | −20.4% |
| Balanced | **new** | **22.0%** | 1.05 | **2.11** | −23.7% |
| Conservative | old | 8.9% | 0.77 | 1.24 | −20.2% |
| Conservative | **new** | **10.4%** | 0.74 | **1.34** | −20.3% |

_Benchmarks over the same window: SPY 12.8% CAGR / 1.01 Sortino, QQQ 17.3% / 1.39._

**Read:** concentrating into fewer names **raised return and downside-adjusted
return (Sortino) in every sleeve**. The cost is a **somewhat deeper worst-case
drawdown** on the two riskier sleeves (~+3pp) — the expected price of holding
fewer names. Tighter stops did *not* reduce max drawdown (monthly drawdowns come
mostly from within-month moves the stops don't catch), but they didn't hurt
returns either. Net: the changes you asked for are supported, with a clearly
understood risk tradeoff. Nothing here argues for reverting them.

## Q3 — is the adaptive selector worth keeping?

| Sleeve (new settings) | CAGR | Sortino | Max DD |
|---|---|---|---|
| Aggressive — **adaptive (live)** | **29.9%** | 2.11 | −26.3% |
| Aggressive — fixed 12-1 + stops | 17.2% | 1.51 | −31.9% |
| Aggressive — best-in-hindsight | 26.3% | 2.41 | −24.3% |
| Balanced — **adaptive (live)** | 22.0% | 2.11 | −23.7% |
| Balanced — fixed 12-1 + stops | 13.0% | 1.57 | −23.8% |
| Conservative — **adaptive (live)** | 10.4% | 1.34 | −20.3% |
| Conservative — fixed 12-1 + stops | 10.0% | 1.30 | −17.5% |

**Read:** the adaptive selector beats a fixed 12-1 rule comfortably and sits
close to the (unachievable) best-in-hindsight ceiling. **Keep it.** Two things I
tried that did *not* help enough to adopt:

- **Changing the warm-up default** (12-1 → volatility-adjusted 12-1): mixed and
  small — helped balanced, hurt aggressive. No robust gain. Leave as is.
- **Replacing selection with a fixed rank-ensemble** of all six signals: lower
  CAGR on the two aggressive sleeves. Not a general win.

## The one candidate worth considering

A **rank-ensemble** (average cross-sectional rank of the six hand signals) run
**only on the conservative sleeve**, with stops:

| Conservative (new settings) | CAGR | Sharpe | Sortino | Max DD |
|---|---|---|---|---|
| adaptive selector (current) | 10.4% | 0.74 | 1.34 | −20.3% |
| **rank-ensemble + stops** | **12.6%** | **0.88** | **1.79** | **−13.0%** |

On this panel the ensemble **Pareto-dominates** for the low-risk sleeve: higher
return *and* higher Sortino *and* a materially shallower drawdown. It makes
intuitive sense — for a sleeve whose whole job is a smooth ride, a steady
consensus of many signals beats chasing whichever single signal won the last
24 months. The clean way to adopt it is to **add the ensemble as a 10th signal
in the menu** (`src/halalmo/signals.py`) so the walk-forward selector can pick it
when it earns its place — this *expands* the menu rather than overriding
anything, and stays inside the existing no-lookahead discipline.

## Recommendation

1. **Keep the new sleeve settings** (5/10/15, 5–10% stops) — evidence-supported.
2. **Keep the adaptive selector** — it's near the hindsight ceiling.
3. **Consider adding the hand-signal rank-ensemble to the model menu**, mainly
   for the conservative sleeve. It's a small, low-risk, principled change — but
   it rests on one survivorship-biased panel, so I'd **let the new realized-picks
   tracker accrue two or three months of live evidence first**, then decide.

I have **not** changed the ranking/selection method — that's the one piece I'm
bringing to you for a decision before touching the live path. Say the word and
I'll add the ensemble signal (menu-only, selector still chooses).

---
_Reproduce: `scratchpad/experiment.py` (Q1–Q3) and `experiment2.py` (candidates)._
