"""Learned cross-sectional ranking signals.

The hand-written signals in `signals.py` each hard-code one opinion about what
"strong trend" means (12-1 return, 3-month return, smoothed ROC, ...). This
module instead *learns* the weighting from the data: every month it fits a
model that maps a panel of trend/risk features to next month's return, and
uses the fitted model's prediction as the ranking score. Three learners join
the menu as ordinary contestants:

  ml_ridge   ridge regression (RidgeCV, leave-one-out alpha) — a linear blend
             of the features, i.e. "which momentum definitions have actually
             been paying, and in what proportion"
  ml_gbm     gradient-boosted trees (shallow, heavily regularized) — can find
             interactions a linear blend cannot, e.g. "6-month momentum only
             works when short-term volatility is not expanding"
  ml_ens     the equal-weight blend of the two, ranked cross-sectionally

They do NOT get to bypass any of the honesty machinery. They are added to the
same fixed, pre-registered menu, run through the same walk-forward backtest,
and are chosen (or not) by the same trailing-Sortino selector with hysteresis.

No-lookahead discipline, which is the whole ballgame for a learned signal:

  * features at month-end `t` use only closes up to and including `t`
  * the training target for month-end `s` is the realized return from `s` to
    the next month-end, so a pair (s, y_s) is only usable once that next
    month-end has passed
  * predicting for `t` therefore trains on pairs with s < t only — the most
    recent training target ends exactly at `t`, never after it
  * the model is refit from scratch at every month-end (expanding window);
    nothing is fitted once on the full sample and applied backwards

Overfitting guards specific to the learners:

  * features are cross-sectionally rank-transformed to [-1, 1] each month, so
    the model sees relative standing rather than levels — no scale drift, and
    outliers cannot dominate the fit
  * the target is winsorized at +/-30% monthly
  * ridge alpha is chosen by leave-one-out CV *inside the training window only*
  * the tree model is capped at depth 3 with a large minimum leaf size and L2
    regularization — it is deliberately too weak to memorize
  * a warm-up period (`MIN_TRAIN_MONTHS`) where there is not yet enough
    realized history falls back to the same pre-registered default the selector
    uses during its own warm-up: plain 12-1 momentum

Because the target is the raw (winsorized) forward return rather than a rank,
a prediction's *sign* is meaningful — "this name is expected to rise" — which
is what the Conservative sleeve's `require_positive` cash rule needs.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .signals import LEARNED, momentum, sroc, ann_vol, MIN_VOL

log = logging.getLogger("halalmo.ml")

MIN_TRAIN_MONTHS = 18      # realized (feature, forward-return) months before a fit is trusted
TARGET_CLIP = 0.30         # winsorize the monthly training target at +/-30%
MIN_TARGET_SPAN = pd.Timedelta(days=15)   # shortest span that counts as a "month" of target
MIN_NAMES_PER_MONTH = 30   # skip months too thin to carry cross-sectional information
RIDGE_ALPHAS = np.logspace(-2.0, 3.0, 12)


# ------------------------------------------------------------------ features --
def _rolling_skew(rets: pd.DataFrame, window: int) -> pd.DataFrame:
    return rets.rolling(window, min_periods=window // 2).skew()


def feature_frames(close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Daily-indexed feature panel. Every value at row `d` uses closes <= `d`."""
    rets = close.pct_change(fill_method=None)
    vol126 = ann_vol(close, 126)
    vol21 = ann_vol(close, 21)
    sma200 = close.rolling(200, min_periods=120).mean()
    hi252 = close.rolling(252, min_periods=150).max()
    r12_1 = momentum(close, 273, 21)
    return {
        # trend, several horizons — the learner decides how to weigh them
        "r1": momentum(close, 21, 0),
        "r3": momentum(close, 63, 0),
        "r6": momentum(close, 126, 0),
        "r12_1": r12_1,
        "sroc3": sroc(close, 13, 63),
        "sroc6": sroc(close, 13, 126),
        "ramom": r12_1 / vol126.clip(lower=MIN_VOL),
        "accel": momentum(close, 63, 0) - momentum(close, 126, 0),
        # risk / regime
        "vol21": vol21,
        "vol126": vol126,
        "volratio": vol21 / vol126.clip(lower=MIN_VOL),
        # position within the stock's own range
        "dist52": close / hi252 - 1.0,
        "sma200gap": close / sma200 - 1.0,
        # distribution shape — lottery-like names behave differently
        "maxret21": rets.rolling(21, min_periods=15).max(),
        "skew126": _rolling_skew(rets, 126),
        "updays126": (rets > 0).where(rets.notna()).rolling(126, min_periods=63).mean(),
    }


