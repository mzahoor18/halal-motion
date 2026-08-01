"""Walk-forward backtest engine.

Timing discipline (no lookahead):
  * signal date  = last trading day of month M-1 (signals use data <= that day)
  * execution    = close of the FIRST trading day of month M (conservative:
                   you could realistically place these orders that morning)
  * costs        = cost_bps_per_side x sum(|weight changes|), charged at each
                   rebalance and on every intramonth stop exit
  * stops        = trailing exit at a *percentage* below the running max close
                   since entry. The percentage is atr_multiple x ATR(22)
                   expressed as a fraction of that high, then clamped into the
                   track's [stop_min_pct, stop_max_pct] band — so a stop is
                   never wider than the band allows, however wild the stock.
                   Breach on close => sold at the NEXT day's close, proceeds
                   sit in cash until the next rebalance.

Portfolio construction per track (TrackSpec):
  * optional low-volatility screen (keep the calmest X% of the eligible names)
  * optional positive-momentum requirement, with the shortfall held in CASH
  * optional per-sector cap, so a sleeve can't become an all-Technology bet
  * equal or inverse-volatility weighting of whatever survives

Monthly return for month M = value change between consecutive post-rebalance
closes, so the adaptive selector consumes genuinely out-of-sample numbers.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import logging
import numpy as np
import pandas as pd

from .signals import SIGNALS, ann_vol, atr, MIN_VOL
from .sectors import cap_by_sector, UNKNOWN
from .data import PriceData

log = logging.getLogger("halalmo.backtest")


@dataclass(frozen=True)
class TrackSpec:
    """Everything that makes one sleeve different from another."""
    key: str
    label: str
    blurb: str = ""
    n: int = 20
    weighting: str = "inv_vol"          # 'inv_vol' | 'equal'
    max_per_sector: int | None = None   # None => no diversification cap
    vol_screen_pct: float | None = None # e.g. 0.5 => only the calmest half rank
    require_positive: bool = False      # drop negative-momentum names, hold cash
    stop_min_pct: float = 0.05
    stop_max_pct: float = 0.15

    @classmethod
    def from_config(cls, key: str, cfg: dict) -> "TrackSpec":
        return cls(
            key=key,
            label=cfg["label"],
            blurb=cfg.get("blurb", ""),
            n=int(cfg["n"]),
            weighting=cfg.get("weighting", "inv_vol"),
            max_per_sector=cfg.get("max_per_sector"),
            vol_screen_pct=cfg.get("vol_screen_pct"),
            require_positive=bool(cfg.get("require_positive", False)),
            stop_min_pct=float(cfg.get("stop_min_pct", 0.05)),
            stop_max_pct=float(cfg.get("stop_max_pct", 0.15)),
        )


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


# ---------------------------------------------------------------- selection --
def select_targets(sig_row: pd.Series, close_row: pd.Series, vol_row: pd.Series,
                   spec: TrackSpec, sectors: pd.Series) -> pd.Series:
    """Target weights for one rebalance. May sum to < 1 (the remainder is cash)
    when `require_positive` leaves fewer than `n` qualifying names."""
    s = sig_row.dropna()
    s = s[close_row.reindex(s.index).notna()]
    needs_vol = spec.weighting == "inv_vol" or spec.vol_screen_pct is not None
    if needs_vol:
        v_all = vol_row.reindex(s.index)
        s = s[v_all.notna()]
    if spec.vol_screen_pct is not None and len(s):
        v = vol_row.reindex(s.index)
        s = s[v <= v.quantile(spec.vol_screen_pct)]
    if spec.require_positive:
        s = s[s > 0]
    if not len(s):
        return pd.Series(dtype=float)

    top = cap_by_sector(s.sort_values(ascending=False), sectors, spec.n, spec.max_per_sector)
    if not len(top):
        return pd.Series(dtype=float)

    if spec.weighting == "inv_vol":
        iv = 1.0 / vol_row.reindex(top.index).clip(lower=MIN_VOL)
        w = iv / iv.sum()
    else:
        w = pd.Series(1.0 / len(top), index=top.index)

    # cash fallback: whatever screen left the sleeve short of n names — momentum
    # requirement, sector cap, or simply a thin universe — the shortfall sits in
    # cash rather than silently over-concentrating into fewer, larger positions.
    invested = min(1.0, len(top) / spec.n)
    return w * invested


def stop_distance(price_ref: float, atr_val: float, atr_mult: float,
                  spec: TrackSpec) -> float:
    """Trailing-stop distance as a fraction of `price_ref`, clamped to the
    track's band. Falls back to the middle of the band when ATR is unavailable."""
    if np.isfinite(atr_val) and price_ref > 0:
        raw = atr_mult * atr_val / price_ref
    else:
        raw = (spec.stop_min_pct + spec.stop_max_pct) / 2.0
    return float(min(max(raw, spec.stop_min_pct), spec.stop_max_pct))


