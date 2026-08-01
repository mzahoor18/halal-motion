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


def _picks_files(p: dict, docs_dir: str, title: str) -> None:
    nm = dt.date.fromisoformat(p["as_of"]) + dt.timedelta(days=4)
    month_lbl = nm.strftime("%B %Y")
    md = [f"# {title} — picks for {month_lbl}",
          f"_As of {p['as_of']} close · educational project, not investment advice._", ""]
    txt = [f"{title} — {month_lbl} picks (as of {p['as_of']})", ""]
    for key in ("focused", "balanced"):
        tr = p["tracks"][key]
        md += [f"## {tr['label']}", f"Live model: **{tr['live_label']}**", "",
               "| # | Ticker | Weight | Last | Suggested stop | |",
               "|---|--------|--------|------|----------------|---|"]
        txt.append(f"{tr['label']}  [model: {tr['live_label']}]")
        for i, row in enumerate(tr["picks"], 1):
            tag = {"held": "held", "new": "NEW", "breached": "STOP ALREADY HIT"}[row["status"]]
            md.append(f"| {i} | {row['ticker']} | {row['weight'] * 100:.1f}% | "
                      f"${row['price']:.2f} | ${row['stop']:.2f} | {tag} |")
            txt.append(f"  {i:>2}. {row['ticker']:<6} {row['weight'] * 100:4.1f}%  "
                       f"last ${row['price']:.2f}  stop ${row['stop']:.2f}  [{tag}]")
        m, b = tr["metrics"], p["benchmarks"].get("SPY", {}).get("metrics", {})
        md += ["", f"Backtest since 2020: CAGR {_fmt_pct(m.get('cagr'))} · Sharpe "
               f"{m.get('sharpe', '–')} · Max DD {_fmt_pct(m.get('max_drawdown'))} "
               f"(SPY over same span: CAGR {_fmt_pct(b.get('cagr'))}, Sharpe {b.get('sharpe', '–')})", ""]
        txt.append("")
    md += ["---", f"_{DISCLAIMER}_"]
    txt += ["Stops are advisory chandelier exits (3 x ATR-22 below the recent high).",
            "Educational only — not investment advice."]
    with open(os.path.join(docs_dir, "picks.md"), "w") as f:
        f.write("\n".join(md) + "\n")
    with open(os.path.join(docs_dir, "picks.txt"), "w") as f:
        f.write("\n".join(txt) + "\n")


def _append_history(p: dict, history_dir: str) -> None:
    path = os.path.join(history_dir, "picks.csv")
    rows = []
    for key in ("focused", "balanced"):
        tr = p["tracks"][key]
        for r in tr["picks"]:
            rows.append({"run_date": p["as_of"], "track": key, "variant": tr["live_variant"],
                         **{k: r[k] for k in ("ticker", "weight", "price", "stop", "status")}})
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
<meta name="description" content="Monthly halal momentum picks from the SPUS universe — an educational, adaptive, walk-forward system.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{
  --bg:#0f1e1b; --bg2:#0b1715; --card:#152a24; --card2:#122420; --line:#24463c;
  --text:#e9f2ec; --muted:#98b3a8; --faint:#6d8a7f;
  --gold:#d9ac33; --gold-dim:#8a6c1c; --jade:#5fcb92; --jade-dim:#2c6d4e;
  --rose:#e0685e; --sky:#7fb3d5;
  --mono:'IBM Plex Mono',ui-monospace,monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{animation:none!important;transition:none!important}}
