"""Walk-forward backtest engine.

Timing discipline (no lookahead):
  * signal date  = last trading day of month M-1 (signals use data <= that day)
  * execution    = close of the FIRST trading day of month M (conservative:
                   you could realistically place these orders that morning)
  * costs        = cost_bps_per_side x sum(|weight changes|), charged at each
                   rebalance and on every intramonth stop exit
  * stops        = chandelier exit: running max close since entry minus
                   atr_multiple x ATR(22); breach on close => sold at the NEXT
                   day's close, proceeds sit in cash until the next rebalance

Monthly return for month M = value change between consecutive post-rebalance
closes, so the adaptive selector consumes genuinely out-of-sample numbers.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import logging
import numpy as np
import pandas as pd

from .signals import SIGNALS, ann_vol, atr, MIN_VOL
from .data import PriceData

log = logging.getLogger("halalmo.backtest")


@dataclass
class Variant:
    signal: str
    stops: bool

    @property
    def name(self) -> str:
        return f"{self.signal}{'+stops' if self.stops else ''}"


@dataclass
class VariantResult:
    name: str
    monthly: pd.Series          # PeriodIndex (M) -> return of that month
    totals: pd.Series           # daily equity (1.0 start, after costs)
    stop_exits: int = 0
    last_targets: dict = field(default_factory=dict)


def rebalance_schedule(dates: pd.DatetimeIndex, start: str) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """[(signal_date=month_end, exec_date=next trading day), ...] with exec >= start."""
    me_mask = dates.to_period("M") != np.append(dates.to_period("M")[1:], None)
    pairs = []
    pos = np.flatnonzero(me_mask)
    for p in pos:
        if p + 1 < len(dates):
            sd, ed = dates[p], dates[p + 1]
            if ed >= pd.Timestamp(start):
                pairs.append((sd, ed))
    return pairs


def run_variant(pdata: PriceData, variant: Variant, n: int, weighting: str,
                start: str, cost_bps: float, atr_mult: float,
                precomputed: dict | None = None) -> VariantResult:
    close = pdata.close
    dates = close.index
    pre = precomputed or {}
    sig = pre.get(("sig", variant.signal))
    if sig is None:
        sig = SIGNALS[variant.signal](close)
    vol = pre.get("vol")
    if vol is None:
        vol = ann_vol(close)
    atr22 = pre.get("atr")
    if atr22 is None:
        atr22 = atr(pdata.high, pdata.low, close, 22)

    C = close.values
    A = atr22.values
    row = {d: i for i, d in enumerate(dates)}
    col = {t: j for j, t in enumerate(close.columns)}
    cost = cost_bps / 1e4

    pairs = rebalance_schedule(dates, start)
    if not pairs:
        raise ValueError("no rebalance dates in range")

    totals = {}
    total = 1.0
    holdings: dict[str, float] = {}
    stop_exits = 0
    monthly_idx, monthly_val = [], []
    month_start_total = None
    last_targets: dict[str, float] = {}

    for i, (sd, ed) in enumerate(pairs):
        # ---- select targets from signal date data ----
        s = sig.loc[sd].dropna()
        alive = close.loc[sd].notna()
        s = s[alive.reindex(s.index, fill_value=False)]
        if weighting == "inv_vol":
            v = vol.loc[sd].reindex(s.index)
            s = s[v.notna()]
        top = s.nlargest(n)
        if len(top) == 0:
            targets = pd.Series(dtype=float)
        elif weighting == "inv_vol":
            iv = 1.0 / vol.loc[sd].reindex(top.index).clip(lower=MIN_VOL)
            targets = iv / iv.sum()
        else:
            targets = pd.Series(1.0 / len(top), index=top.index)

        # ---- rebalance at close of ed ----
        cur_w = {t: v_ / total for t, v_ in holdings.items()} if total > 0 else {}
        names = set(targets.index) | set(cur_w)
        turn = sum(abs(targets.get(t, 0.0) - cur_w.get(t, 0.0)) for t in names)
        total *= (1.0 - cost * turn)
        holdings = {t: float(targets[t]) * total for t in targets.index}
        cash = total - sum(holdings.values())
        totals[ed] = total
        last_targets = {t: float(targets[t]) for t in targets.index}

        if month_start_total is not None:
            monthly_idx.append(pairs[i - 1][1].to_period("M"))
            monthly_val.append(total / month_start_total - 1.0)
        month_start_total = total

        # ---- simulate days (ed, next_ed] ----
        nxt = pairs[i + 1][1] if i + 1 < len(pairs) else dates[-1]
        seg = dates[(dates > ed) & (dates <= nxt)]
        run_max = {t: C[row[ed], col[t]] for t in holdings}
        pending: set[str] = set()
        prev_r = row[ed]
        for d in seg:
            r_i = row[d]
            for t in list(holdings):
                ci = col[t]
                p1, p0 = C[r_i, ci], C[prev_r, ci]
                if np.isfinite(p1) and np.isfinite(p0) and p0 > 0:
                    holdings[t] *= p1 / p0
            # execute yesterday's stop signals at today's close
            for t in list(pending):
                if t in holdings:
                    cash += holdings.pop(t) * (1.0 - cost)
                    stop_exits += 1
                pending.discard(t)
            # check stops on today's close (variant-dependent)
            if variant.stops:
                for t in list(holdings):
                    ci = col[t]
                    p1 = C[r_i, ci]
                    if not np.isfinite(p1):
                        continue
                    if p1 > run_max[t]:
                        run_max[t] = p1
                    a_ = A[r_i, ci]
                    if np.isfinite(a_) and p1 < run_max[t] - atr_mult * a_:
                        pending.add(t)
            total = cash + sum(holdings.values())
            totals[d] = total
            prev_r = r_i

    # close final partial month
    if month_start_total is not None and len(pairs) >= 1:
        last_ed = pairs[-1][1]
        if dates[-1] > last_ed:
            monthly_idx.append(last_ed.to_period("M"))
            monthly_val.append(total / month_start_total - 1.0)

    tot = pd.Series(totals).sort_index()
    monthly = pd.Series(monthly_val, index=pd.PeriodIndex(monthly_idx, freq="M"))
    return VariantResult(variant.name, monthly, tot, stop_exits, last_targets)


def bench_monthly(close: pd.Series, dates_ref: pd.DatetimeIndex, start: str) -> tuple[pd.Series, pd.Series]:
    """Benchmark monthly returns + equity aligned to the same exec-date grid."""
    pairs = rebalance_schedule(dates_ref, start)
    eds = [ed for _, ed in pairs]
    px = close.reindex(dates_ref).ffill()
    vals = px.loc[[d for d in eds if d in px.index]]
    if dates_ref[-1] > eds[-1]:
        vals = pd.concat([vals, px.iloc[[-1]]])
        labels = [d.to_period("M") for d in eds]
    else:
        labels = [d.to_period("M") for d in eds[:-1]]
    rets = vals.pct_change().dropna()
    rets.index = pd.PeriodIndex(labels, freq="M")
    equity = px / px.loc[eds[0]]
    return rets, equity.loc[eds[0]:]


def current_picks(pdata: PriceData, sig_key: str, n: int, weighting: str,
                  atr_mult: float, prev_selection: set[str] | None = None) -> pd.DataFrame:
    """Picks as of the latest available close, with suggested chandelier stops.

    Names that were already held last month keep their trailing stop (running
    max over the holding period); brand-new entries start at close - k*ATR.
    """
    close = pdata.close
    sd = close.index[-1]
    sig = SIGNALS[sig_key](close)
    vol = ann_vol(close)
    atr22 = atr(pdata.high, pdata.low, close, 22)

    s = sig.loc[sd].dropna()
    s = s[close.loc[sd].reindex(s.index).notna()]
    if weighting == "inv_vol":
        s = s[vol.loc[sd].reindex(s.index).notna()]
    top = s.nlargest(n)
    if weighting == "inv_vol":
        iv = 1.0 / vol.loc[sd].reindex(top.index).clip(lower=MIN_VOL)
        w = iv / iv.sum()
    else:
        w = pd.Series(1.0 / len(top), index=top.index)

    month_start = sd.to_period("M").start_time
    prev = prev_selection or set()
    rows = []
    for t in top.index:
        px = float(close.at[sd, t])
        a_ = atr22.at[sd, t]
        a_ = float(a_) if np.isfinite(a_) else px * 0.08 / 3.0
        if t in prev:
            hist = close[t].loc[month_start:sd]
            ref = float(np.nanmax(hist.values)) if len(hist) else px
        else:
            ref = px
        rows.append({
            "ticker": t, "weight": round(float(w[t]), 4), "price": round(px, 2),
            "stop": round(max(ref - atr_mult * a_, 0.01), 2),
            "signal_score": round(float(top[t]), 4),
            "status": "held" if t in prev else "new",
        })
    return pd.DataFrame(rows)
