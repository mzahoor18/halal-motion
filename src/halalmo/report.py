"""Output layer: static dashboard (docs/index.html), shareable picks files
(docs/picks.md, docs/picks.txt), machine-readable docs/data.json, and an
append-only history log (history/picks.csv)."""
from __future__ import annotations
import json
import os
import datetime as dt
import pandas as pd

DISCLAIMER = ("Educational project by a private individual — not investment advice, "
              "not a solicitation. Backtested results use today's fund holdings applied "
              "historically (survivorship bias) and assumed costs; live results will differ. "
              "Past performance never guarantees future results. Do your own research.")


def build_all(payload: dict, docs_dir: str, history_dir: str, title: str) -> None:
    os.makedirs(docs_dir, exist_ok=True)
    os.makedirs(history_dir, exist_ok=True)
    with open(os.path.join(docs_dir, "data.json"), "w") as f:
        json.dump(payload, f, indent=1)
    html = TEMPLATE.replace("__TITLE__", title) \
                   .replace("__DATA__", json.dumps(payload)) \
                   .replace("__DISCLAIMER__", DISCLAIMER)
    with open(os.path.join(docs_dir, "index.html"), "w") as f:
        f.write(html)
    with open(os.path.join(docs_dir, ".nojekyll"), "w") as f:
        f.write("")
    _picks_files(payload, docs_dir, title)
    _append_history(payload, history_dir)


def _fmt_pct(x, digits=1):
    try:
        return f"{100 * float(x):+.{digits}f}%"
    except (TypeError, ValueError):
        return "–"


def _track_keys(p: dict) -> list[str]:
    return p.get("track_order") or list(p["tracks"])


def _picks_files(p: dict, docs_dir: str, title: str) -> None:
    nm = dt.date.fromisoformat(p["as_of"]) + dt.timedelta(days=4)
    month_lbl = nm.strftime("%B %Y")
    md = [f"# {title} — picks for {month_lbl}",
          f"_As of {p['as_of']} close · educational project, not investment advice._", ""]
    txt = [f"{title} — {month_lbl} picks (as of {p['as_of']})", ""]
    for key in _track_keys(p):
        tr = p["tracks"][key]
        band = tr.get("stop_band", [0.05, 0.15])
        md += [f"## {tr['label']}", f"Live model: **{tr['live_label']}** · stop band "
               f"{band[0] * 100:.0f}–{band[1] * 100:.0f}%", "",
               "| # | Ticker | Sector | Weight | Last | Sell if it falls to | |",
               "|---|--------|--------|--------|------|---------------------|---|"]
        txt.append(f"{tr['label']}  [model: {tr['live_label']}]")
        for i, row in enumerate(tr["picks"], 1):
            tag = {"held": "held", "new": "NEW", "breached": "STOP ALREADY HIT"}[row["status"]]
            drop = row.get("stop_drop_pct", 0.0)
            md.append(f"| {i} | {row['ticker']} | {row.get('sector', '–')} | "
                      f"{row['weight'] * 100:.1f}% | ${row['price']:.2f} | "
                      f"${row['stop']:.2f} (−{drop * 100:.1f}%) | {tag} |")
            txt.append(f"  {i:>2}. {row['ticker']:<6} {row['weight'] * 100:4.1f}%  "
                       f"last ${row['price']:.2f}  sell at ${row['stop']:.2f} "
                       f"(−{drop * 100:.1f}%)  [{tag}]")
        if tr.get("cash_pct", 0) > 0.005:
            md.append(f"| | CASH | – | {tr['cash_pct'] * 100:.1f}% | | | not enough "
                      f"positive-momentum names |")
            txt.append(f"      CASH   {tr['cash_pct'] * 100:4.1f}%  (not enough positive-momentum names)")
        m, b = tr["metrics"], p["benchmarks"].get("SPY", {}).get("metrics", {})
        md += ["", f"Backtest since 2020: CAGR {_fmt_pct(m.get('cagr'))} · Sharpe "
               f"{m.get('sharpe', '–')} · Max DD {_fmt_pct(m.get('max_drawdown'))} "
               f"(SPY over same span: CAGR {_fmt_pct(b.get('cagr'))}, Sharpe {b.get('sharpe', '–')})", ""]
        txt.append("")
    md += ["---", f"_{DISCLAIMER}_"]
    txt += ["Sell levels are advisory trailing stops, capped at 15% below the recent high.",
            "The bracketed % is how far the stock must fall from today's price to trigger it.",
            "Educational only — not investment advice."]
    with open(os.path.join(docs_dir, "picks.md"), "w") as f:
        f.write("\n".join(md) + "\n")
    with open(os.path.join(docs_dir, "picks.txt"), "w") as f:
        f.write("\n".join(txt) + "\n")


