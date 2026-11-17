"""Bookie-engine dashboard, styled like the FX Engine dashboard (same dark palette, header, tabs, KPI tiles, cards).
ONE self-contained HTML file (inline SVG, a few lines of tab JS, no external requests) built from docs/results/bets.json (+ the paper ledger when served).
It only ever shows numbers that are in those files; with no results it says so. Research only: nothing here places a real bet.
Usage: PYTHONPATH=src python -m fxengine.bets.dashboard   -> docs/results/bets.html"""
from __future__ import annotations
import html, json, math, sys
from datetime import datetime
from pathlib import Path

NAMES = {
    "F1_all_favourites": ("Back every favourite", "Shortest price in each match"),
    "L1_longshots_5plus": ("Back every longshot", "Any outcome priced 5.0 or longer"),
    "V1_b365_vs_pinnacle_3pc": ("Bet365 vs sharp price", "Bet365 pays 3%+ more than Pinnacle's fair price"),
    "OV1_over25_all": ("Always over 2.5 goals", "Every match, over 2.5"),
    "UN1_under25_all": ("Always under 2.5 goals", "Every match, under 2.5"),
    "D1_draws_all": ("Back every draw", "Every match, the draw"),
}
SELNAME = {"H": "Home", "D": "Draw", "A": "Away", "O25": "Over 2.5", "U25": "Under 2.5"}
E = html.escape

