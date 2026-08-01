"""Adaptive strategy selection with overfitting guards.

Each month the selector looks at the trailing `window_months` of *out-of-sample*
monthly returns for every variant in the fixed menu and holds the variant with
the best trailing Sortino. Guards:

  * warm-up: before `min_months` of history exist, hold the pre-registered
    default (12-1 momentum, no stops) — the academic standard, chosen a priori
  * hysteresis: a challenger must beat the incumbent's trailing Sortino by
    `switch_margin` to take over, preventing noise-chasing churn
  * fixed menu: nothing is fitted; the model can only re-rank pre-registered
    strategies, so degrees of freedom stay tiny relative to the data

The meta track record is the compounded return of whichever variant was live
each month — i.e., exactly what a disciplined investor following the system
would have earned (before slippage beyond the modeled costs).
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd


def sortino_m(monthly: pd.Series) -> float:
    r = monthly.dropna()
    if len(r) < 6:
        return float("-inf")
    downside = r[r < 0]
    dd = downside.std(ddof=0)
    if dd is None or not np.isfinite(dd) or dd < 1e-9:
        dd = 1e-9
    return float(r.mean() * 12 / (dd * np.sqrt(12)))


@dataclass
class SelectorOutput:
    meta_monthly: pd.Series          # PeriodIndex -> return of the live variant
    selections: pd.Series            # PeriodIndex -> variant name live that month
    live_variant: str                # variant selected for the upcoming month
    leaderboard: pd.DataFrame        # trailing scores per variant, latest window


def walk_forward(variant_monthly: pd.DataFrame, window_months: int, min_months: int,
                 switch_margin: float, default_variant: str) -> SelectorOutput:
    months = variant_monthly.index
    incumbent = default_variant if default_variant in variant_monthly.columns \
        else variant_monthly.columns[0]
    meta, sel = [], []
    for i, m in enumerate(months):
        hist = variant_monthly.iloc[max(0, i - window_months):i]
        if len(hist) >= min_months:
            scores = hist.apply(sortino_m)
            best = scores.idxmax()
            inc_score = scores.get(incumbent, float("-inf"))
            if scores[best] > inc_score + switch_margin:
                incumbent = best
        sel.append(incumbent)
        meta.append(variant_monthly.at[m, incumbent])

    # selection for the upcoming (not yet traded) month
    hist = variant_monthly.iloc[-window_months:]
    live = incumbent
    lb = None
    if len(hist) >= min_months:
        scores = hist.apply(sortino_m).sort_values(ascending=False)
        if scores.iloc[0] > scores.get(incumbent, float("-inf")) + switch_margin:
            live = scores.index[0]
        lb = scores.rename("trailing_sortino").to_frame()
    else:
        lb = pd.DataFrame({"trailing_sortino": {incumbent: float("nan")}})
    lb["live"] = [ix == live for ix in lb.index]

    return SelectorOutput(
        meta_monthly=pd.Series(meta, index=months),
        selections=pd.Series(sel, index=months),
        live_variant=live,
        leaderboard=lb.reset_index().rename(columns={"index": "variant"}),
    )