def _append_history(p: dict, history_dir: str) -> None:
    path = os.path.join(history_dir, "picks.csv")
    cols = ("ticker", "sector", "weight", "price", "stop", "stop_drop_pct", "status")
    rows = []
    for key in _track_keys(p):
        tr = p["tracks"][key]
        for r in tr["picks"]:
            rows.append({"run_date": p["as_of"], "track": key, "variant": tr["live_variant"],
                         **{c: r.get(c) for c in cols}})
    df = pd.DataFrame(rows)
    if os.path.exists(path):
        old = pd.read_csv(path)
        old = old[old.run_date != p["as_of"]]  # idempotent re-runs
        df = pd.concat([old, df], ignore_index=True)
    df.to_csv(path, index=False)


# --------------------------------------------------------------------------
TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<meta name="description" content="Monthly halal momentum picks from the SPUS + MNZL universe — three risk sleeves, an educational, adaptive, walk-forward system.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{
  --bg:#0f1e1b; --bg2:#0b1715; --card:#152a24; --card2:#122420; --line:#24463c;
  --text:#e9f2ec; --muted:#98b3a8; --faint:#6d8a7f;
  --gold:#d9ac33; --gold-dim:#8a6c1c; --jade:#5fcb92; --jade-dim:#2c6d4e;
  --sky:#7fb3d5; --sky-dim:#38607a; --rose:#e0685e;
  --mono:'IBM Plex Mono',ui-monospace,monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{animation:none!important;transition:none!important}}