CSS = """
:root{--bg:#111110;--card:#1a1a19;--line:#2c2c2a;--ink:#f0efec;--ink2:#c3c2b7;--mute:#8d8c84;--s1:#3987e5;--s2:#d95926;--good:#0ca30c;--warn:#fab219;--crit:#d03b3b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,'Inter','Segoe UI',sans-serif}
.wrap{max-width:1360px;margin:0 auto;padding:14px 16px 40px}
.top{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:6px 0 10px}
.brand{font-weight:700;letter-spacing:.14em;font-size:13px}.chip{border:1px solid var(--line);border-radius:999px;padding:3px 10px;font-size:11px;color:var(--ink2)}
.pill{display:inline-flex;align-items:center;gap:7px;border-radius:999px;padding:4px 12px;font-weight:700;font-size:12px;letter-spacing:.06em;color:#fff}
.pill.good{background:#0a6e0a}.pill.warn{background:#8a5f00}.pill.crit{background:#9c2b2b}
.sp{flex:1}.mono,.num{font-family:ui-monospace,'SF Mono',Menlo,monospace;font-variant-numeric:tabular-nums}.muted{color:var(--mute)}
.tabs{display:flex;gap:4px;overflow-x:auto;border-bottom:1px solid var(--line);margin-bottom:12px}
.tabs button{background:none;border:0;color:var(--ink2);padding:9px 14px;font:600 12px inherit;font-family:inherit;letter-spacing:.06em;text-transform:uppercase;cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap}
.tabs button.on{color:var(--ink);border-bottom-color:var(--s1)}.js .tab{display:none}.js .tab.on{display:block}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:0 0 12px}
.kpi,.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.kpi small{color:var(--mute);text-transform:uppercase;letter-spacing:.08em;font-size:12px}.kpi b{display:block;font:600 28px ui-monospace,Menlo,monospace;margin-top:2px}
.kpi span{color:var(--mute);font-size:13px}.up{color:#3fd13f}.dn{color:#e0605a}
.verdict{border:1px solid var(--crit);background:color-mix(in srgb,var(--crit) 12%,var(--card));border-radius:10px;padding:10px 14px;margin:0 0 12px}
.verdict.ok{border-color:var(--good);background:color-mix(in srgb,var(--good) 12%,var(--card))}.verdict.empty{border-color:var(--line);background:var(--card)}
h3{margin:0 0 10px;font-size:13px;text-transform:uppercase;letter-spacing:.1em;color:var(--ink2);font-weight:600}
h2.sec{font-size:16px;margin:16px 0 8px}h2.sec small{color:var(--mute);font-weight:400;font-size:12px;margin-left:8px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(12,1fr)}.c12{grid-column:span 12}.c6{grid-column:span 6}.c4{grid-column:span 4}
@media(max-width:900px){.c6,.c4{grid-column:span 12}}
svg{width:100%;height:auto;display:block}.scroll{overflow-x:auto}.scroll svg{min-width:640px}
.gridl{stroke:var(--line);stroke-width:1}.zero{stroke:var(--mute);stroke-width:1.2;stroke-dasharray:4 3}.tick{fill:var(--mute);font-size:11px}
.rl{fill:var(--ink);font-size:13px;font-weight:600}.rs{fill:var(--mute);font-size:11px}.val{fill:var(--ink);font-size:12px;font-weight:600}
.ci{stroke-width:3;stroke-linecap:round}.ci.no{stroke:var(--s2)}.ci.ok{stroke:var(--good)}.dot.no{fill:var(--s2);stroke:var(--card);stroke-width:2}.dot.ok{fill:var(--good);stroke:var(--card);stroke-width:2}.chal{fill:var(--s1)}
.legend{display:flex;gap:14px;margin-top:6px;color:var(--ink2);font-size:11px;flex-wrap:wrap}.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
.tag{display:inline-block;border-radius:4px;padding:1px 8px;font-size:10px;font-weight:700;letter-spacing:.06em;color:#fff}.tag.f{background:#9c2b2b}.tag.p{background:#0a6e0a}.tag.n{background:var(--line);color:var(--ink2)}
.rulecard h4{margin:0;font-size:15px}.rulecard .d{color:var(--mute);font-size:12px;margin:2px 0 10px}.rulecard .tag{float:right}
.nums{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px}.nums div{background:color-mix(in srgb,var(--bg) 55%,var(--card));border-radius:8px;padding:8px 10px}
.nums small{display:block;color:var(--mute);font-size:11px;text-transform:uppercase;letter-spacing:.07em}.nums b{font:600 16px ui-monospace,Menlo,monospace}
.neg{fill:var(--s2)}.pos{fill:var(--good)}.seas{max-width:230px}
.lrow{display:grid;grid-template-columns:200px 1fr;gap:4px 14px;align-items:center;margin:11px 0}.lname{font-size:13px;font-weight:600}
.bar{display:flex;height:14px;border-radius:99px;overflow:hidden;background:var(--line)}.b-goal{background:var(--good)}.b-mid{background:transparent}.b-ruin{background:var(--s2);margin-left:auto}
.lnum{grid-column:2;font-size:12px;color:var(--ink2)}.lnum b{color:var(--ink)}
.note{border:1px solid var(--warn);background:color-mix(in srgb,var(--warn) 10%,var(--card));border-radius:10px;padding:10px 14px;font-size:13.5px;margin-top:12px}
.tbl{width:100%;border-collapse:collapse;font-size:13px}.tbl th{color:var(--mute);font-weight:600;text-align:left;padding:6px 8px;font-size:11px;text-transform:uppercase;letter-spacing:.07em}
.tbl td{padding:7px 8px;border-top:1px solid var(--line)}.tbl .r{text-align:right}.w{color:#3fd13f;font-weight:700}.l{color:#e0605a;font-weight:700}
ul.lim{margin:6px 0 0;padding-left:18px;color:var(--ink2);font-size:13.5px}ul.lim li{margin:4px 0}
.fx{display:grid;grid-template-columns:1fr auto;gap:6px 12px;align-items:center;padding:9px 0;border-top:1px solid var(--line)}.fx .m{font-size:13.5px;font-weight:600}.fx .t{color:var(--mute);font-size:11.5px;font-weight:400}
.pk{display:flex;flex-wrap:wrap;gap:5px;justify-content:flex-end}.pk button,.btn{font:600 12px inherit;font-family:inherit;border:1px solid var(--line);background:var(--card);color:var(--ink2);border-radius:6px;padding:5px 10px;cursor:pointer;min-width:54px}
.pk button:hover,.btn:hover{border-color:var(--s1);color:var(--ink)}.pk button i{display:block;font:normal 11px ui-monospace,Menlo,monospace;color:var(--mute)}
.ctl{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:8px 0}.ctl input{font:inherit;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px 10px}
.ctl input[type=number]{width:90px}.ctl input[type=search]{flex:1;min-width:160px}
.paperbanner{border:1px solid var(--s1);background:color-mix(in srgb,var(--s1) 10%,var(--card));border-radius:10px;padding:8px 14px;margin:0 0 12px;font-size:13px;color:var(--ink2)}
footer{color:var(--mute);font-size:12px;text-align:center;margin-top:14px}
@media (max-width:640px){.lrow{grid-template-columns:1fr}.lnum{grid-column:1}}
"""

