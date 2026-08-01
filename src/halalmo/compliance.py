"""Ticker -> Musaffa Shariah-compliance status, layered on top of the SPUS/MNZL
fund screens.

SPUS and MNZL each run their own Shariah board's methodology, and holdings can
drift out of compliance between the fund's own rebalances (or simply differ
from Musaffa's AAOIFI-based ratios). This module checks every ticker against
Musaffa's public per-stock page (musaffa.com/stock/<ticker>/), which
server-renders a `shariahCompliantStatus` field of COMPLIANT / NON_COMPLIANT /
QUESTIONABLE alongside the rest of the page — plus, from the same fetch, the
listing `exchange` (so a ticker can never be confused with a same-symbol
company on another market when looked up directly on Musaffa) and the GICS
sub-industry (`gsubind`), used by `manual_screen.py` for the business-activity
and boycott screens layered on top of the ratio-based Musaffa verdict.

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
FIELDS = {
    "status": re.compile(r'"shariahCompliantStatus":"([A-Za-z_]+)"'),
    "exchange": re.compile(r'"exchange":"([^"]*)"'),
    "subindustry": re.compile(r'"gsubind":"([^"]*)"'),
}
BASE_URL = "https://musaffa.com/stock/{}/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; halal-motion/1.0; personal research)"}
MAX_WORKERS = 6
TIMEOUT = 20
COLUMNS = ["status", "exchange", "subindustry"]


def _musaffa_slug(ticker: str) -> list[str]:
    """Candidate URL slugs to try, in order. Yahoo-style share-class dashes
    (e.g. LEN-B) are dotted on Musaffa (LEN.B); fall back to the base ticker."""
    candidates = [ticker]
    if "-" in ticker:
        candidates.append(ticker.replace("-", "."))
        candidates.append(ticker.split("-")[0])
    return candidates


def _fetch_one(ticker: str) -> tuple[str, dict]:
    for slug in _musaffa_slug(ticker):
        try:
            r = requests.get(BASE_URL.format(slug), headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            anchor = r.text.find(f'"stock-overview:{slug}"')
            if anchor == -1:
                continue
            seg = r.text[anchor:anchor + 8000]
            m = FIELDS["status"].search(seg)
            if not m:
                continue
            m_exch = FIELDS["exchange"].search(seg)
            m_sub = FIELDS["subindustry"].search(seg)
            return ticker, {
                "status": m.group(1).upper(),
                "exchange": m_exch.group(1) if m_exch else "",
                "subindustry": m_sub.group(1) if m_sub else "",
            }
        except requests.RequestException as e:  # noqa: BLE001
            log.debug("compliance lookup failed for %s (%s): %s", ticker, slug, e)
    return ticker, {"status": UNKNOWN, "exchange": "", "subindustry": ""}


def load_compliance(path: str, tickers: list[str], refresh: bool = True) -> pd.DataFrame:
    """DataFrame indexed by ticker (columns: status, exchange, subindustry) for
    `tickers`, filling gaps from Musaffa when `refresh` is on. Anything still
    unresolved maps to status 'UNKNOWN'."""
    cache: dict[str, dict] = {}
    if os.path.exists(path):
        df = pd.read_csv(path, dtype=str).fillna("")
        for _, row in df.iterrows():
            cache[row["ticker"]] = {
                "status": row.get("status") or UNKNOWN,
                "exchange": row.get("exchange", ""),
                "subindustry": row.get("subindustry", ""),
            }

    # a cache entry needs a fresh lookup if it's missing, still unresolved, or
    # predates the exchange/subindustry columns (old-format cache row)
    missing = [t for t in tickers
              if t not in cache or cache[t]["status"] == UNKNOWN or not cache[t]["exchange"]]
    if refresh and missing:
        log.info("checking Musaffa compliance for %d ticker(s) …", len(missing))
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            for t, info in ex.map(_fetch_one, missing):
                cache[t] = info
        log.info("compliance lookups done in %.0fs", time.time() - t0)
        try:
            rows = [{"ticker": t, **info} for t, info in sorted(cache.items())]
            out = pd.DataFrame(rows, columns=["ticker"] + COLUMNS)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            out.to_csv(path, index=False)
            log.info("compliance map saved (%d tickers on file)", len(out))
        except Exception as e:  # noqa: BLE001
            log.warning("could not write compliance map: %s", e)

    rows = {t: cache.get(t, {"status": UNKNOWN, "exchange": "", "subindustry": ""}) for t in tickers}
    df = pd.DataFrame.from_dict(rows, orient="index", columns=COLUMNS)
    df.index.name = "ticker"
    counts = df.status.value_counts()
    log.info("compliance map: %s", dict(counts))
    return df


def filter_compliant(tickers: list[str], comp: pd.DataFrame) -> tuple[list[str], list[dict]]:
    """Split `tickers` into (compliant, dropped) where dropped is a list of
    {ticker, status} for anything not COMPLIANT (NON_COMPLIANT, QUESTIONABLE,
    or UNKNOWN/uncovered) — excluded rather than guessed at."""
    kept, dropped = [], []
    for t in tickers:
        st = comp.status.get(t, UNKNOWN)
        if st == COMPLIANT:
            kept.append(t)
        else:
            dropped.append({"ticker": t, "status": st})
    return kept, dropped