def month_end_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last trading day of each month present in `index`."""
    per = index.to_period("M")
    keep = np.append(per[1:] != per[:-1], True)
    return index[keep]


def _cs_rank(row: pd.Series) -> pd.Series:
    """Cross-sectional rank in [-1, 1]; missing values land on the median (0)."""
    r = row.rank(pct=True)
    return (2.0 * (r - 0.5)).fillna(0.0)


def build_panel(close: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.DatetimeIndex, list[str]]:
    """Rank-transformed feature matrix and forward-return target, indexed by
    (month_end, ticker). The target for the final month-end is NaN by
    construction — that month has not happened yet."""
    feats = feature_frames(close)
    names = sorted(feats)
    me = month_end_dates(close.index)

    # eligibility: a real close plus the two features every model leans on
    eligible = close.loc[me].notna() & feats["r6"].loc[me].notna() & feats["vol126"].loc[me].notna()

    blocks, idx_dates, idx_tickers = [], [], []
    for d in me:
        cols = eligible.columns[eligible.loc[d].values]
        if len(cols) < MIN_NAMES_PER_MONTH:
            continue
        block = pd.DataFrame({f: _cs_rank(feats[f].loc[d, cols]) for f in names})
        blocks.append(block.values)
        idx_dates.extend([d] * len(cols))
        idx_tickers.extend(cols)

    if not blocks:
        raise ValueError("no month-ends with enough cross-section to learn from")

    mi = pd.MultiIndex.from_arrays([pd.DatetimeIndex(idx_dates), idx_tickers],
                                   names=["date", "ticker"])
    X = pd.DataFrame(np.vstack(blocks), index=mi, columns=names)

    # Forward month-end-to-month-end return, winsorized. A live run happens a
    # day or two into a new month, so `me` ends on a stub: its last entry is the
    # newest close, not a completed month. Pairing the previous month-end with
    # that stub would teach the model on a one-day "month", so any span shorter
    # than a real month is dropped from the target — it still gets a prediction,
    # it just never becomes a training example.
    px = close.loc[me]
    fwd = (px.shift(-1) / px - 1.0).clip(-TARGET_CLIP, TARGET_CLIP)
    span = pd.Series(me, index=me).shift(-1) - pd.Series(me, index=me)
    fwd = fwd.where(span >= MIN_TARGET_SPAN, np.nan, axis=0)
    y = pd.Series(fwd.stack(future_stack=True).reindex(mi).values, index=mi, name="y")
    return X, y, me, names


# -------------------------------------------------------------------- models --
def _fit_predict(Xtr: np.ndarray, ytr: np.ndarray, Xte: np.ndarray) -> dict[str, np.ndarray]:
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import RidgeCV

    ridge = RidgeCV(alphas=RIDGE_ALPHAS).fit(Xtr, ytr)
    gbm = HistGradientBoostingRegressor(
        max_depth=3,
        max_iter=150,
        learning_rate=0.05,
        min_samples_leaf=40,
        l2_regularization=1.0,
        early_stopping=False,
        random_state=0,
    ).fit(Xtr, ytr)
    return {"ml_ridge": ridge.predict(Xte), "ml_gbm": gbm.predict(Xte)}


def _consensus(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Blend two prediction vectors by *rank* (so the model with the wider
    spread can't dominate), then map the consensus ordering back onto the
    averaged prediction values — which keeps the result in return units, and
    therefore keeps its sign meaningful for the `require_positive` cash rule."""
    rank = pd.Series(a).rank(pct=True).values + pd.Series(b).rank(pct=True).values
    slots = np.argsort(np.argsort(rank))
    return np.sort(0.5 * (a + b))[slots]