JS = """<script>
(function(){var d=document;d.documentElement.classList.add('js');var bs=d.querySelectorAll('.tabs button'),ts=d.querySelectorAll('.tab');
function show(t){bs.forEach(function(b){b.classList.toggle('on',b.dataset.t===t)});ts.forEach(function(s){s.classList.toggle('on',s.id===t)});try{history.replaceState(null,'','#'+t)}catch(e){}}
bs.forEach(function(b){b.onclick=function(){show(b.dataset.t)}});var h=(location.hash||'').slice(1);show(d.getElementById(h)?h:bs[0].dataset.t);if(!h){window.scrollTo(0,0);setTimeout(function(){window.scrollTo(0,0)},0)}})();
function bet(btn){var s=parseFloat(document.getElementById('stake').value);btn.disabled=true;
fetch('/api/bet',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:btn.dataset.id,market:btn.dataset.m,sel:btn.dataset.s,stake:s})})
.then(function(r){return r.json()}).then(function(j){if(j.ok){location.reload()}else{alert(j.error||'Could not place that paper bet');btn.disabled=false}})
.catch(function(){alert('Could not reach the paper server');btn.disabled=false})}
function tick(b){b.disabled=true;b.textContent='Checking...';fetch('/api/tick',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(function(){location.reload()}).catch(function(){b.disabled=false})}
function filt(q){q=q.toLowerCase();document.querySelectorAll('.fx').forEach(function(e){e.style.display=e.dataset.q.indexOf(q)>-1?'':'none'})}
</script>"""


def _num(x):
    return isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x))


def level(res):
    """Coverage of the shown range: gate_b uses alpha*2 two-sided with alpha = 0.05/trials, i.e. 1 - 0.1/trials (98.3% for 6 rules)."""
    n = max(1, (res or {}).get("n_trials", 1) or 1)
    return f"{100 * (1 - 0.1 / n):.1f}%"


def pct(x, signed=False, d=1):
    return "n/a" if not _num(x) else (f"{x * 100:+.{d}f}%" if signed else f"{x * 100:.{d}f}%")


def _gbp(x, signed=False):
    return "n/a" if not _num(x) else (f"{'+' if signed and x > 0 else '-' if x < 0 else ''}£{abs(x):.2f}")


