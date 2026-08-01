"""Ranking signals (all computed strictly from data up to the signal date)
and risk primitives (volatility, ATR) used for weighting and stops.

Signal menu — the fixed 'contestants' the adaptive selector chooses among:
  mom_12_1   classic 12-month momentum skipping the most recent month
  mom_6      6-month total return
  mom_3      3-month total return
  sroc_3     Smoothed Rate of Change: 13-day EMA, 3-month ROC (Schutzman)
  sroc_6     Smoothed Rate of Change: 13-day EMA, 6-month ROC
  ramom_12_1 12-1 momentum divided by realized volatility (risk-adjusted)

Keeping the menu small and pre-registered is a deliberate overfitting guard:
the selector can only ever pick from these; nothing is fitted per-stock.
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