body{background:var(--bg);color:var(--text);font:16px/1.6 'IBM Plex Sans',system-ui,sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--jade)}
.wrap{max-width:1060px;margin:0 auto;padding:0 20px}
/* header with girih lattice signature */
header{position:relative;border-bottom:1px solid var(--line);overflow:hidden;background:var(--bg2)}
.lattice{position:absolute;inset:0;opacity:.16;pointer-events:none}
.head-inner{position:relative;padding:56px 0 40px}
.eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.22em;text-transform:uppercase;color:var(--faint)}
h1{font-family:'Fraunces',serif;font-weight:600;font-size:clamp(34px,5.5vw,52px);line-height:1.08;margin:10px 0 8px}
h1 .thin{color:var(--jade)}
.sub{color:var(--muted);max-width:62ch}
.asof{margin-top:22px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.chip{font-family:var(--mono);font-size:12.5px;border:1px solid var(--line);border-radius:999px;padding:5px 12px;color:var(--muted);background:rgba(0,0,0,.18)}
.chip b{color:var(--text);font-weight:500}
.chip.gold{border-color:var(--gold-dim)} .chip.gold b{color:var(--gold)}
.chip.jade{border-color:var(--jade-dim)} .chip.jade b{color:var(--jade)}
.ribbon{background:#1c1710;border-top:1px solid #3d3115;border-bottom:1px solid #3d3115;color:#d8c185;font-size:13.5px;padding:10px 0}
section{padding:44px 0 6px}
h2{font-family:'Fraunces',serif;font-weight:500;font-size:26px;margin-bottom:4px}
.kicker{font-family:var(--mono);font-size:11.5px;letter-spacing:.2em;text-transform:uppercase;color:var(--faint);margin-bottom:6px}
.lede{color:var(--muted);max-width:70ch;margin-bottom:22px}
/* picks */
.cards{display:grid;grid-template-columns:1fr 1fr;gap:20px}
@media(max-width:820px){.cards{grid-template-columns:1fr}}
.card{background:linear-gradient(160deg,var(--card),var(--card2));border:1px solid var(--line);border-radius:14px;padding:20px 20px 12px;position:relative}
.card.gold{border-top:3px solid var(--gold)} .card.jade{border-top:3px solid var(--jade)}
.card h3{font-family:'Fraunces',serif;font-weight:500;font-size:21px}
.card .meta{font-size:13px;color:var(--muted);margin:2px 0 14px}
.card .meta b{color:var(--text);font-weight:500}
table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:13.5px}
thead th{text-align:right;color:var(--faint);font-weight:400;font-size:11px;letter-spacing:.08em;text-transform:uppercase;padding:0 8px 8px;border-bottom:1px solid var(--line)}
thead th:first-child,tbody td:first-child{text-align:left;padding-left:2px}
tbody td{padding:7px 8px;text-align:right;border-bottom:1px dashed rgba(36,70,60,.55)}
tbody tr:last-child td{border-bottom:none}
td.tick{font-weight:500;color:var(--text)}
td .new{font-size:10px;letter-spacing:.1em;color:var(--bg);background:var(--jade);border-radius:4px;padding:1px 5px;margin-left:6px;vertical-align:1px}
td .brch{font-size:10px;letter-spacing:.1em;color:var(--bg);background:var(--rose);border-radius:4px;padding:1px 5px;margin-left:6px;vertical-align:1px}
td.stop{color:var(--rose)}
/* chart + metrics */
.panel{background:var(--card2);border:1px solid var(--line);border-radius:14px;padding:22px}
.chart-box{height:420px}
@media(max-width:640px){.chart-box{height:320px}}
.legend-note{font-size:12.5px;color:var(--faint);margin-top:10px}
.mtable{overflow-x:auto}
.mtable table{min-width:640px}
.mtable td.name{text-align:left;color:var(--text)}
.pos{color:var(--jade)} .neg{color:var(--rose)}
/* how it works */
.how p{color:var(--muted);max-width:74ch;margin-bottom:14px}
.how b{color:var(--text);font-weight:600}
details{border:1px solid var(--line);border-radius:12px;background:var(--card2);margin-top:18px}
summary{cursor:pointer;padding:14px 18px;font-family:var(--mono);font-size:13px;color:var(--muted)}
summary:focus-visible{outline:2px solid var(--jade);outline-offset:2px}
details .inner{padding:0 18px 16px}
.live-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--jade);margin-right:6px}
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
    <div class="eyebrow">SPUS universe · monthly rebalance · walk-forward</div>
    <h1>__TITLE__<span class="thin">.</span></h1>
    <p class="sub">An adaptive momentum system over the halal-screened stocks held by the SPUS ETF
    (S&amp;P 500 Sharia Industry Exclusions). Every month it re-tests six pre-registered momentum
    models out-of-sample and follows the current leader — one concentrated portfolio, one diversified.</p>
    <div class="asof" id="asof"></div>
  </div>
</header>
<div class="ribbon"><div class="wrap">⚠︎ __DISCLAIMER__</div></div>

