"""Price data layer.

Online: batch download of dividend-adjusted OHLC via yfinance (auto_adjust=True,
so Close/High/Low form a consistent total-return-ish series).

Offline: deterministic synthetic prices with regime-persistent drifts, used to
exercise the entire pipeline end-to-end without network access. Synthetic mode
is for plumbing verification only — never for real conclusions.
"""
from __future__ import annotations
import logging
import numpy as np
import pandas as pd

log = logging.getLogger("halalmo.data")


class PriceData:
    def __init__(self, close: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame):
        self.close, self.high, self.low = close, high, low

    def usable(self, min_obs: int = 260) -> "PriceData":
        ok = self.close.columns[self.close.notna().sum() >= min_obs]
        dropped = sorted(set(self.close.columns) - set(ok))
        if dropped:
            log.info("dropping %d tickers with <%d observations: %s%s",
                     len(dropped), min_obs, ",".join(dropped[:12]), "…" if len(dropped) > 12 else "")
        return PriceData(self.close[ok], self.high[ok], self.low[ok])


def download(tickers: list[str], start: str) -> PriceData:
    import yfinance as yf
    log.info("downloading %d tickers from %s …", len(tickers), start)
    raw = yf.download(tickers, start=start, auto_adjust=True, progress=False,
                      group_by="column", threads=True)
    if isinstance(raw.columns, pd.MultiIndex):
        close, high, low = raw["Close"], raw["High"], raw["Low"]
    else:  # single ticker edge case
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})
        high = raw[["High"]].rename(columns={"High": tickers[0]})
        low = raw[["Low"]].rename(columns={"Low": tickers[0]})
    close = close.dropna(how="all")
    idx = close.index
    return PriceData(close, high.reindex(idx), low.reindex(idx))


def _read_parquet(path: str) -> pd.DataFrame:
    """Read a parquet file, tolerating a pyarrow/file-format mismatch.

    Some pyarrow versions raise "Repetition level histogram size mismatch" on
    files written by a different version; fastparquet reads them fine. Try the
    default engine first, then fall back rather than failing the whole run."""
    try:
        return pd.read_parquet(path)
    except Exception as e:  # noqa: BLE001 - any engine/format error is worth a fallback
        log.warning("default parquet engine failed (%s); retrying with fastparquet", e)
        return pd.read_parquet(path, engine="fastparquet")


def from_snapshot(path: str) -> PriceData:
    """Load a committed real-price snapshot (long-form parquet:
    date, ticker, close, high, low — closes dividend/split-adjusted)."""
    df = _read_parquet(path)
    close = df.pivot(index="date", columns="ticker", values="close").sort_index()
    high = df.pivot(index="date", columns="ticker", values="high").sort_index()
    low = df.pivot(index="date", columns="ticker", values="low").sort_index()
    close.index = pd.to_datetime(close.index)
    high.index, low.index = close.index, close.index
    log.info("snapshot prices: %d tickers x %d days (%s -> %s)", close.shape[1],
             close.shape[0], close.index[0].date(), close.index[-1].date())
    return PriceData(close, high, low)


def synthetic(tickers: list[str], start: str, end: str | None = None, seed: int = 7) -> PriceData:
    """GBM with slowly mean-reverting per-stock drift => genuine cross-sectional
    momentum structure, plus a common market factor with a 2020-style crash."""
    rng = np.random.default_rng(seed)
    end = end or pd.Timestamp.today().normalize().isoformat()
    dates = pd.bdate_range(start, end)
    n, T = len(tickers), len(dates)
    mkt = rng.normal(0.0004, 0.011, T)
    crash = (dates >= "2020-02-20") & (dates <= "2020-03-23")
    mkt[crash] -= 0.028
    rebound = (dates > "2020-03-23") & (dates <= "2020-06-01")
    mkt[rebound] += 0.006
    drift = rng.normal(0, 0.0009, n)
    rets = np.empty((T, n))
    for t in range(T):
        drift = 0.995 * drift + rng.normal(0, 0.00012, n)  # persistent alpha => momentum
        beta = 1.0 + 0.3 * np.tanh(drift * 800)
        rets[t] = drift + beta * mkt[t] + rng.normal(0, 0.016, n)
    close = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=dates, columns=tickers)
    intraday = np.abs(rng.normal(0.008, 0.004, (T, n)))
    high = close * (1 + intraday)
    low = close * (1 - intraday)
    # a few late listings to exercise eligibility logic
    for i, t in enumerate(tickers[: max(3, n // 40)]):
        close.iloc[: 700 + 13 * i, close.columns.get_loc(t)] = np.nan
        high.iloc[: 700 + 13 * i, high.columns.get_loc(t)] = np.nan
        low.iloc[: 700 + 13 * i, low.columns.get_loc(t)] = np.nan
    log.info("synthetic prices: %d tickers x %d days", n, T)
    return PriceData(close, high, low)