body{background:var(--bg);color:var(--text);font:16px/1.6 'IBM Plex Sans',system-ui,sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--jade)}
.wrap{max-width:1180px;margin:0 auto;padding:0 20px}
/* header with girih lattice signature */
header{position:relative;border-bottom:1px solid var(--line);overflow:hidden;background:var(--bg2)}
.lattice{position:absolute;inset:0;opacity:.16;pointer-events:none}
.head-inner{position:relative;padding:56px 0 40px}
.eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.22em;text-transform:uppercase;color:var(--faint)}
h1{font-family:'Fraunces',serif;font-weight:600;font-size:clamp(34px,5.5vw,52px);line-height:1.08;margin:10px 0 8px}
h1 .thin{color:var(--jade)}
.sub{color:var(--muted);max-width:64ch}
.asof{margin-top:22px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.chip{font-family:var(--mono);font-size:12.5px;border:1px solid var(--line);border-radius:999px;padding:5px 12px;color:var(--muted);background:rgba(0,0,0,.18)}
.chip b{color:var(--text);font-weight:500}
.chip.gold{border-color:var(--gold-dim)} .chip.gold b{color:var(--gold)}
.chip.jade{border-color:var(--jade-dim)} .chip.jade b{color:var(--jade)}
.chip.sky{border-color:var(--sky-dim)} .chip.sky b{color:var(--sky)}
.ribbon{background:#1c1710;border-top:1px solid #3d3115;border-bottom:1px solid #3d3115;color:#d8c185;font-size:13.5px;padding:10px 0}
section{padding:44px 0 6px}
h2{font-family:'Fraunces',serif;font-weight:500;font-size:26px;margin-bottom:4px}
.kicker{font-family:var(--mono);font-size:11.5px;letter-spacing:.2em;text-transform:uppercase;color:var(--faint);margin-bottom:6px}
.lede{color:var(--muted);max-width:74ch;margin-bottom:22px}
/* glossary term markers + floating tooltip */
.term{border-bottom:1px dotted currentColor;cursor:help;outline:none}
.term:focus-visible{outline:2px solid var(--jade);outline-offset:2px;border-radius:2px}
.tip{position:fixed;display:none;z-index:200;max-width:min(320px,80vw);background:#08110f;
  border:1px solid var(--jade-dim);border-radius:10px;padding:11px 13px;font-size:13.5px;
  line-height:1.5;color:var(--text);box-shadow:0 10px 30px rgba(0,0,0,.55)}
.tip b{display:block;font-family:var(--mono);font-size:11.5px;letter-spacing:.12em;
  text-transform:uppercase;color:var(--jade);margin-bottom:5px;font-weight:500}
/* picks */
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;align-items:start}
@media(max-width:980px){.cards{grid-template-columns:1fr}}
.card{background:linear-gradient(160deg,var(--card),var(--card2));border:1px solid var(--line);border-radius:14px;padding:20px 18px 14px}
.card.gold{border-top:3px solid var(--gold)} .card.jade{border-top:3px solid var(--jade)}
.card.sky{border-top:3px solid var(--sky)}
.card h3{font-family:'Fraunces',serif;font-weight:500;font-size:21px}
.card .risk{font-family:var(--mono);font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--faint)}
.card .meta{font-size:12.5px;color:var(--muted);margin:8px 0 4px}
.card .meta b{color:var(--text);font-weight:500}
.card .blurb{font-size:13px;color:var(--muted);margin:8px 0 14px}
.rules{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}
.rule{font-family:var(--mono);font-size:10.5px;border:1px solid var(--line);border-radius:5px;padding:2px 7px;color:var(--muted)}
table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:13px}
thead th{text-align:right;color:var(--faint);font-weight:400;font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;padding:0 6px 8px;border-bottom:1px solid var(--line)}
thead th:first-child,tbody td:first-child{text-align:left;padding-left:2px}
tbody td{padding:7px 6px;text-align:right;border-bottom:1px dashed rgba(36,70,60,.55);vertical-align:top}
tbody tr:last-child td{border-bottom:none}
td.tick{font-weight:500;color:var(--text)}
td.tick .sec{display:block;font-size:10px;color:var(--faint);letter-spacing:.02em;font-weight:400}
td .new{font-size:9.5px;letter-spacing:.1em;color:var(--bg);background:var(--jade);border-radius:4px;padding:1px 5px;margin-left:5px;vertical-align:1px}
td .brch{font-size:9.5px;letter-spacing:.1em;color:var(--bg);background:var(--rose);border-radius:4px;padding:1px 5px;margin-left:5px;vertical-align:1px}
td.stop{color:var(--rose)}
td.stop .drop{display:block;font-size:10.5px;color:var(--faint)}
tr.cash td{color:var(--sky)}
/* sector mix bar */
.mix{margin-top:14px}
.mixbar{display:flex;height:7px;border-radius:4px;overflow:hidden;background:#0a1614}
.mixbar span{display:block}
.mixkey{display:flex;flex-wrap:wrap;gap:4px 10px;margin-top:7px;font-size:10.5px;color:var(--faint);font-family:var(--mono)}
.mixkey i{display:inline-block;width:7px;height:7px;border-radius:2px;margin-right:4px;vertical-align:0}
/* chart + metrics */
.panel{background:var(--card2);border:1px solid var(--line);border-radius:14px;padding:22px}
.chart-box{height:440px}
@media(max-width:640px){.chart-box{height:320px}}
.legend-note{font-size:12.5px;color:var(--faint);margin-top:10px}
.mtable{overflow-x:auto}
.mtable table{min-width:700px}
.mtable td.name{text-align:left;color:var(--text)}
.pos{color:var(--jade)} .neg{color:var(--rose)}
/* how it works */
.how p{color:var(--muted);max-width:78ch;margin-bottom:14px}
.how b{color:var(--text);font-weight:600}
details{border:1px solid var(--line);border-radius:12px;background:var(--card2);margin-top:18px}
summary{cursor:pointer;padding:14px 18px;font-family:var(--mono);font-size:13px;color:var(--muted)}
summary:focus-visible{outline:2px solid var(--jade);outline-offset:2px}
details .inner{padding:0 18px 16px}
.live-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--jade);margin-right:6px}
.glossary{columns:2;column-gap:28px}
@media(max-width:720px){.glossary{columns:1}}
.glossary dt{font-family:var(--mono);font-size:12.5px;color:var(--gold);margin-top:12px}
.glossary dd{font-size:13.5px;color:var(--muted);break-inside:avoid;margin-bottom:2px}
footer{margin-top:56px;border-top:1px solid var(--line);padding:26px 0 48px;color:var(--faint);font-size:13px}
footer p{max-width:80ch;margin-bottom:10px}
</style>
</head>
<body>
<header>
  <svg class="lattice" width="100%" height="100%" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
    <defs><pattern id="girih" width="84" height="84" patternUnits="userSpaceOnUse">
      <g fill="none" stroke="#3f7a63" stroke-width="1">
        <path d="M42 4 L54 30 L80 42 L54 54 L42 80 L30 54 L4 42 L30 30 Z"/>
        <path d="M42 18 L50 34 L66 42 L50 50 L42 66 L34 50 L18 42 L34 34 Z"/>
        <circle cx="42" cy="42" r="5"/>
        <path d="M0 0 L12 6 M84 0 L72 6 M0 84 L12 78 M84 84 L72 78"/>
      </g></pattern></defs>
    <rect width="100%" height="100%" fill="url(#girih)"/>
  </svg>
  <div class="wrap head-inner">
    <div class="eyebrow">SPUS + MNZL universe · monthly rebalance · walk-forward</div>
    <h1>__TITLE__<span class="thin">.</span></h1>
    <p class="sub">An adaptive <span class="term" data-term="momentum">momentum</span> system over the
    halal-screened stocks held by the SPUS and MNZL ETFs. Every month it re-tests six pre-registered
    models <span class="term" data-term="oos">out-of-sample</span> and follows the current leader —
    in three sleeves: <b>Aggressive</b>, <b>Balanced</b> and <b>Conservative</b>.</p>
    <p class="sub" style="margin-top:10px;font-size:14px">Dotted underlines explain themselves —
    hover or tap any term you don't recognise.</p>
    <div class="asof" id="asof"></div>
  </div>
