"""Pipeline orchestrator.

    PYTHONPATH=src python -m halalmo.run [--offline]

Steps: universe -> prices -> 12 variants x 2 tracks (walk-forward) ->
adaptive selector -> current picks with stops -> dashboard + shareable files.

--offline uses deterministic synthetic prices to validate the plumbing without
network access; the dashboard is watermarked accordingly.
"""
from __future__ import annotations
import argparse
import datetime as dt
import logging
import os
import sys

import numpy as np
import pandas as pd
import yaml

from . import data as data_mod
from . import report
from .backtest import (Variant, TrackSpec, run_variant, bench_monthly, current_picks,
                       rebalance_schedule, select_targets)
from .compliance import load_compliance, filter_compliant
from .manual_screen import apply_business_activity_screen, apply_bds_screen
from .metrics import summarize, equity_points
from .sectors import load_sectors
from .selector import walk_forward
from .signals import SIGNALS, SIGNAL_LABELS, ann_vol, atr
from .universe import load_universe

log = logging.getLogger("halalmo.run")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def pretty(variant_name: str) -> str:
    sig, _, _ = variant_name.partition("+")
    base = SIGNAL_LABELS.get(sig, sig)
    return f"{base} · stops" if variant_name.endswith("+stops") else base


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["yfinance", "snapshot", "synthetic"],
                    default="yfinance",
                    help="price source: yfinance (live), snapshot (committed real-price "
                         "parquet), synthetic (plumbing test)")
    ap.add_argument("--offline", action="store_true", help="alias for --source synthetic")
    ap.add_argument("--snapshot-path", default=None,
                    help="parquet path for --source snapshot (default data/snapshot_prices.parquet)")
    ap.add_argument("--config", default=os.path.join(ROOT, "config.yaml"))
    args = ap.parse_args()
    if args.offline:
        args.source = "synthetic"

    logging.basicConfig(level=logging.INFO, format="%(levelname).1s %(name)s: %(message)s")
    cfg = yaml.safe_load(open(args.config))
    docs_dir = os.path.join(ROOT, "docs")
    hist_dir = os.path.join(ROOT, "history")
    seed_path = os.path.join(ROOT, "data", "universe_seed.csv")
    sector_path = os.path.join(ROOT, "data", "sectors.csv")
    compliance_path = os.path.join(ROOT, "data", "compliance.csv")

    # ---------------- universe & prices ----------------
    funds = tuple(cfg.get("funds", ["spus"]))
    uni = load_universe(seed_path, refresh=args.source == "yfinance", funds=funds)
    tickers = uni.ticker.tolist()
    benchmarks = list(cfg["benchmarks"])
    start_px = cfg["price_history_start"]

    # ---------------- Musaffa compliance screen ----------------
    # SPUS and MNZL each run their own Shariah board's methodology, which can
    # drift from Musaffa's AAOIFI-based ratios between fund rebalances. Only
    # tickers Musaffa marks fully COMPLIANT stay in the tradeable universe;
    # QUESTIONABLE (doubtful) and uncovered names are excluded, not guessed at.
    comp = load_compliance(compliance_path, tickers, refresh=args.source == "yfinance")
    exchange_of = comp.exchange.to_dict()
    tickers, musaffa_excluded = filter_compliant(tickers, comp)
    for e in musaffa_excluded:
        e["exchange"] = exchange_of.get(e["ticker"], "")
    excl_counts = pd.Series([e["status"] for e in musaffa_excluded]).value_counts().to_dict() \
        if musaffa_excluded else {}
    log.info("Musaffa screen: %d compliant / %d checked, excluded %s",
             len(tickers), len(tickers) + len(musaffa_excluded), excl_counts)

    # ---------------- business-activity screen ----------------
    # A financial-ratio screen alone can pass a company whose core business
    # routinely involves alcohol or gambling revenue (e.g. cruise operators) or
    # runs conventional insurance. Config-driven GICS sub-industry + one-off
    # ticker exclusions, on top of the Musaffa ratio verdict above.
    tickers, activity_excluded = apply_business_activity_screen(
        tickers, comp, cfg.get("business_activity_screen", {}))
    for e in activity_excluded:
        e["exchange"] = exchange_of.get(e["ticker"], "")
    log.info("Business-activity screen: %d remain, %d excluded", len(tickers), len(activity_excluded))

    # ---------------- BDS / boycott screen ----------------
    # A small, explicitly-sourced, hand-maintained list — see manual_screen.py
    # and config.yaml for scope and caveats.
    tickers, bds_excluded = apply_bds_screen(tickers, cfg.get("bds_screen", {}))
    for e in bds_excluded:
        e["exchange"] = exchange_of.get(e["ticker"], "")
    log.info("BDS screen: %d remain, %d excluded", len(tickers), len(bds_excluded))

    if args.source == "synthetic":
        pdata_all = data_mod.synthetic(tickers + benchmarks, start_px)
        data_mode = "synthetic"
    elif args.source == "snapshot":
        snap = args.snapshot_path or os.path.join(ROOT, "data", "snapshot_prices.parquet")
        pdata_all = data_mod.from_snapshot(snap)
        data_mode = "snapshot"
    else:
        pdata_all = data_mod.download(sorted(set(tickers + benchmarks)), start_px)
        data_mode = "live"

    bench_close = {b: pdata_all.close[b].dropna() for b in benchmarks if b in pdata_all.close}
    screened_set = set(tickers)  # survived Musaffa + business-activity + BDS screens
    stock_cols = [t for t in pdata_all.close.columns if t not in benchmarks and t in screened_set]
    pdata = data_mod.PriceData(pdata_all.close[stock_cols], pdata_all.high[stock_cols],
                               pdata_all.low[stock_cols]).usable()
    close = pdata.close
    log.info("price panel: %d tickers x %d days (%s -> %s)", close.shape[1], close.shape[0],
             close.index[0].date(), close.index[-1].date())

    # ---------------- sectors (for diversification caps) ----------------
    sectors = load_sectors(sector_path, list(close.columns), refresh=args.source == "yfinance")

    # ---------------- precompute signals ----------------
    pre = {("sig", k): fn(close) for k, fn in SIGNALS.items()}
    pre["vol"] = ann_vol(close)
    pre["atr"] = atr(pdata.high, pdata.low, close, 22)

    start_bt = cfg["start_backtest"]
    cost_bps = float(cfg["cost_bps_per_side"])
    atr_mult = float(cfg["atr_multiple"])
    sel_cfg = cfg["selector"]
    variants = [Variant(s, st) for s in SIGNALS for st in (False, True)]

    tracks_payload = {}
    leaderboard_rows = []
    meta_months_ref = None

    specs = {key: TrackSpec.from_config(key, tcfg) for key, tcfg in cfg["tracks"].items()}

    for key, spec in specs.items():
        log.info("track %s: %d variants (n=%d, %s, sector cap=%s, vol screen=%s, stops %.0f–%.0f%%)",
                 key, len(variants), spec.n, spec.weighting, spec.max_per_sector,
                 spec.vol_screen_pct, 100 * spec.stop_min_pct, 100 * spec.stop_max_pct)
        results = {}
        for v in variants:
            res = run_variant(pdata, v, spec, start_bt, cost_bps, atr_mult, sectors, pre)
            results[v.name] = res
        vm = pd.DataFrame({name: r.monthly for name, r in results.items()}).sort_index()
        sel = walk_forward(vm, sel_cfg["window_months"], sel_cfg["min_months"],
                           sel_cfg["switch_margin"], sel_cfg["default_variant"])
        meta = sel.meta_monthly.dropna()
        meta_months_ref = meta.index if meta_months_ref is None else meta_months_ref

        # held/new status: portfolio of the month that just ended
        pairs = rebalance_schedule(close.index, start_bt)
        prev_sd = pairs[-1][0]
        prev_sig = pre[("sig", sel.selections.iloc[-1].partition("+")[0])]
        prev_set = set(select_targets(prev_sig.loc[prev_sd], close.loc[prev_sd],
                                      pre["vol"].loc[prev_sd], spec, sectors).index)

        live_sig = sel.live_variant.partition("+")[0]
        picks = current_picks(pdata, live_sig, spec, atr_mult, sectors, prev_set, pre)
        if len(picks):
            picks["exchange"] = picks["ticker"].map(exchange_of).fillna("")
        labels, values = equity_points(meta)
        cash_pct = max(0.0, 1.0 - float(picks.weight.sum())) if len(picks) else 1.0
        tracks_payload[key] = {
            "label": spec.label,
            "blurb": spec.blurb,
            "live_variant": sel.live_variant,
            "live_label": pretty(sel.live_variant),
            "picks": picks.to_dict(orient="records"),
            "cash_pct": round(cash_pct, 4),
            "stop_band": [spec.stop_min_pct, spec.stop_max_pct],
            "max_per_sector": spec.max_per_sector,
            "sector_mix": (picks.groupby("sector").weight.sum().round(4).sort_values(ascending=False).to_dict()
                           if len(picks) else {}),
            "metrics": summarize(meta),
            "equity": {"labels": labels, "values": values},
            "stop_exits": results[sel.live_variant].stop_exits,
            "recent_selections": {str(k): v for k, v in sel.selections.tail(6).items()},
        }
        for _, r in sel.leaderboard.iterrows():
            leaderboard_rows.append({
                "track": key.capitalize(), "variant": r["variant"], "label": pretty(r["variant"]),
                "trailing_sortino": None if not np.isfinite(r["trailing_sortino"]) else round(float(r["trailing_sortino"]), 3),
                "live": bool(r["live"]),
            })
        log.info("track %s live variant: %s | months=%d | stop_exits(live)=%d",
                 key, sel.live_variant, len(meta), results[sel.live_variant].stop_exits)

    # ---------------- benchmarks ----------------
    bench_payload = {}
    for b, s in bench_close.items():
        m, _ = bench_monthly(s, close.index, start_bt)
        m = m.reindex(meta_months_ref).dropna()
        lb, vv = equity_points(m)
        bench_payload[b] = {"metrics": summarize(m), "equity": {"labels": lb, "values": vv}}

    # ---------------- payload & outputs ----------------
    as_of = close.index[-1].date().isoformat()
    period = f"{meta_months_ref[0].strftime('%b %Y')} – {meta_months_ref[-1].strftime('%b %Y')}"
    payload = {
        "as_of": as_of,
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "period": period,
        "cost_bps": cost_bps,
        "universe_size": int(close.shape[1]),
        "universe_funds": list(funds),
        "sector_count": int(sectors[sectors != "Unknown"].nunique()),
        "data_mode": data_mode,
        "track_order": list(specs),
        "compliance": {
            "source": "Musaffa",
            "checked": len(tickers) + len(musaffa_excluded) + len(activity_excluded) + len(bds_excluded),
            "compliant": len(tickers) + len(activity_excluded) + len(bds_excluded),
            "excluded_counts": excl_counts,
            "excluded": sorted(musaffa_excluded, key=lambda e: e["ticker"]),
        },
        "business_activity_screen": {
            "excluded_subindustries": cfg.get("business_activity_screen", {}).get("excluded_subindustries", []),
            "excluded": sorted(activity_excluded, key=lambda e: e["ticker"]),
        },
        "bds_screen": {
            "enabled": bool(cfg.get("bds_screen", {}).get("enabled", True)),
            "excluded": sorted(bds_excluded, key=lambda e: e["ticker"]),
        },
        "tracks": tracks_payload,
        "benchmarks": bench_payload,
        "leaderboard": leaderboard_rows,
    }
    report.build_all(payload, docs_dir, hist_dir, cfg["site_title"])
    log.info("outputs written: docs/index.html, docs/picks.md, docs/picks.txt, "
             "docs/data.json, history/picks.csv")
    for key in tracks_payload:
        t = tracks_payload[key]
        log.info("%s: %s | CAGR %s | Sharpe %s", key, t["live_label"],
                 t["metrics"].get("cagr"), t["metrics"].get("sharpe"))


if __name__ == "__main__":
    sys.exit(main())
