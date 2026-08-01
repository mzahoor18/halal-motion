"""Performance statistics on monthly return series. Risk-free rate assumed 0
(disclosed on the site); all ratios annualized from monthly data."""
from __future__ import annotations
import numpy as np
import pandas as pd


def summarize(monthly: pd.Series) -> dict:
    r = monthly.dropna()
    if len(r) == 0:
        return {}
    eq = (1 + r).cumprod()
    n = len(r)
    total = float(eq.iloc[-1] - 1)
    cagr = float(eq.iloc[-1] ** (12 / n) - 1)
    vol = float(r.std(ddof=1) * np.sqrt(12)) if n > 1 else float("nan")
    sharpe = float(r.mean() * 12 / vol) if vol and vol > 0 else float("nan")
    downside = r[r < 0].std(ddof=0)
    sortino = float(r.mean() * 12 / (downside * np.sqrt(12))) if downside and downside > 1e-9 else float("nan")
    dd = eq / eq.cummax() - 1
    max_dd = float(dd.min())
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else float("nan")
    return {
        "months": n,
        "total_return": round(total, 4),
        "cagr": round(cagr, 4),
        "ann_vol": round(vol, 4),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "max_drawdown": round(max_dd, 4),
        "calmar": round(calmar, 3),
        "win_rate": round(float((r > 0).mean()), 3),
        "best_month": round(float(r.max()), 4),
        "worst_month": round(float(r.min()), 4),
    }


def equity_points(monthly: pd.Series, base: float = 100.0) -> tuple[list[str], list[float]]:
    r = monthly.dropna()
    eq = base * (1 + r).cumprod()
    labels = [str(p) for p in r.index]
    start_label = str(r.index[0] - 1)
    return [start_label] + labels, [round(base, 2)] + [round(v, 2) for v in eq.tolist()]
