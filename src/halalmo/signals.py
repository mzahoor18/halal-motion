"""Ranking signals (all computed strictly from data up to the signal date)
and risk primitives (volatility, ATR) used for weighting and stops.

Signal menu — the fixed 'contestants' the adaptive selector chooses among.

Hand-written definitions, each encoding one fixed opinion about what a strong
trend looks like:
  mom_12_1   classic 12-month momentum skipping the most recent month
  mom_6      6-month total return
  mom_3      3-month total return
  sroc_3     Smoothed Rate of Change: 13-day EMA, 3-month ROC (Schutzman)
  sroc_6     Smoothed Rate of Change: 13-day EMA, 6-month ROC
  ramom_12_1 12-1 momentum divided by realized volatility (risk-adjusted)

Learned definitions, which fit the weighting rather than asserting it (see
`ml.py` for the walk-forward training discipline):
  ml_ridge   ridge regression over a 16-feature trend/risk panel
  ml_gbm     shallow, regularized gradient-boosted trees over the same panel
  ml_ens     rank-consensus of the two

Keeping the menu small and pre-registered is a deliberate overfitting guard:
the selector can only ever pick from these. The learned entries are fitted, but
only ever on data strictly older than the month they rank — and they still have
to earn their place through the same trailing out-of-sample scoring as the rest.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

MIN_VOL = 0.08  # clip annualized vol used in denominators / weights


def momentum(close: pd.DataFrame, lb_days: int, skip_days: int = 0) -> pd.DataFrame:
    return close.shift(skip_days) / close.shift(lb_days) - 1.0


def sroc(close: pd.DataFrame, ema_span: int = 13, roc_days: int = 63) -> pd.DataFrame:
    ema = close.ewm(span=ema_span, adjust=False).mean()
    ema = ema.where(close.notna())  # do not let EMA extend past listing gaps
    return ema / ema.shift(roc_days) - 1.0


def ann_vol(close: pd.DataFrame, window: int = 126) -> pd.DataFrame:
    return close.pct_change(fill_method=None).rolling(window, min_periods=window // 2).std() * np.sqrt(252)


def risk_adj_mom(close: pd.DataFrame, lb_days: int, skip_days: int = 0) -> pd.DataFrame:
    return momentum(close, lb_days, skip_days) / ann_vol(close).clip(lower=MIN_VOL)


def atr(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, n: int = 22) -> pd.DataFrame:
    prev = close.shift(1)
    tr = np.maximum.reduce([
        (high - low).abs().values,
        (high - prev).abs().values,
        (low - prev).abs().values,
    ])
    tr = pd.DataFrame(tr, index=close.index, columns=close.columns)
    return tr.rolling(n, min_periods=n).mean()


SIGNALS = {
    "mom_12_1":   lambda c: momentum(c, 273, 21),   # ~12m lookback, skip ~1m
    "mom_6":      lambda c: momentum(c, 126, 0),
    "mom_3":      lambda c: momentum(c, 63, 0),
    "sroc_3":     lambda c: sroc(c, 13, 63),
    "sroc_6":     lambda c: sroc(c, 13, 126),
    "ramom_12_1": lambda c: risk_adj_mom(c, 273, 21),
}

SIGNAL_LABELS = {
    "mom_12_1": "12-1 momentum",
    "mom_6": "6-month momentum",
    "mom_3": "3-month momentum",
    "sroc_3": "SROC (3-month)",
    "sroc_6": "SROC (6-month)",
    "ramom_12_1": "Risk-adjusted 12-1",
}

# ------------------------------------------------------------------- learned --
# This module owns the menu; `ml.py` owns the fitting (and imports the
# primitives above). The `ml` import is therefore deferred to call time, which
# keeps the dependency one-directional.
LEARNED = ("ml_ridge", "ml_gbm", "ml_ens")

LEARNED_LABELS = {
    "ml_ridge": "Learned blend (ridge)",
    "ml_gbm": "Learned trees (gradient boosting)",
    "ml_ens": "Learned ensemble",
}


def _learned(key: str):
    def _fn(close: pd.DataFrame) -> pd.DataFrame:
        from .ml import ml_scores
        return ml_scores(close)[key]
    return _fn


SIGNALS.update({k: _learned(k) for k in LEARNED})
SIGNAL_LABELS.update(LEARNED_LABELS)


def is_learned(variant_or_signal: str) -> bool:
    """True for a learned signal, with or without a `+stops` suffix."""
    return variant_or_signal.partition("+")[0] in LEARNED
