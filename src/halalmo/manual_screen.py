"""Two screens layered on top of the Musaffa ratio-based compliance check
(see compliance.py), both driven entirely by config.yaml so they're easy to
review and extend without touching code.

`business_activity_screen` — GICS sub-industry exclusions (e.g. "Hotels,
Resorts & Cruise Lines", conventional insurance lines) that a pure
financial-ratio screen doesn't always catch: a company can pass on
debt/interest ratios while its core business routinely involves alcohol or
gambling revenue. Sub-industry comes from Musaffa's own reported GICS
classification (see compliance.py's `subindustry` column).

`bds_screen` — a small, explicitly-sourced ticker list reflecting publicly
documented boycott targets. This is NOT a comprehensive database — no clean,
machine-readable source for this exists (unlike Musaffa's compliance API).
It's a starting point maintained by hand in config.yaml; every entry should
cite where the claim comes from, and the intent is that you extend it as you
become aware of specific, well-documented cases.
"""
from __future__ import annotations
import pandas as pd


def _by_ticker(cfg_list: list[dict] | None) -> dict[str, dict]:
    return {row["ticker"]: row for row in (cfg_list or [])}


def apply_business_activity_screen(tickers: list[str], comp: pd.DataFrame,
                                   cfg: dict) -> tuple[list[str], list[dict]]:
    """Drop tickers whose GICS sub-industry is on the excluded list, or that
    are named explicitly as one-off overrides."""
    excluded_sub = set(cfg.get("excluded_subindustries") or [])
    overrides = _by_ticker(cfg.get("excluded_tickers"))
    kept, dropped = [], []
    for t in tickers:
        if t in overrides:
            row = overrides[t]
            dropped.append({"ticker": t, "reason": row.get("reason", "manually excluded"),
                            "source": row.get("source", "")})
            continue
        sub = comp.subindustry.get(t, "")
        if sub and sub in excluded_sub:
            dropped.append({"ticker": t, "reason": f"Business activity: {sub}", "source": ""})
            continue
        kept.append(t)
    return kept, dropped


def apply_bds_screen(tickers: list[str], cfg: dict) -> tuple[list[str], list[dict]]:
    """Drop tickers named in the config's boycott-target list."""
    if not cfg.get("enabled", True):
        return tickers, []
    overrides = _by_ticker(cfg.get("excluded_tickers"))
    kept, dropped = [], []
    for t in tickers:
        if t in overrides:
            row = overrides[t]
            dropped.append({"ticker": t, "reason": row.get("reason", ""), "source": row.get("source", "")})
        else:
            kept.append(t)
    return kept, dropped