def _walk_forward_scores(close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    X, y, me, names = cached_panel(close)
    dates = X.index.get_level_values("date")
    tickers_all = X.index.get_level_values("ticker")
    Xv, yv, has_y = X.values, y.values, y.notna().values
    fallback = momentum(close, 273, 21)   # pre-registered warm-up default

    out = {k: pd.DataFrame(index=close.index, columns=close.columns, dtype=float)
           for k in LEARNED}
    pred_dates = [d for d in me if d in set(dates)]
    n_fit = 0

    for d in pred_dates:
        train_mask = np.asarray(dates < d) & has_y
        te_mask = np.asarray(dates == d)
        tickers = tickers_all[te_mask]

        if pd.Index(dates[train_mask]).nunique() < MIN_TRAIN_MONTHS:
            for k in LEARNED:
                out[k].loc[d, tickers] = fallback.loc[d, tickers].values
            continue

        preds = _fit_predict(Xv[train_mask], yv[train_mask], Xv[te_mask])
        n_fit += 1
        for k in ("ml_ridge", "ml_gbm"):
            out[k].loc[d, tickers] = preds[k]
        out["ml_ens"].loc[d, tickers] = _consensus(preds["ml_ridge"], preds["ml_gbm"])

    log.info("ML signals: %d month-end fits (%d warm-up months, %d features, %d tickers)",
             n_fit, len(pred_dates) - n_fit, len(names), close.shape[1])

    # the backtest reads signals at month-ends and `current_picks` at the last
    # close; carry the monthly score forward so both lookups resolve.
    for k in LEARNED:
        out[k] = out[k].ffill()
    return out


# --------------------------------------------------------------------- cache --
# `SIGNALS` calls into here once per learner, and `run.py` once more for the
# coefficient display — all with the same price panel. Keyed on panel identity
# so a single walk-forward training pass serves every caller.
_SCORES: dict[tuple, dict[str, pd.DataFrame]] = {}
_PANELS: dict[tuple, tuple] = {}


def _panel_key(close: pd.DataFrame) -> tuple:
    return (id(close), close.shape, close.index[-1], close.columns[0], close.columns[-1])


def cached_panel(close: pd.DataFrame) -> tuple:
    key = _panel_key(close)
    if key not in _PANELS:
        _PANELS.clear()
        _PANELS[key] = build_panel(close)
    return _PANELS[key]


def ml_scores(close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """All three learned score frames, computed once per price panel."""
    key = _panel_key(close)
    if key not in _SCORES:
        _SCORES.clear()
        _SCORES[key] = _walk_forward_scores(close)
    return _SCORES[key]


# ------------------------------------------------------------- introspection --
def feature_importance(close: pd.DataFrame) -> pd.DataFrame:
    """Ridge coefficients from a fit on the full realized history, for display
    only — it says what the linear learner currently leans on. Never fed back
    into the backtest, which always uses the walk-forward fits above."""
    from sklearn.linear_model import RidgeCV

    X, y, _, names = cached_panel(close)
    m = y.notna().values
    if m.sum() < MIN_NAMES_PER_MONTH * MIN_TRAIN_MONTHS:
        return pd.DataFrame(columns=["feature", "coef"])
    fit = RidgeCV(alphas=RIDGE_ALPHAS).fit(X.values[m], y.values[m])
    df = pd.DataFrame({"feature": names, "coef": fit.coef_})
    return df.reindex(df.coef.abs().sort_values(ascending=False).index).reset_index(drop=True)
