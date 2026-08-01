"""Universe construction: union of SPUS + MNZL holdings.

Live sources (verified July 2026):
  - SPUS: daily holdings CSV published by the fund administrator
      https://www.sp-funds.com/wp-content/uploads/data/TidalFG_Holdings_SPUS.csv
    Fallback: parse the holdings table on https://www.sp-funds.com/spus/
  - MNZL: full holdings table embedded in https://manzilfunds.com/

If both live fetches fail (site redesign, network issue), we fall back to the
committed seed file data/universe_seed.csv. Whenever a live fetch succeeds the
seed is refreshed on disk, so the cache heals itself over time.
"""
from __future__ import annotations
import io
import re
import logging
import pandas as pd
import requests
from bs4 import BeautifulSoup

log = logging.getLogger("halalmo.universe")

SPUS_CSV = "https://www.sp-funds.com/wp-content/uploads/data/TidalFG_Holdings_SPUS.csv"
SPUS_PAGE = "https://www.sp-funds.com/spus/"
MNZL_PAGE = "https://manzilfunds.com/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; halal-momentum/1.0; personal research)"}

NON_EQUITY = {"CASH&OTHER", "CASH & OTHER", "CASH", "USD"}


def _clean_ticker(raw: str) -> str | None:
    t = str(raw).strip().upper()
    if not t or t in NON_EQUITY:
        return None
    # Drop CUSIP-like or placeholder identifiers (digits, CVR suffixes, etc.)
    if re.search(r"\d", t) or len(t) > 6:
        return None
    return t.replace("/", "-").replace(".", "-")  # Yahoo-style share classes


def fetch_spus() -> list[str]:
    """SPUS holdings tickers, CSV first, HTML table fallback."""
    try:
        r = requests.get(SPUS_CSV, headers=HEADERS, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        col = next(c for c in df.columns if "ticker" in c.lower().replace(" ", ""))
        ticks = [t for t in (_clean_ticker(x) for x in df[col]) if t]
        if len(ticks) >= 100:
            log.info("SPUS via CSV: %d tickers", len(ticks))
            return sorted(set(ticks))
    except Exception as e:  # noqa: BLE001
        log.warning("SPUS CSV fetch failed (%s); trying HTML", e)
    r = requests.get(SPUS_PAGE, headers=HEADERS, timeout=30)
    r.raise_for_status()
    ticks = _tickers_from_tables(r.text, name_hints=("stockticker", "ticker"))
    log.info("SPUS via HTML: %d tickers", len(ticks))
    return ticks


def fetch_mnzl() -> list[str]:
    """MNZL holdings tickers parsed from the fund homepage table."""
    r = requests.get(MNZL_PAGE, headers=HEADERS, timeout=30)
    r.raise_for_status()
    ticks = _tickers_from_tables(r.text, name_hints=("ticker",))
    log.info("MNZL via HTML: %d tickers", len(ticks))
    return ticks


def _tickers_from_tables(html: str, name_hints: tuple[str, ...]) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    best: list[str] = []
    for table in soup.find_all("table"):
        header = table.find("tr")
        if not header:
            continue
        cells = [c.get_text(strip=True).lower().replace(" ", "") for c in header.find_all(["th", "td"])]
        idx = next((i for i, c in enumerate(cells) if any(h in c for h in name_hints)), None)
        if idx is None:
            continue
        ticks = []
        for row in table.find_all("tr")[1:]:
            tds = row.find_all(["td", "th"])
            if len(tds) > idx:
                t = _clean_ticker(tds[idx].get_text(strip=True))
                if t:
                    ticks.append(t)
        if len(ticks) > len(best):
            best = ticks
    if len(best) < 100:
        raise RuntimeError(f"holdings table parse produced only {len(best)} tickers")
    return sorted(set(best))


def load_universe(seed_path: str, refresh: bool = True,
                  funds: tuple[str, ...] = ("spus",)) -> pd.DataFrame:
    """Return DataFrame(ticker, source) for the selected fund universe(s).

    `funds` may contain 'spus' and/or 'mnzl'. Falls back per-fund to the
    committed seed file when a live fetch fails. The seed keeps rows for both
    funds so the config can be flipped later without losing the fallback.
    """
    seed = pd.read_csv(seed_path)
    seed_spus = set(seed.loc[seed.source.isin(["spus", "both"]), "ticker"])
    seed_mnzl = set(seed.loc[seed.source.isin(["mnzl", "both"]), "ticker"])

    spus = seed_spus if "spus" in funds else set()
    mnzl = seed_mnzl if "mnzl" in funds else set()
    live_spus = live_mnzl = False
    if refresh and "spus" in funds:
        try:
            spus, live_spus = set(fetch_spus()), True
        except Exception as e:  # noqa: BLE001
            log.warning("SPUS live fetch failed, using seed (%s)", e)
    if refresh and "mnzl" in funds:
        try:
            mnzl, live_mnzl = set(fetch_mnzl()), True
        except Exception as e:  # noqa: BLE001
            log.warning("MNZL live fetch failed, using seed (%s)", e)

    rows = [{"ticker": t,
             "source": "both" if (t in spus and t in mnzl) else ("spus" if t in spus else "mnzl")}
            for t in sorted(spus | mnzl)]
    uni = pd.DataFrame(rows)

    # refresh the seed only for the fund(s) fetched live, preserving the rest
    if refresh and (live_spus or live_mnzl):
        try:
            new_spus = spus if live_spus else seed_spus
            new_mnzl = mnzl if live_mnzl else seed_mnzl
            all_rows = [{"ticker": t,
                         "source": "both" if (t in new_spus and t in new_mnzl)
                         else ("spus" if t in new_spus else "mnzl")}
                        for t in sorted(new_spus | new_mnzl)]
            pd.DataFrame(all_rows).to_csv(seed_path, index=False)
            log.info("seed refreshed (%d tickers on file)", len(all_rows))
        except Exception as e:  # noqa: BLE001
            log.warning("could not refresh seed file: %s", e)
    log.info("universe [%s]: %d tickers (spus live=%s, mnzl live=%s)",
             "+".join(funds), len(uni), live_spus, live_mnzl)
    return uni