def _forest(rules, lvl="95%") -> str:
    rs = [r for r in rules if "roi" in r]
    if not rs:
        return ""
    vals = [v for r in rs for v in (r["ci95_lo"], r["ci95_hi"], r["roi"], r.get("challenger_p95")) if _num(v)] + [0.0]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.08 or 0.01
    lo, hi = lo - pad, hi + pad
    W, LBL, RH, TOP = 760, 190, 54, 26
    H = TOP + RH * len(rs) + 34
    X = lambda v: LBL + (v - lo) / (hi - lo) * (W - LBL - 16)
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Return on each £1 staked for each rule, with {lvl} confidence ranges">']
    step = 0.05 if hi - lo > 0.25 else 0.02 if hi - lo > 0.1 else 0.01
    t = math.ceil(lo / step) * step
    while t <= hi:
        x = X(t)
        o.append(f'<line x1="{x:.1f}" y1="{TOP - 6}" x2="{x:.1f}" y2="{H - 28}" class="gridl"/><text x="{x:.1f}" y="{H - 12}" class="tick" text-anchor="middle">{t * 100:+.0f}%</text>')
        t += step
    o.append(f'<line x1="{X(0):.1f}" y1="{TOP - 10}" x2="{X(0):.1f}" y2="{H - 28}" class="zero"/><text x="{X(0):.1f}" y="{TOP - 12}" class="tick" text-anchor="middle">break-even</text>')
    for i, r in enumerate(rs):
        y = TOP + RH * i + RH / 2
        name = NAMES.get(r["rule"], (r["rule"], ""))[0]
        cls = "ok" if r["passes"] else "no"
        o.append(f'<text x="0" y="{y - 3:.1f}" class="rl">{E(name)}</text><text x="0" y="{y + 13:.1f}" class="rs">{r["n"]:,} bets</text>')
        o.append(f'<line x1="{X(r["ci95_lo"]):.1f}" y1="{y:.1f}" x2="{X(r["ci95_hi"]):.1f}" y2="{y:.1f}" class="ci {cls}"/>'
                 f'<line x1="{X(r["ci95_lo"]):.1f}" y1="{y - 6:.1f}" x2="{X(r["ci95_lo"]):.1f}" y2="{y + 6:.1f}" class="ci {cls}"/>'
                 f'<line x1="{X(r["ci95_hi"]):.1f}" y1="{y - 6:.1f}" x2="{X(r["ci95_hi"]):.1f}" y2="{y + 6:.1f}" class="ci {cls}"/>')
        if _num(r.get("challenger_p95")):
            o.append(f'<path d="M{X(r["challenger_p95"]):.1f} {y - 11:.1f} l4 -6 l-8 0 z" class="chal"><title>Random betting beats this only 5% of the time: {pct(r["challenger_p95"], True)}</title></path>')
        o.append(f'<circle cx="{X(r["roi"]):.1f}" cy="{y:.1f}" r="5.5" class="dot {cls}"><title>{E(name)}: {pct(r["roi"], True, 2)} per £1 staked</title></circle>'
                 f'<text x="{min(X(r["ci95_hi"]) + 8, W - 44):.1f}" y="{y + 4:.1f}" class="val">{pct(r["roi"], True)}</text>')
    o.append("</svg>")
    return "".join(o)


def _seasons(by) -> str:
    items = [(k, v) for k, v in sorted((by or {}).items()) if _num(v)]
    if not items:
        return ""
    m = max(0.05, max(abs(v) for _, v in items))
    w, h, mid = 14, 34, 17
    o = [f'<svg viewBox="0 0 {len(items) * (w + 3)} {h}" class="seas" role="img" aria-label="ROI by season"><line x1="0" y1="{mid}" x2="{len(items) * (w + 3)}" y2="{mid}" class="zero"/>']
    for i, (k, v) in enumerate(items):
        bh = abs(v) / m * (mid - 2)
        o.append(f'<rect x="{i * (w + 3)}" y="{mid - bh if v >= 0 else mid}" width="{w}" height="{max(bh, 1):.1f}" class="{"pos" if v >= 0 else "neg"}"><title>{E(k)}: {pct(v, True)}</title></rect>')
    return "".join(o) + "</svg>"


def _lottery(rules) -> str:
    rs = [r for r in rules if "sim" in r]
    if not rs:
        return ""
    o = []
    for r in rs:
        s = r["sim"]
        g, ru, ne = s["p_goal"], s["p_ruin"], max(0.0, s["p_neither"])
        name = NAMES.get(r["rule"], (r["rule"], ""))[0]
        o.append(f'<div class="lrow"><div class="lname">{E(name)}</div><div class="bar" role="img" aria-label="{E(name)}: {g:.1%} reach £1,000, {ru:.0%} lose the £100">'
                 f'<span class="b-goal" style="width:{max(g * 100, 0.4):.2f}%"></span><span class="b-mid" style="width:{ne * 100:.2f}%"></span><span class="b-ruin" style="width:{ru * 100:.2f}%"></span></div>'
                 f'<div class="lnum"><b>{g:.1%}</b> reach £1,000 · <b>{ru:.0%}</b> go bust</div></div>')
    return "".join(o)