# ----------------------------------------------------------------- backtest --
def run_variant(pdata: PriceData, variant: Variant, spec: TrackSpec,
                start: str, cost_bps: float, atr_mult: float,
                sectors: pd.Series, precomputed: dict | None = None) -> VariantResult:
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
        targets = select_targets(sig.loc[sd], close.loc[sd], vol.loc[sd], spec, sectors)

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
                    dist = stop_distance(run_max[t], A[r_i, ci], atr_mult, spec)
                    if p1 < run_max[t] * (1.0 - dist):
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


def current_picks(pdata: PriceData, sig_key: str, spec: TrackSpec, atr_mult: float,
                  sectors: pd.Series, prev_selection: set[str] | None = None,
                  precomputed: dict | None = None) -> pd.DataFrame:
    """Picks as of the latest available close, with suggested trailing stops.

    Names that were already held last month keep their trailing stop (anchored
    at the running max over the holding period); brand-new entries anchor at the
    latest close. `stop_drop_pct` is what a holder actually watches: how far the
    stock must fall *from here* before the stop trips.
    """
    close = pdata.close
    sd = close.index[-1]
    pre = precomputed or {}
    sig = pre.get(("sig", sig_key))
    if sig is None:
        sig = SIGNALS[sig_key](close)
    vol = pre.get("vol")
    if vol is None:
        vol = ann_vol(close)
    atr22 = pre.get("atr")
    if atr22 is None:
        atr22 = atr(pdata.high, pdata.low, close, 22)

    w = select_targets(sig.loc[sd], close.loc[sd], vol.loc[sd], spec, sectors)
    month_start = sd.to_period("M").start_time
    prev = prev_selection or set()
    rows = []
    for t in w.index:
        px = float(close.at[sd, t])
        a_ = float(atr22.at[sd, t])
        if t in prev:
            hist = close[t].loc[month_start:sd]
            ref = float(np.nanmax(hist.values)) if len(hist) else px
        else:
            ref = px
        dist = stop_distance(ref, a_, atr_mult, spec)
        stop = ref * (1.0 - dist)
        # A trailing stop can sit ABOVE the current price when a held name has
        # already fallen further than the band allows from its running high —
        # i.e. the exit has effectively already triggered. Publishing that as a
        # sell level below today's price would be incoherent, so we re-anchor to
        # the current price and flag the name as already breached.
        breached = stop >= px
        if breached:
            dist = stop_distance(px, a_, atr_mult, spec)
            stop = px * (1.0 - dist)
        rows.append({
            "ticker": t,
            "sector": str(sectors.get(t, UNKNOWN)),
            "weight": round(float(w[t]), 4),
            "price": round(px, 2),
            "stop": round(max(stop, 0.01), 2),
            "stop_drop_pct": round(max(0.0, (px - stop) / px), 4),
            "signal_score": round(float(sig.at[sd, t]), 4),
            "status": "breached" if breached else ("held" if t in prev else "new"),
        })
    df = pd.DataFrame(rows)
    if len(df):
        df = df.sort_values("weight", ascending=False).reset_index(drop=True)
    return df