</header>
<div class="ribbon"><div class="wrap">⚠︎ __DISCLAIMER__</div></div>

<main class="wrap">
<section id="picks">
  <div class="kicker">This month</div>
  <h2>Current picks</h2>
  <p class="lede">Buy list at the latest close. Each name carries a suggested
  <span class="term" data-term="stop">sell level</span> — a
  <span class="term" data-term="trailing">trailing stop</span> that never sits more than 15% below the
  recent high. The bracketed percentage is how far the stock has to fall <em>from today's price</em>
  before you'd sell it. A brand-new pick gets the full band; a name that's already pulled back from
  its high shows a smaller number, because it is that much closer to the exit.</p>
  <div class="cards" id="cards"></div>
</section>

<section id="performance">
  <div class="kicker">Track record (backtest)</div>
  <h2>Growth of $100 since 2020</h2>
  <p class="lede"><span class="term" data-term="walkforward">Walk-forward</span>: at every point the
  system only knew the past. <span class="term" data-term="benchmark">Benchmarks</span>: SPY
  (S&amp;P 500) and QQQ (Nasdaq-100) are dividend-adjusted ETFs; ^DJI is the Dow Jones price index.
  <span class="term" data-term="logscale">Log scale</span>.</p>
  <div class="panel"><div class="chart-box"><canvas id="eq"></canvas></div>
  <div class="legend-note" id="chartnote"></div></div>
</section>

<section id="metrics">
  <div class="kicker">Scorecard</div>
  <h2>Risk &amp; return</h2>
  <p class="lede">Every column header explains itself on hover. Short version: the first column is
  how fast money grew, the middle columns are how bumpy the ride was, and
  <span class="term" data-term="maxdd">Max DD</span> is the worst peak-to-trough fall you'd have had
  to sit through.</p>
  <div class="panel mtable" id="mtable"></div>
</section>

<section id="how" class="how">
  <div class="kicker">Under the hood</div>
  <h2>How it works</h2>
  <p><b><span class="term" data-term="universe">Universe</span>.</b> The combined holdings of SPUS
  (S&amp;P 500 Sharia Industry Exclusions) and MNZL (Manzil US Equity), refreshed monthly from the
  issuers' published holdings files — currently <span id="unisize"></span> stocks across
  <span id="seccount"></span> sectors.</p>
  <p><b>Signals.</b> Six pre-registered momentum definitions compete:
  <span class="term" data-term="mom121">12-1</span>, 6-month and 3-month momentum,
  <span class="term" data-term="sroc">smoothed rate of change</span> over 3 and 6 months, and
  <span class="term" data-term="riskadj">volatility-adjusted 12-1</span> — each with and without stops.</p>
  <p><b>Adaptive selection.</b> Each month, every variant's trailing 24 months of
  <span class="term" data-term="oos">out-of-sample</span> returns are scored by
  <span class="term" data-term="sortino">Sortino ratio</span>; the leader runs the next month. A
  challenger must beat the incumbent by a clear margin to take over, and the menu itself never grows —
  two deliberate guards against <span class="term" data-term="overfit">overfitting</span>. The first
  year runs the academic default (12-1 momentum) while history accrues.</p>
  <p><b>The three sleeves.</b> <b>Aggressive</b> holds the 8 strongest names with no sector limits and
  the widest stops. <b>Balanced</b> holds 20 with a
  <span class="term" data-term="sectorcap">cap of 3 per sector</span>. <b>Conservative</b> ranks only
  the calmest half of the universe by <span class="term" data-term="vol">volatility</span>, holds 25
  names capped at 3 per sector, keeps the tightest stops, and sits in
  <span class="term" data-term="cash">cash</span> rather than forcing picks when too few names have
  positive momentum. All three size positions by
  <span class="term" data-term="invvol">inverse volatility</span>.</p>
  <p><b>Execution model.</b> Signals form at month-end close; trades assume the first close of the new
  month, with 0.10% (<span class="term" data-term="bps">10 bps</span>) per-side costs.</p>
  <details><summary><span class="live-dot"></span>Model leaderboard — trailing 24-month Sortino by variant</summary>
    <div class="inner mtable" id="leader"></div></details>
  <details><summary>Full glossary — every term on this page, in plain English</summary>
    <div class="inner"><dl class="glossary" id="gloss"></dl></div></details>