def _curve(curve, start) -> str:
    if len(curve) < 2:
        return '<p class="muted">The bankroll chart appears after the first paper bet settles.</p>'
    lo, hi = min(curve + [start]), max(curve + [start])
    pad = (hi - lo) * 0.1 or 1
    lo, hi = lo - pad, hi + pad
    W, H = 700, 150
    X = lambda i: 8 + i / (len(curve) - 1) * (W - 16)
    Y = lambda v: H - 10 - (v - lo) / (hi - lo) * (H - 20)
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(curve))
    col = "var(--good)" if curve[-1] >= start else "var(--s2)"
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Virtual bankroll after each settled paper bet"><line x1="0" y1="{Y(start):.1f}" x2="{W}" y2="{Y(start):.1f}" class="zero"/>'
            f'<text x="{W - 4}" y="{Y(start) - 4:.1f}" class="tick" text-anchor="end">£{start:.0f} start</text><polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.5" stroke-linejoin="round"/>'
            f'<circle cx="{X(len(curve) - 1):.1f}" cy="{Y(curve[-1]):.1f}" r="4.5" fill="{col}"/></svg>')


def _bet_rows(bets, n=30):
    if not bets:
        return '<p class="muted">None yet.</p>'
    rows = []
    for b in bets[:n]:
        st = {"won": '<span class="w">WON</span>', "lost": '<span class="l">LOST</span>'}.get(b["status"], '<span class="tag n">OPEN</span>')
        rows.append(f'<tr><td>{E(b["date"])}</td><td>{E(b["home"])} v {E(b["away"])}</td><td>{E(SELNAME.get(b["sel"], b["sel"]))}</td><td class="r num">{b["odds"]:.2f}</td><td class="r num">£{b["stake"]:.2f}</td>'
                    f'<td>{st}</td><td class="r num">{_gbp(b["pnl"], True) if b["pnl"] is not None else ""}</td><td>{E(b["rule"])}</td></tr>')
    return ('<div class="scroll" style="overflow-x:auto"><table class="tbl" style="min-width:560px"><tr><th>Date</th><th>Match</th><th>Pick</th><th class="r">Price</th><th class="r">Stake</th><th>Status</th><th class="r">P/L</th><th>By</th></tr>'
            + "".join(rows) + "</table></div>")


def _paper_tab(p: dict) -> str:
    eq, roi = p["equity"], p["roi"]
    cls = "up" if eq > p["start"] else "dn" if eq < p["start"] else ""
    fx = []
    for f in p["fixtures"]:
        btns = []
        for m, sel, o in (("1X2", "H", f["b365"][0]), ("1X2", "D", f["b365"][1]), ("1X2", "A", f["b365"][2]), ("OU", "O25", f["ou"][0]), ("OU", "U25", f["ou"][1])):
            if o:
                btns.append(f'<button data-id="{E(f["id"], quote=True)}" data-m="{m}" data-s="{sel}" onclick="bet(this)">{SELNAME[sel]}<i>{o:.2f}</i></button>')
        if btns:
            q = E(f'{f["home"]} {f["away"]} {f["div"]} {f["date"]}'.lower(), quote=True)
            fx.append(f'<div class="fx" data-q="{q}"><div class="m">{E(f["home"])} v {E(f["away"])}<div class="t">{E(f["date"])} {E(f["time"])} · {E(f["div"])}</div></div><div class="pk">{"".join(btns)}</div></div>')
    rules = "".join(f'<tr><td>{E(k)}</td><td class="r num">{v["n"]}</td><td class="r num">{v["won"]}</td><td class="r num">{_gbp(v["pnl"], True)}</td><td class="r num">{pct(v["pnl"] / v["staked"], True) if v["staked"] else "n/a"}</td></tr>' for k, v in sorted(p["by_rule"].items()))
    rcls = "up" if (roi or 0) > 0 else "dn" if (roi or 0) < 0 else ""
    return f"""<div class="paperbanner"><b>PAPER ONLY.</b> Pretend money. Nothing is ever sent to Bet365 or any bookmaker. Prices are Bet365's from football-data.co.uk's free fixtures file and may differ from live prices. Last check: {E(p["last_tick"] or "never")} UTC.</div>
<div class="kpis"><div class="kpi"><small>Virtual bankroll</small><b class="{cls}">£{eq:.2f}</b><span>start £{p["start"]:.0f}</span></div><div class="kpi"><small>Free to stake</small><b>£{p["available"]:.2f}</b><span>after open bets</span></div>
<div class="kpi"><small>Open bets</small><b>{len(p["open"])}</b><span>waiting for the match</span></div><div class="kpi"><small>Settled</small><b>{p["n_settled"]}</b><span>{p["won"]} won</span></div>
<div class="kpi"><small>Return on stakes</small><b class="{rcls}">{pct(roi, True)}</b><span>settled bets only</span></div></div>
<div class="grid"><div class="card c12"><h3>Virtual bankroll after each settled bet</h3>{_curve(p["curve"], p["start"])}</div>
<div class="card c12"><h3>Place a paper bet</h3><div class="ctl"><label class="muted">Stake £ <input id="stake" type="number" min="{p["min_stake"]}" step="0.5" value="{p["auto_stake"]:.2f}"></label>
<input type="search" placeholder="Search team or league (e.g. Arsenal, E0)" oninput="filt(this.value)"><button class="btn" onclick="tick(this)">Refresh prices &amp; results</button></div>
{"".join(fx) or '<p class="muted">No upcoming matches loaded yet. The free fixtures file only has matches once the site posts them; this page checks every 30 minutes by itself.</p>'}</div>
<div class="card c6"><h3>Open paper bets</h3>{_bet_rows(p["open"])}</div><div class="card c6"><h3>Settled paper bets</h3>{_bet_rows(p["settled"])}</div>
{('<div class="card c12"><h3>By strategy</h3><table class="tbl"><tr><th>Strategy</th><th class="r">Settled</th><th class="r">Won</th><th class="r">P/L</th><th class="r">Return</th></tr>' + rules + '</table><p class="muted" style="font-size:12px;margin:8px 0 0">V1 / V1P = automatic bets from the research rule (Shin / plain margin removal), flat £' + f"{p['auto_stake']:.2f}" + ' each. MANUAL = your clicks.</p></div>') if rules else ""}</div>"""


