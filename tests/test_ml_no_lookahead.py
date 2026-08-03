"""The one test that actually matters for a fitted signal.

A hand-written momentum formula cannot see the future by accident. A learned
one can, in half a dozen quiet ways: a rolling feature that centres on its
window, a target that overlaps the prediction month, a scaler fitted on the
full sample. Any of those would show up as a backtest that looks wonderful and
a live run that doesn't.

So we test it directly rather than by inspection: compute the scores from the
full price history, then recompute them from a history truncated part-way —
every later price physically deleted. If the model is using anything it could
not have known at the time, the two runs disagree.

These run on the committed real-price snapshot (a 60-ticker slice, for speed).
The same check has been run at production scale — ~350 tickers over 2016-2026,
the panel the published picks come from — and agrees to floating-point noise.

Run with:  PYTHONPATH=src pytest tests/ -q
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from halalmo import ml
from halalmo.data import from_snapshot
from halalmo.signals import LEARNED, SIGNALS

SNAPSHOT = "data/snapshot_prices.parquet"
N_TICKERS = 60          # enough cross-section to fit, small enough to stay quick
CUT_BACK = 6            # test the month-end this many months before the end


@pytest.fixture(scope="module")
def close() -> pd.DataFrame:
    px = from_snapshot(SNAPSHOT).usable().close
    keep = sorted(px.columns[px.notna().all()])[:N_TICKERS]
    if len(keep) < ml.MIN_NAMES_PER_MONTH:
        pytest.skip("snapshot too thin for a cross-sectional fit")
    return px[keep]


def test_scores_are_invariant_to_deleting_the_future(close):
    """The core leak test: cutting the price history at `cut` must not move any
    score at or before `cut`.

    Every month-end in the overlap is compared, not just the cut date — for a
    prediction at `t <= cut` both the features (backward-looking) and the
    training set (finished months before `t`) are identical in the two panels,
    so *all* of them must agree. Same two training passes, far more assertions.
    """
    month_ends = ml.month_end_dates(close.index)
    cut = month_ends[-CUT_BACK]

    full = {k: v.copy() for k, v in ml.ml_scores(close).items()}   # cache clears on next call
    truncated = ml.ml_scores(close.loc[:cut].copy())
    overlap = ml.month_end_dates(close.loc[:cut].index)

    compared = 0
    for key in ml.LEARNED:
        a, b = full[key].loc[overlap], truncated[key].loc[overlap]
        both = a.notna() & b.notna()
        compared += int(both.values.sum())
        worst = float(np.nanmax((a - b).abs().where(both).values))
        assert worst < 1e-10, f"{key}: deleting the future moved a score by {worst:.3e}"

    # a comparison over an empty overlap would pass trivially
    assert compared > 1000, f"only {compared} score cells compared — fixture too thin"


def test_training_target_never_reaches_past_the_prediction_month(close):
    """Structural check on the panel itself: the forward return attached to
    month `s` is realized at the *next* month-end, so a pair may only train a
    model predicting `d` when that next month-end is on or before `d`."""
    X, y, month_ends, _ = ml.build_panel(close.copy())
    dates = X.index.get_level_values("date")
    nxt = dict(zip(month_ends[:-1], month_ends[1:]))

    for d in month_ends[-4:]:
        usable = np.asarray(dates < d) & y.notna().values
        for s in pd.Index(dates[usable]).unique():
            assert nxt[s] <= d, f"target for {s.date()} resolves after {d.date()}"


def test_last_month_has_no_target(close):
    """The final month-end cannot have a realized forward return, so it must
    never enter a training set."""
    _, y, month_ends, _ = ml.build_panel(close.copy())
    last = y[y.index.get_level_values("date") == month_ends[-1]]
    assert len(last) and last.isna().all()


def test_stub_month_is_not_a_training_target(close):
    """A live run lands a day or two into a new month, so the panel's last
    'month-end' is a stub. The month before it must not be trained on a
    two-day return dressed up as a month."""
    month_ends = ml.month_end_dates(close.index)
    last_full = month_ends[-2]                       # a genuine month-end close
    stub_day = last_full + pd.Timedelta(days=4)      # a couple of sessions into the next month
    assert stub_day.month != last_full.month, "fixture did not cross a month boundary"

    truncated = close.loc[:last_full]
    stubbed = pd.concat([truncated, truncated.iloc[[-1]].rename(index={last_full: stub_day})])

    _, y, me, _ = ml.build_panel(stubbed)
    assert me[-1] == stub_day and me[-2] == last_full, "fixture did not produce a stub month"
    penultimate = y[y.index.get_level_values("date") == me[-2]]
    assert len(penultimate) and penultimate.isna().all()

    # ...while a genuine month-to-month span is still a usable target
    assert y[y.index.get_level_values("date") == me[-3]].notna().any()


def test_learned_signals_are_on_the_menu(close):
    """The learners must be ordinary contestants, resolvable through the same
    registry the backtest iterates — not a special path around it."""
    for key in LEARNED:
        assert key in SIGNALS
        frame = SIGNALS[key](close)
        assert frame.shape[1] == close.shape[1]
        assert frame.loc[ml.month_end_dates(close.index)[-1]].notna().any()