</section>
</main>

<footer><div class="wrap">
  <p id="fnote1"></p>
  <p><b>Known limitations, stated plainly:</b> the backtest applies today's SPUS + MNZL holdings to the
  past (<span class="term" data-term="survivorship">survivorship bias</span>), uses a 0%
  <span class="term" data-term="rf">risk-free rate</span> in ratios, models stops on closing prices,
  and ignores taxes. Momentum strategies historically endure sharp drawdowns when trends reverse.
  Nothing here is investment, legal, or tax advice.</p>
  <p>Built with an open pipeline: holdings → six momentum signals → walk-forward selector →
  monthly picks. Regenerated automatically on the 1st of each month.</p>
</div></footer>

<script>
const DATA = __DATA__;
const fmtP=(x,d=1)=>x==null||isNaN(x)?"–":(100*x).toFixed(d)+"%";
const fmtS=(x,d=2)=>x==null||isNaN(x)?"–":(+x).toFixed(d);
const cls=x=>x>=0?"pos":"neg";
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

/* ---------------- plain-English glossary ---------------- */
const GLOSSARY={
 momentum:["Momentum","The tendency of stocks that have gone up over the last several months to keep going up for a while longer. This system buys recent winners and sells them when the trend breaks."],
 mom121:["12-1 momentum","Return over the last 12 months, ignoring the most recent month. Skipping that month avoids a well-known short-term bounce-back effect that would otherwise muddy the signal."],
 sroc:["SROC","Smoothed Rate of Change. The same idea as momentum, but the price is smoothed first (a moving average) so one wild day doesn't decide whether a stock is in an uptrend."],
 riskadj:["Volatility-adjusted momentum","Momentum divided by how jumpy the stock is. A steady 30% gain scores better than a wild 30% gain, because it's more likely to be a real trend than luck."],
 vol:["Volatility","How much a price bounces around, day to day. High volatility means bigger swings in both directions — more potential gain, more potential pain."],
 invvol:["Inverse-volatility weighting","Calmer stocks get a bigger share of the money, jumpier stocks a smaller one. The aim is for every holding to contribute a similar amount of risk, instead of one wild stock dominating the portfolio."],
 stop:["Sell level (stop-loss)","A price at which you'd sell to cut a loss. If the stock closes below it, you're out. It's a discipline device: it decides in advance how much you're willing to lose on a position."],
 trailing:["Trailing stop","A sell level that rises as the stock rises but never falls. It locks in gains on the way up while still capping the loss if the trend reverses. Here it's set below the highest close since you bought, capped at 15%."],
 atr:["ATR","Average True Range — the average size of a stock's daily price swing over the last 22 trading days. Used to set stops: a jumpy stock needs more room before you call the trend broken."],
 sectorcap:["Sector cap","A hard limit on how many holdings can come from one industry group (technology, healthcare, energy…). It stops the whole portfolio betting on a single corner of the market at the same time."],
 cash:["Cash allocation","Money deliberately left uninvested. The Conservative sleeve does this when too few stocks have positive momentum — it would rather hold cash than buy something falling."],
 universe:["Universe","The list of stocks the system is allowed to choose from — here, everything held by the SPUS and MNZL halal ETFs, so the whole selection is already Sharia-screened."],
 rebalance:["Rebalance","The monthly reset: sell what's no longer in the list, buy what is, and reset each position to its target size."],
 bps:["Basis points (bps)","One basis point is 0.01%. A 10 bps cost per side means every purchase and every sale is assumed to cost 0.10% of the amount traded, covering commissions and spread."],
 cagr:["CAGR","Compound Annual Growth Rate — the steady yearly rate that would take you from the starting value to the ending value. It smooths out the good and bad years into one number."],
 sharpe:["Sharpe ratio","Return per unit of bumpiness. Higher is better. Roughly: under 1 is unremarkable, above 1 is good, above 2 is excellent. It penalises upside and downside swings equally."],
 sortino:["Sortino ratio","Like Sharpe, but only counts downward swings as risk — because nobody minds a portfolio that jumps up. This is the score the system uses to pick which model runs each month."],
 maxdd:["Maximum drawdown","The worst peak-to-trough fall over the whole period. If it says −40%, at some point the portfolio was worth 40% less than its previous high — and you'd have had to hold on through it."],
 calmar:["Calmar ratio","Annual return divided by the worst drawdown. It answers: how much growth did I get for the deepest pain I had to endure? Higher is better."],
 winrate:["Winning months","The share of months that finished positive. Useful context, but not decisive on its own — a strategy can win often and still lose badly on the rare bad month."],
 totalret:["Total return","The full cumulative gain over the whole period, not annualised. A 200% total return means the money tripled."],
 walkforward:["Walk-forward testing","Testing a strategy the way you'd actually live it: at each point in the past, the system is only shown data available up to that date. It prevents the classic cheat of using knowledge from the future."],
 oos:["Out-of-sample","Results from data the model had never seen when it made its choice. In-sample results are easy to make look brilliant; out-of-sample results are the only kind worth anything."],
 overfit:["Overfitting","Tuning a strategy so precisely to past data that it captures noise instead of a real pattern — and then falls apart in the real world. Guards here: a fixed six-model menu and a hysteresis rule so the system can't chase noise."],
 survivorship:["Survivorship bias","The backtest applies today's fund holdings to the past. Companies that failed and left the fund never appear, so historic results look better than reality would have been. Treat the numbers as a comparison between methods, not a promise."],
 benchmark:["Benchmark","A yardstick to compare against. SPY tracks the S&P 500, QQQ the Nasdaq-100, ^DJI the Dow Jones. Beating a benchmark is the point of active picking; not beating it means an index fund would have served you better."],
 logscale:["Log scale","On this chart, equal vertical distances mean equal percentage moves. A doubling from $100 to $200 looks the same size as $200 to $400 — which is the fair way to compare growth over many years."],
 rf:["Risk-free rate","The return you could earn with no risk at all. Ratios here assume 0%, which is conservative in a positive-rate world — it makes the reported Sharpe and Sortino slightly flattering."]
};
/* floating tooltip, positioned in viewport coords so tables can't clip it */
const TIP=document.createElement("div");TIP.className="tip";TIP.setAttribute("role","tooltip");
document.body.appendChild(TIP);
let tipFor=null;
function showTip(el){
  const g=GLOSSARY[el.dataset.term]; if(!g){return;}
  TIP.innerHTML=`<b>${esc(g[0])}</b>${esc(g[1])}`;
  TIP.style.visibility="hidden";TIP.style.display="block";TIP.style.left="0px";TIP.style.top="0px";
  const r=el.getBoundingClientRect(),w=TIP.offsetWidth,h=TIP.offsetHeight;
  let left=r.left+r.width/2-w/2;
  left=Math.max(8,Math.min(left,window.innerWidth-w-8));
  let top=r.top-h-10; if(top<8) top=r.bottom+10;
  TIP.style.left=left+"px";TIP.style.top=top+"px";TIP.style.visibility="visible";
  tipFor=el;
}
function hideTip(){TIP.style.display="none";tipFor=null;}
document.addEventListener("mouseover",e=>{const t=e.target.closest(".term");if(t){showTip(t);}else if(tipFor){hideTip();}});
document.addEventListener("focusin",e=>{const t=e.target.closest(".term");t?showTip(t):hideTip();});
document.addEventListener("focusout",hideTip);
document.addEventListener("click",e=>{const t=e.target.closest(".term");
  if(!t){hideTip();return;} e.preventDefault(); showTip(t);});
