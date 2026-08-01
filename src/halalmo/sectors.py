"""Ticker -> sector map, used to keep the Balanced and Conservative sleeves
from piling into one corner of the market.

The map lives in `data/sectors.csv` (committed, so a run never *depends* on the
network). On a live run we look up only the tickers that are missing from the
cache — typically a handful after a holdings change — and write the enlarged
map back. Sector strings are Yahoo's own coarse buckets (Technology, Energy,
Healthcare, ...), which is plenty for a diversification cap.
"""
from __future__ import annotations
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

log = logging.getLogger("halalmo.sectors")

UNKNOWN = "Unknown"
MAX_WORKERS = 8


def _fetch_one(ticker: str) -> tuple[str, str]:
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).get_info() or {}
        sec = info.get("sector") or UNKNOWN
        return ticker, str(sec).strip() or UNKNOWN
    except Exception as e:  # noqa: BLE001
        log.debug("sector lookup failed for %s: %s", ticker, e)
        return ticker, UNKNOWN


def load_sectors(path: str, tickers: list[str], refresh: bool = True) -> pd.Series:
    """Series ticker -> sector for `tickers`, filling gaps from Yahoo when
    `refresh` is on. Anything still unresolved maps to 'Unknown'."""
    cache: dict[str, str] = {}
    if os.path.exists(path):
        df = pd.read_csv(path)
        cache = dict(zip(df.ticker, df.sector.fillna(UNKNOWN)))

    missing = [t for t in tickers if t not in cache or cache[t] == UNKNOWN]
    if refresh and missing:
        log.info("looking up sectors for %d ticker(s) …", len(missing))
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            for t, sec in ex.map(_fetch_one, missing):
                cache[t] = sec
        try:
            out = pd.DataFrame(sorted(cache.items()), columns=["ticker", "sector"])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            out.to_csv(path, index=False)
            log.info("sector map saved (%d tickers on file)", len(out))
        except Exception as e:  # noqa: BLE001
            log.warning("could not write sector map: %s", e)

    s = pd.Series({t: cache.get(t, UNKNOWN) for t in tickers}, name="sector")
    known = int((s != UNKNOWN).sum())
    log.info("sector map: %d/%d tickers classified across %d sectors",
             known, len(s), s[s != UNKNOWN].nunique())
    return s


def cap_by_sector(ranked: pd.Series, sectors: pd.Series, n: int,
                  max_per_sector: int | None) -> pd.Series:
    """Take the top `n` of `ranked` (already sorted best-first) while holding no
    more than `max_per_sector` names from any one sector.

    'Unknown' is treated as its own bucket but never capped — otherwise an
    incomplete map would silently shrink the portfolio. The cap is a hard
    constraint: if too few sectors have enough qualifying names to reach `n`,
    this returns fewer than `n` rather than breaching it. The caller (see
    `select_targets`) treats the shortfall as cash, same as any other screen
    that can't fill every slot.
    """
    if max_per_sector is None or max_per_sector <= 0:
        return ranked.head(n)
    picked: list[str] = []
    counts: dict[str, int] = {}
    for t in ranked.index:
        sec = sectors.get(t, UNKNOWN)
        if sec != UNKNOWN and counts.get(sec, 0) >= max_per_sector:
            continue
        picked.append(t)
        counts[sec] = counts.get(sec, 0) + 1
        if len(picked) == n:
            break
    return ranked.loc[picked]
