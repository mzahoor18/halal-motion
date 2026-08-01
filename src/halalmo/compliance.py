"""Ticker -> Musaffa Shariah-compliance status, layered on top of the SPUS/MNZL
fund screens.

SPUS and MNZL each run their own Shariah board's methodology, and holdings can
drift out of compliance between the fund's own rebalances (or simply differ
from Musaffa's AAOIFI-based ratios). This module checks every ticker against
Musaffa's public per-stock page (musaffa.com/stock/<ticker>/), which
server-renders a `shariahCompliantStatus` field of COMPLIANT / NON_COMPLIANT /
QUESTIONABLE alongside the rest of the page.

Only COMPLIANT survives the filter — QUESTIONABLE (doubtful, e.g. borderline
debt ratios) and tickers Musaffa doesn't cover at all are excluded rather than
guessed at. See `filter_compliant`.

The map lives in `data/compliance.csv` (committed, so a run never *depends* on
the network). On a live run we look up only tickers missing from the cache and
write the enlarged map back, the same pattern as `sectors.py`.
"""
from __future__ import annotations
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

log = logging.getLogger("halalmo.compliance")

UNKNOWN = "UNKNOWN"
COMPLIANT = "COMPLIANT"
STATUS_FIELD_RE = re.compile(r'"shariahCompliantStatus":"([A-Za-z_]+)"')
BASE_URL = "https://musaffa.com/stock/{}/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; halal-motion/1.0; personal research)"}
MAX_WORKERS = 6
TIMEOUT = 20


def _musaffa_slug(ticker: str) -> list[str]:
    """Candidate URL slugs to try, in order. Yahoo-style share-class dashes
    (e.g. LEN-B) are dotted on Musaffa (LEN.B); fall back to the base ticker."""
    candidates = [ticker]
    if "-" in ticker:
        candidates.append(ticker.replace("-", "."))
        candidates.append(ticker.split("-")[0])
    return candidates


def _fetch_one(ticker: str) -> tuple[str, str]:
    for slug in _musaffa_slug(ticker):
        try:
            r = requests.get(BASE_URL.format(slug), headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            m = STATUS_FIELD_RE.search(r.text, r.text.find(f'"stock-overview:{slug}"'))
            if m:
                return ticker, m.group(1).upper()
        except requests.RequestException as e:  # noqa: BLE001
            log.debug("compliance lookup failed for %s (%s): %s", ticker, slug, e)
    return ticker, UNKNOWN


def load_compliance(path: str, tickers: list[str], refresh: bool = True) -> pd.Series:
    """Series ticker -> Musaffa status for `tickers`, filling gaps from Musaffa
    when `refresh` is on. Anything still unresolved maps to 'UNKNOWN'."""
    cache: dict[str, str] = {}
    if os.path.exists(path):
        df = pd.read_csv(path)
        cache = dict(zip(df.ticker, df.status.fillna(UNKNOWN)))

    missing = [t for t in tickers if t not in cache or cache[t] == UNKNOWN]
    if refresh and missing:
        log.info("checking Musaffa compliance for %d ticker(s) …", len(missing))
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            for t, status in ex.map(_fetch_one, missing):
                cache[t] = status
        log.info("compliance lookups done in %.0fs", time.time() - t0)
        try:
            out = pd.DataFrame(sorted(cache.items()), columns=["ticker", "status"])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            out.to_csv(path, index=False)
            log.info("compliance map saved (%d tickers on file)", len(out))
        except Exception as e:  # noqa: BLE001
            log.warning("could not write compliance map: %s", e)

    s = pd.Series({t: cache.get(t, UNKNOWN) for t in tickers}, name="status")
    counts = s.value_counts()
    log.info("compliance map: %s", dict(counts))
    return s


def filter_compliant(tickers: list[str], status: pd.Series) -> tuple[list[str], list[dict]]:
    """Split `tickers` into (compliant, dropped) where dropped is a list of
    {ticker, status} for anything not COMPLIANT (NON_COMPLIANT, QUESTIONABLE,
    or UNKNOWN/uncovered) — excluded rather than guessed at."""
    kept, dropped = [], []
    for t in tickers:
        st = status.get(t, UNKNOWN)
        if st == COMPLIANT:
            kept.append(t)
        else:
            dropped.append({"ticker": t, "status": st})
    return kept, dropped