document.addEventListener("keydown",e=>{if(e.key==="Escape")hideTip();});
window.addEventListener("scroll",()=>{if(tipFor)hideTip();},{passive:true});
document.querySelectorAll(".term").forEach(el=>{el.tabIndex=0;el.setAttribute("aria-label",
  (GLOSSARY[el.dataset.term]||["",""])[0]+": "+(GLOSSARY[el.dataset.term]||["",""])[1]);});
/* full glossary list */
document.getElementById("gloss").innerHTML=Object.values(GLOSSARY)
 .sort((a,b)=>a[0].localeCompare(b[0]))
 .map(([t,d])=>`<dt>${esc(t)}</dt><dd>${esc(d)}</dd>`).join("");

/* ---------------- header chips ---------------- */
const ORDER=DATA.track_order||Object.keys(DATA.tracks);
const COLORS={aggressive:"gold",balanced:"jade",conservative:"sky"};
const LINE={aggressive:"#d9ac33",balanced:"#5fcb92",conservative:"#7fb3d5"};
const RISK={aggressive:"Higher risk",balanced:"Medium risk",conservative:"Lower risk"};
const cap=s=>s.charAt(0).toUpperCase()+s.slice(1);
document.getElementById("asof").innerHTML=`<span class="chip">as of <b>${esc(DATA.as_of)}</b></span>`
+ORDER.map(k=>`<span class="chip ${COLORS[k]||""}">${cap(k)} model <b>${esc(DATA.tracks[k].live_label)}</b></span>`).join("")
+`<span class="chip">universe <b>${DATA.universe_size}</b> stocks</span>`
+(DATA.data_mode==="synthetic"?`<span class="chip" style="border-color:#7a3f3f"><b style="color:#e0685e">synthetic data — demo only</b></span>`:
  DATA.data_mode==="snapshot"?`<span class="chip"><b>real prices · validation build to ${esc(DATA.as_of)}</b></span>`:"");