<main class="wrap">
<section id="picks">
  <div class="kicker">This month</div>
  <h2>Current picks</h2>
  <p class="lede">Buy list at the latest close. The suggested stop is a chandelier exit — 3×ATR(22)
  below the highest close since entry — meant as an advisory intramonth safety valve, not a promise.</p>
  <div class="cards" id="cards"></div>
</section>

<section id="performance">
  <div class="kicker">Track record (backtest)</div>
  <h2>Growth of $100 since 2020</h2>
  <p class="lede">Walk-forward: at every point the system only knew the past. Benchmarks: SPY
  (S&amp;P 500) and QQQ (Nasdaq-100) are dividend-adjusted ETFs; ^DJI is the Dow Jones price index.
  Log scale.</p>
  <div class="panel"><div class="chart-box"><canvas id="eq"></canvas></div>
  <div class="legend-note" id="chartnote"></div></div>
</section>

<section id="metrics">
  <div class="kicker">Scorecard</div>
  <h2>Risk &amp; return</h2>
  <div class="panel mtable" id="mtable"></div>
</section>

<section id="how" class="how">
  <div class="kicker">Under the hood</div>
  <h2>How it works</h2>
  <p><b>Universe.</b> The holdings of SPUS — the S&amp;P 500 Sharia Industry Exclusions ETF —
  refreshed monthly from the issuer's published holdings file, currently
  <span id="unisize"></span> stocks.</p>
  <p><b>Signals.</b> Six pre-registered momentum definitions compete: 12-1, 6-month and 3-month
  momentum, smoothed rate of change (SROC) over 3 and 6 months, and volatility-adjusted 12-1 —
  each with and without chandelier stops.</p>
  <p><b>Adaptive selection.</b> Each month, every variant's trailing 24 months of out-of-sample
  returns are scored by Sortino ratio; the leader runs the next month. A challenger must beat the
  incumbent by a clear margin to take over, and the menu itself never grows — two deliberate guards
  against overfitting. The first year runs the academic default (12-1 momentum) while history accrues.</p>
  <p><b>Execution model.</b> Signals form at month-end close; trades assume the first close of the
  new month, with 0.10% per-side costs. Focused holds the top 8 equal-weighted; Balanced holds the
  top 20 weighted by inverse volatility.</p>
  <details><summary><span class="live-dot"></span>Model leaderboard — trailing 24-month Sortino by variant</summary>
    <div class="inner mtable" id="leader"></div></details>
</section>
</main>

<footer><div class="wrap">
  <p id="fnote1"></p>
  <p><b>Known limitations, stated plainly:</b> the backtest applies today's SPUS holdings to the
  past (survivorship bias), uses a 0% risk-free rate in ratios,
  models stops on closing prices, and ignores taxes. Momentum strategies historically endure sharp
  drawdowns when trends reverse. Nothing here is investment, legal, or tax advice.</p>
  <p>Built with an open pipeline: holdings → six momentum signals → walk-forward selector →
  monthly picks. Regenerated automatically on the 1st of each month.</p>
</div></footer>

<script>
const DATA = __DATA__;
const fmtP=(x,d=1)=>x==null||isNaN(x)?"–":(100*x).toFixed(d)+"%";
const fmtS=(x,d=2)=>x==null||isNaN(x)?"–":(+x).toFixed(d);
const cls=x=>x>=0?"pos":"neg";

// header chips
const asof=document.getElementById("asof");
asof.innerHTML=`<span class="chip">as of <b>${DATA.as_of}</b></span>
<span class="chip gold">Focused model <b>${DATA.tracks.focused.live_label}</b></span>
<span class="chip jade">Balanced model <b>${DATA.tracks.balanced.live_label}</b></span>
<span class="chip">universe <b>${DATA.universe_size}</b> stocks</span>`
+(DATA.data_mode==="synthetic"?`<span class="chip" style="border-color:#7a3f3f"><b style="color:#e0685e">synthetic data — demo only</b></span>`:
  DATA.data_mode==="snapshot"?`<span class="chip"><b>real prices · validation build to ${DATA.as_of}</b></span>`:"");
document.getElementById("unisize").textContent=DATA.universe_size;