def render_paper(p: dict) -> str:        # kept for callers/tests that want the paper panel on its own
    return _paper_tab(p)


def render(res: dict | None, paper: dict | None = None) -> str:
    rules = (res or {}).get("rules", [])
    lvl = level(res)
    scored = [r for r in rules if "roi" in r]
    passed = [r for r in scored if r["passes"]]
    if not scored:
        state, label = "warn", "NO RESULTS YET"
        verdict = ('<div class="verdict empty"><b>No results yet.</b> <span class="muted">Run <code>bash deploy/run_bets.sh</code> on the VM. This page shows only real results from docs/results/bets.json.</span></div>')
    elif passed:
        names = ", ".join(NAMES.get(r["rule"], (r["rule"],))[0] for r in passed)
        state, label = "good", f"{len(passed)} RULE CLEARED THE GATE"
        verdict = (f'<div class="verdict ok"><b>{len(passed)} rule(s) cleared the gate: {E(names)}.</b> Treat as a lead, not a result: it still needs the sealed holdout season, and real prices may be worse than the historical ones.</div>')
    else:
        avg = sum(r["roi"] for r in scored) / len(scored)
        state, label = "crit", "NO EDGE FOUND"
        verdict = (f'<div class="verdict"><b>No proven edge: every rule loses to the bookmaker\'s margin.</b> Average return per £1 staked across {len(scored)} pre-registered rules: <b class="num">{pct(avg, True)}</b>. '
                   f'A rule only counts if its whole {lvl} range is above zero after the multiple-testing penalty and it beats random betting.</div>')
    cards = []
    for r in rules:
        name, desc = NAMES.get(r["rule"], (r["rule"], ""))
        if "roi" not in r:
            cards.append(f'<div class="card c4 rulecard"><span class="tag n">{E(str(r.get("verdict", "no result")))}</span><h4>{E(name)}</h4><div class="d">{E(desc)}</div><p class="muted">Only {r.get("n", 0):,} bets: too few to judge.</p></div>')
            continue
        ok = r["passes"]
        cards.append(
            f'<div class="card c4 rulecard"><span class="tag {"p" if ok else "f"}">{"CLEARED GATE" if ok else "NO EDGE"}</span><h4>{E(name)}</h4><div class="d">{E(desc)}</div>'
            f'<div class="nums"><div><small>Return per £1</small><b>{pct(r["roi"], True, 2)}</b></div><div><small>{lvl} range</small><b style="font-size:13px">{pct(r["ci95_lo"], True)} to {pct(r["ci95_hi"], True)}</b></div>'
            f'<div><small>Bets · hit rate</small><b style="font-size:14px">{r["n"]:,} · {pct(r["hit_rate"])}</b></div><div><small>Beat the closing line</small><b>{pct(r.get("clv_vs_close"), True)}</b></div></div>'
            f'{_seasons(r.get("by_season")) and "<small class=muted>Return by season</small>" + _seasons(r.get("by_season"))}</div>')
    tabs = [("paper", "Paper trading")] if paper is not None else []
    tabs += [("research", "Research"), ("rules", "Rules"), ("odds", "£1,000 odds"), ("about", "About")]
    seasons, trials = E(str((res or {}).get("seasons", "—"))), (res or {}).get("n_trials", "—")
    now = datetime.now().strftime("%a %d %b %Y %H:%M")
    sections = []
    if paper is not None:
        sections.append(f'<div class="tab" id="paper">{_paper_tab(paper)}</div>')
    sections.append(f'<div class="tab" id="research">{verdict}<div class="card"><h3>Did any rule make money after the bookmaker\'s cut? · profit per £1 staked at Bet365\'s own historical price</h3>'
                    f'<div class="scroll">{_forest(rules, lvl) or "<p class=muted>No scored rules yet.</p>"}</div>'
                    f'<div class="legend"><span><i style="background:var(--s2)"></i>no proven edge</span><span><i style="background:var(--good)"></i>cleared the gate</span><span><i style="background:var(--s1)"></i>random-bet 95th percentile</span><span>dot = result · line = {lvl} range (already includes the penalty for trying several rules) · dashed = break-even</span></div></div></div>')
    sections.append(f'<div class="tab" id="rules"><div class="grid">{"".join(cards) or "<p class=muted>Nothing to show yet.</p>"}</div><p class="muted" style="font-size:12px">Past results on past matches. A winning past is not a promise.</p></div>')
    sections.append(f'<div class="tab" id="odds"><div class="card"><h3>Chance of turning £100 into £1,000 · 5% of the bankroll staked each time</h3>{_lottery(rules) or "<p class=muted>No simulation yet.</p>"}'
                    '<div class="note">Even with zero margin, going all-in at even money reaches £1,000 only 10% of the time (1 in 10); with a typical 5% margin about 1 in 12. A 10x target is a lottery ticket whether or not an edge exists.</div></div></div>')
    sections.append('<div class="tab" id="about"><div class="card"><h3>What this cannot tell you</h3><ul class="lim"><li>Historical prices are closing-time snapshots; today\'s Bet365 price may differ.</li>'
                    '<li>Free data has no stake limits. Bet365 limits or closes accounts that win, so real profit would be lower than any backtest.</li>'
                    '<li>Only money you can afford to lose entirely. This engine never logs in, never places or suggests a bet; any real bet is yours alone, at your own risk.</li>'
                    '<li>Latest seasons are sealed: the engine has never looked at them. They are opened once, only if a rule clears the gate.</li></ul></div></div>')
    body = (f'<div class="wrap"><div class="top"><span class="brand">BOOKIE ENGINE</span><span class="pill {state}">{label}</span><span class="chip">seasons {seasons}</span>'
            f'<span class="chip">{trials} rules tried</span><span class="chip">latest seasons sealed</span><span class="chip">paper only · never places a bet</span><span class="sp"></span><span class="mono muted">{now}</span></div>'
            f'<div class="tabs">{"".join(f"<button data-t={k!r}>{v}</button>".replace(chr(39), chr(34)) for k, v in tabs)}</div>{"".join(sections)}'
            '<footer>Generated from docs/results/bets.json · numbers are shown only if they are in that file</footer></div>')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bookie Engine</title>'
            f'<style>{CSS}</style></head><body>{body}{JS}</body></html>')


def write(res_path=Path("docs/results/bets.json"), out=Path("docs/results/bets.html")) -> Path:
    res = json.loads(Path(res_path).read_text()) if Path(res_path).exists() else None
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(res))
    return out


if __name__ == "__main__":
    print("wrote", write(*(Path(a) for a in sys.argv[1:3])))