document.getElementById("unisize").textContent=DATA.universe_size;
document.getElementById("seccount").textContent=DATA.sector_count||"11";

/* ---------------- picks cards ---------------- */
const SECCOL=["#5fcb92","#d9ac33","#7fb3d5","#c98f6d","#9a8fbf","#6fbfae","#cf7f9c","#8fae5c","#d0a96a","#7f9fd5","#b98fc9","#8a9a95"];
const secColor=(()=>{const m={};let i=0;return s=>(m[s]??=SECCOL[i++%SECCOL.length]);})();
const cards=document.getElementById("cards");
for(const key of ORDER){
  const t=DATA.tracks[key],color=COLORS[key]||"jade";
  const rows=t.picks.map((r,i)=>`<tr>
    <td class="tick">${i+1}&nbsp; ${esc(r.ticker)}${r.status==="new"?'<span class="new">NEW</span>':r.status==="breached"?'<span class="brch">STOP HIT</span>':""}
      <span class="sec">${esc(r.sector||"")}</span></td>
    <td>${fmtP(r.weight)}</td><td>$${r.price.toFixed(2)}</td>
    <td class="stop">$${r.stop.toFixed(2)}<span class="drop">(−${(100*(r.stop_drop_pct||0)).toFixed(1)}%)</span></td></tr>`).join("")
   +((t.cash_pct||0)>0.005?`<tr class="cash"><td class="tick">— CASH<span class="sec">no forced picks</span></td>
      <td>${fmtP(t.cash_pct)}</td><td>–</td><td>–</td></tr>`:"");
  const mix=Object.entries(t.sector_mix||{});
  const total=mix.reduce((a,[,v])=>a+v,0)||1;
  const mixHTML=mix.length?`<div class="mix">
     <div class="mixbar">${mix.map(([s,v])=>`<span style="width:${100*v/total}%;background:${secColor(s)}" title="${esc(s)} ${fmtP(v)}"></span>`).join("")}</div>
     <div class="mixkey">${mix.map(([s,v])=>`<span><i style="background:${secColor(s)}"></i>${esc(s)} ${fmtP(v,0)}</span>`).join("")}</div></div>`:"";
  const band=t.stop_band||[0.05,0.15];
  const rules=[`${t.picks.length} holdings`,
    t.max_per_sector?`max ${t.max_per_sector}/sector`:"no sector cap",
    `stop ${(100*band[0]).toFixed(0)}–${(100*band[1]).toFixed(0)}% below high`]
    .map(x=>`<span class="rule">${esc(x)}</span>`).join("");
  cards.insertAdjacentHTML("beforeend",`<div class="card ${color}">
    <div class="risk">${esc(RISK[key]||"")}</div>
    <h3>${esc(cap(key))}</h3>
    <div class="blurb">${esc(t.blurb||t.label)}</div>
    <div class="rules">${rules}</div>
    <div class="meta">live model <b>${esc(t.live_label)}</b></div>
    <table aria-label="${esc(key)} picks"><thead><tr><th>Pick</th>
      <th><span class="term" data-term="invvol">Weight</span></th><th>Last</th>
      <th><span class="term" data-term="trailing">Sell at</span></th></tr></thead>
    <tbody>${rows}</tbody></table>${mixHTML}</div>`);
}