// picks cards
const cards=document.getElementById("cards");
for(const [key,color] of [["focused","gold"],["balanced","jade"]]){
  const t=DATA.tracks[key];
  const rows=t.picks.map((r,i)=>`<tr>
    <td class="tick">${i+1}&nbsp; ${r.ticker}${r.status==="new"?'<span class="new">NEW</span>':r.status==="breached"?'<span class="brch">STOP HIT</span>':""}</td>
    <td>${fmtP(r.weight)}</td><td>$${r.price.toFixed(2)}</td>
    <td class="stop">$${r.stop.toFixed(2)}</td></tr>`).join("");
  cards.insertAdjacentHTML("beforeend",`<div class="card ${color}">
    <h3>${key==="focused"?"Focused":"Balanced"}</h3>
    <div class="meta">${t.label} · live model <b>${t.live_label}</b></div>
    <table aria-label="${key} picks"><thead><tr><th>Pick</th><th>Weight</th><th>Last</th><th>Stop</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`);
}

// equity chart
const BCOL={SPY:"#7fb3d5",QQQ:"#c98f6d","^DJI":"#9a8fbf",DIA:"#9a8fbf"};
const series=[["Focused",DATA.tracks.focused.equity,"#d9ac33",2.4],
              ["Balanced",DATA.tracks.balanced.equity,"#5fcb92",2.4],
              ...Object.entries(DATA.benchmarks).map(([k,v])=>[k,v.equity,BCOL[k]||"#8fa0a8",1.3])
             ].filter(s=>s[1]);
new Chart(document.getElementById("eq"),{type:"line",
 data:{labels:series[0][1].labels,
  datasets:series.map(([label,eq,colorr,w])=>({label,data:eq.values,borderColor:colorr,
    borderWidth:w,pointRadius:0,tension:.25,borderDash:label==="Focused"||label==="Balanced"?[]:[5,4]}))},
 options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},
  scales:{y:{type:"logarithmic",grid:{color:"rgba(36,70,60,.5)"},ticks:{color:"#98b3a8",callback:v=>"$"+v}},
          x:{grid:{display:false},ticks:{color:"#6d8a7f",maxTicksLimit:9}}},
  plugins:{legend:{labels:{color:"#e9f2ec",boxWidth:18,boxHeight:2}},
   tooltip:{backgroundColor:"#0b1715",borderColor:"#24463c",borderWidth:1,
    callbacks:{label:c=>` ${c.dataset.label}: $${(+c.parsed.y).toFixed(0)}`}}}}});
document.getElementById("chartnote").textContent=
 `Backtest ${DATA.period}. Net of ${DATA.cost_bps} bps per-side costs. Meta-strategy shown: the variant actually selected each month.`;

// metrics table
const M=[["Focused",DATA.tracks.focused.metrics],["Balanced",DATA.tracks.balanced.metrics],
 ...Object.entries(DATA.benchmarks).map(([k,v])=>[k,v.metrics])];
const mrows=M.map(([name,m])=>`<tr><td class="name">${name}</td>
 <td class="${cls(m.cagr)}">${fmtP(m.cagr)}</td><td>${fmtS(m.sharpe)}</td><td>${fmtS(m.sortino)}</td>
 <td>${fmtP(m.ann_vol)}</td><td class="neg">${fmtP(m.max_drawdown)}</td>
 <td>${fmtS(m.calmar)}</td><td>${fmtP(m.win_rate,0)}</td>
 <td class="${cls(m.total_return)}">${fmtP(m.total_return,0)}</td></tr>`).join("");
document.getElementById("mtable").innerHTML=`<table>
 <thead><tr><th style="text-align:left">Series</th><th>CAGR</th><th>Sharpe</th><th>Sortino</th>
 <th>Vol</th><th>Max DD</th><th>Calmar</th><th>Win mo.</th><th>Total</th></tr></thead>
 <tbody>${mrows}</tbody></table>`;

// leaderboard
const L=DATA.leaderboard;
const lrows=L.map(r=>`<tr><td class="name">${r.track}</td><td class="name">${r.label}</td>
 <td>${fmtS(r.trailing_sortino)}</td><td>${r.live?'<span class="live-dot"></span>live':""}</td></tr>`).join("");
document.getElementById("leader").innerHTML=`<table>
 <thead><tr><th style="text-align:left">Track</th><th style="text-align:left">Variant</th>
 <th>Sortino (24m)</th><th></th></tr></thead><tbody>${lrows}</tbody></table>`;

document.getElementById("fnote1").textContent=`Generated ${DATA.generated}. Data: fund issuer holdings pages + Yahoo Finance adjusted prices.`;
</script>
</body>
</html>
"""