/* ---------------- equity chart ---------------- */
const BCOL={SPY:"#8fa0a8",QQQ:"#c98f6d","^DJI":"#9a8fbf",DIA:"#9a8fbf"};
const series=[...ORDER.map(k=>[cap(k),DATA.tracks[k].equity,LINE[k]||"#5fcb92",2.4,false]),
              ...Object.entries(DATA.benchmarks).map(([k,v])=>[k,v.equity,BCOL[k]||"#8fa0a8",1.3,true])
             ].filter(s=>s[1]);
new Chart(document.getElementById("eq"),{type:"line",
 data:{labels:series[0][1].labels,
  datasets:series.map(([label,eq,colorr,w,dash])=>({label,data:eq.values,borderColor:colorr,
    borderWidth:w,pointRadius:0,tension:.25,borderDash:dash?[5,4]:[]}))},
 options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},
  scales:{y:{type:"logarithmic",grid:{color:"rgba(36,70,60,.5)"},ticks:{color:"#98b3a8",callback:v=>"$"+v}},
          x:{grid:{display:false},ticks:{color:"#6d8a7f",maxTicksLimit:9}}},
  plugins:{legend:{labels:{color:"#e9f2ec",boxWidth:18,boxHeight:2}},
   tooltip:{backgroundColor:"#0b1715",borderColor:"#24463c",borderWidth:1,
    callbacks:{label:c=>` ${c.dataset.label}: $${(+c.parsed.y).toFixed(0)}`}}}}});
document.getElementById("chartnote").textContent=
 `Backtest ${DATA.period}. Net of ${DATA.cost_bps} bps per-side costs. Meta-strategy shown: the variant actually selected each month.`;

/* ---------------- metrics table ---------------- */
const M=[...ORDER.map(k=>[cap(k),DATA.tracks[k].metrics]),
 ...Object.entries(DATA.benchmarks).map(([k,v])=>[k,v.metrics])];
const mrows=M.map(([name,m])=>`<tr><td class="name">${esc(name)}</td>
 <td class="${cls(m.cagr)}">${fmtP(m.cagr)}</td><td>${fmtS(m.sharpe)}</td><td>${fmtS(m.sortino)}</td>
 <td>${fmtP(m.ann_vol)}</td><td class="neg">${fmtP(m.max_drawdown)}</td>
 <td>${fmtS(m.calmar)}</td><td>${fmtP(m.win_rate,0)}</td>
 <td class="${cls(m.total_return)}">${fmtP(m.total_return,0)}</td></tr>`).join("");
const TH=(lbl,term)=>`<th><span class="term" data-term="${term}">${lbl}</span></th>`;
document.getElementById("mtable").innerHTML=`<table>
 <thead><tr><th style="text-align:left">Series</th>${TH("CAGR","cagr")}${TH("Sharpe","sharpe")}
 ${TH("Sortino","sortino")}${TH("Vol","vol")}${TH("Max DD","maxdd")}${TH("Calmar","calmar")}
 ${TH("Win mo.","winrate")}${TH("Total","totalret")}</tr></thead>
 <tbody>${mrows}</tbody></table>`;

/* ---------------- leaderboard ---------------- */
const lrows=DATA.leaderboard.map(r=>`<tr><td class="name">${esc(r.track)}</td><td class="name">${esc(r.label)}</td>
 <td>${fmtS(r.trailing_sortino)}</td><td>${r.live?'<span class="live-dot"></span>live':""}</td></tr>`).join("");
document.getElementById("leader").innerHTML=`<table>
 <thead><tr><th style="text-align:left">Track</th><th style="text-align:left">Variant</th>
 <th><span class="term" data-term="sortino">Sortino (24m)</span></th><th></th></tr></thead><tbody>${lrows}</tbody></table>`;

/* re-arm terms created after initial pass */
document.querySelectorAll(".term").forEach(el=>{el.tabIndex=0;});

document.getElementById("fnote1").textContent=`Generated ${DATA.generated}. Data: fund issuer holdings pages + Yahoo Finance adjusted prices.`;
</script>
</body>
</html>
"""
