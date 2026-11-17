"""Bookie-engine dashboard: ONE self-contained HTML file (inline SVG, no scripts, no external requests) built from docs/results/bets.json.
It only ever shows numbers that are in that file; with no results it says so. Research only: nothing here places or suggests a bet.
Usage: PYTHONPATH=src python -m fxengine.bets.dashboard   -> docs/results/bets.html"""
from __future__ import annotations
import html, json, math, sys
from pathlib import Path

NAMES = {
    "F1_all_favourites": ("Back every favourite", "Shortest price in each match"),
    "L1_longshots_5plus": ("Back every longshot", "Any outcome priced 5.0 or longer"),
    "V1_b365_vs_pinnacle_3pc": ("Bet365 vs sharp price", "Bet365 pays 3%+ more than Pinnacle's fair price"),
    "OV1_over25_all": ("Always over 2.5 goals", "Every match, over 2.5"),
    "UN1_under25_all": ("Always under 2.5 goals", "Every match, under 2.5"),
    "D1_draws_all": ("Back every draw", "Every match, the draw"),
}
E = html.escape


def _num(x):
    return isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x))


def level(res):
    """Coverage of the shown range: gate_b uses alpha*2 two-sided with alpha = 0.05/trials, i.e. 1 - 0.1/trials (98.3% for 6 rules)."""
    n = max(1, (res or {}).get("n_trials", 1) or 1)
    return f"{100 * (1 - 0.1 / n):.1f}%"


def pct(x, signed=False, d=1):
    return "n/a" if not _num(x) else (f"{x * 100:+.{d}f}%" if signed else f"{x * 100:.{d}f}%")


def _forest(rules, lvl='95%') -> str:
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
        o.append(f'<line x1="{x:.1f}" y1="{TOP - 6}" x2="{x:.1f}" y2="{H - 28}" class="grid"/>'
                 f'<text x="{x:.1f}" y="{H - 12}" class="tick" text-anchor="middle">{t * 100:+.0f}%</text>')
        t += step
    o.append(f'<line x1="{X(0):.1f}" y1="{TOP - 10}" x2="{X(0):.1f}" y2="{H - 28}" class="zero"/>'
             f'<text x="{X(0):.1f}" y="{TOP - 12}" class="tick" text-anchor="middle">break-even</text>')
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
    o = [f'<svg viewBox="0 0 {len(items) * (w + 3)} {h}" class="seas" role="img" aria-label="ROI by season">'
         f'<line x1="0" y1="{mid}" x2="{len(items) * (w + 3)}" y2="{mid}" class="zero"/>']
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
        o.append(f'<div class="lrow"><div class="lname">{E(name)}</div>'
                 f'<div class="bar" role="img" aria-label="{E(name)}: {g:.1%} reach £1,000, {ru:.0%} lose the £100">'
                 f'<span class="b-goal" style="width:{max(g * 100, 0.4):.2f}%"></span><span class="b-mid" style="width:{ne * 100:.2f}%"></span>'
                 f'<span class="b-ruin" style="width:{ru * 100:.2f}%"></span></div>'
                 f'<div class="lnum"><b>{g:.1%}</b> reach £1,000 · <b>{ru:.0%}</b> go bust</div></div>')
    return "".join(o)


CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#14181f;--mut:#5b6573;--line:#e3e7ee;--accent:#2563eb;--ok:#15803d;--no:#b4533a;--okbg:#e8f5ec;--nobg:#fbeee9;--warn:#92600a;--warnbg:#fdf3dc}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0e1116;--card:#171b22;--ink:#e8ecf2;--mut:#9aa5b4;--line:#28303b;--accent:#6ea0ff;--ok:#4cc27a;--no:#e38a6e;--okbg:#14301f;--nobg:#33201a;--warn:#e0b04a;--warnbg:#33290f}}
:root[data-theme=dark]{--bg:#0e1116;--card:#171b22;--ink:#e8ecf2;--mut:#9aa5b4;--line:#28303b;--accent:#6ea0ff;--ok:#4cc27a;--no:#e38a6e;--okbg:#14301f;--nobg:#33201a;--warn:#e0b04a;--warnbg:#33290f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1060px;margin:0 auto;padding:20px 16px 48px}
header{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:baseline;justify-content:space-between;margin-bottom:14px}
h1{font-size:22px;margin:0;letter-spacing:-.01em}h1 small{font-weight:500;color:var(--mut);font-size:14px;margin-left:8px}
.chips{display:flex;flex-wrap:wrap;gap:6px}.chip{border:1px solid var(--line);background:var(--card);border-radius:99px;padding:3px 10px;font-size:12.5px;color:var(--mut)}
.verdict{border-radius:14px;padding:18px 20px;margin:10px 0 18px;border:1px solid var(--line);display:grid;grid-template-columns:auto 1fr;gap:6px 18px;align-items:center}
.verdict.no{background:var(--nobg)}.verdict.ok{background:var(--okbg)}.verdict.empty{background:var(--card)}
.big{font-size:44px;font-weight:700;line-height:1;letter-spacing:-.02em}.verdict.no .big{color:var(--no)}.verdict.ok .big{color:var(--ok)}
.vt{font-size:17px;font-weight:650}.vs{color:var(--mut);font-size:14px}
section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:18px}
h2{font-size:15px;margin:0 0 2px}.sub{color:var(--mut);font-size:13px;margin:0 0 12px}
svg{width:100%;height:auto;display:block}.scroll{overflow-x:auto}.scroll svg{min-width:640px}
.grid{stroke:var(--line);stroke-width:1}.zero{stroke:var(--mut);stroke-width:1.2;stroke-dasharray:4 3}.tick{fill:var(--mut);font-size:11px}
.rl{fill:var(--ink);font-size:13px;font-weight:600}.rs{fill:var(--mut);font-size:11px}.val{fill:var(--ink);font-size:12px;font-weight:600}
.ci{stroke-width:3;stroke-linecap:round}.ci.no{stroke:var(--no)}.ci.ok{stroke:var(--ok)}.dot.no{fill:var(--no);stroke:var(--card);stroke-width:2}.dot.ok{fill:var(--ok);stroke:var(--card);stroke-width:2}
.chal{fill:var(--accent)}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:12.5px;color:var(--mut);margin-top:8px}.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:14px}
.card{border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:var(--card)}
.card h3{margin:0;font-size:15px}.card .d{color:var(--mut);font-size:12.5px;margin-bottom:10px}
.badge{float:right;font-size:11.5px;font-weight:650;border-radius:99px;padding:2px 9px}.badge.no{background:var(--nobg);color:var(--no)}.badge.ok{background:var(--okbg);color:var(--ok)}.badge.na{background:var(--line);color:var(--mut)}
.kv{display:grid;grid-template-columns:1fr 1fr;gap:8px 12px;margin-bottom:8px}.kv div span{display:block;color:var(--mut);font-size:11.5px}.kv div b{font-size:17px}
.neg{fill:var(--no)}.pos{fill:var(--ok)}.seas{max-width:230px}
.lrow{display:grid;grid-template-columns:190px 1fr;gap:4px 14px;align-items:center;margin:11px 0}.lname{font-size:13px;font-weight:600}
.bar{display:flex;height:16px;border-radius:99px;overflow:hidden;background:var(--line)}.b-goal{background:var(--ok)}.b-mid{background:transparent}.b-ruin{background:var(--no);margin-left:auto}
.lnum{grid-column:2;font-size:12.5px;color:var(--mut)}.lnum b{color:var(--ink)}
.note{background:var(--warnbg);color:var(--warn);border-radius:10px;padding:10px 14px;font-size:13.5px;margin-top:12px}
ul.lim{margin:6px 0 0;padding-left:18px;color:var(--mut);font-size:13.5px}ul.lim li{margin:3px 0}
footer{color:var(--mut);font-size:12.5px;text-align:center;margin-top:8px}
@media (max-width:640px){.big{font-size:34px}.lrow{grid-template-columns:1fr}.lnum{grid-column:1}.verdict{grid-template-columns:1fr}}
"""


PAPER_CSS = """
.paper{border:2px solid var(--accent)}.ptag{display:inline-block;background:var(--accent);color:#fff;border-radius:6px;padding:1px 8px;font-size:11.5px;font-weight:700;letter-spacing:.04em;margin-right:8px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:10px 0 14px}.stat{background:var(--bg);border-radius:10px;padding:10px 12px}.stat span{display:block;color:var(--mut);font-size:11.5px}.stat b{font-size:20px}
.up{color:var(--ok)}.dn{color:var(--no)}
.fx{display:grid;grid-template-columns:1fr auto;gap:6px 12px;align-items:center;padding:9px 0;border-top:1px solid var(--line)}.fx .m{font-size:13.5px;font-weight:600}.fx .t{color:var(--mut);font-size:11.5px;font-weight:400}
.pk{display:flex;flex-wrap:wrap;gap:5px;justify-content:flex-end}.pk button{font:inherit;font-size:12px;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;padding:5px 9px;cursor:pointer;min-width:54px}.pk button:hover{border-color:var(--accent)}.pk button i{display:block;font-style:normal;color:var(--mut);font-size:10.5px}
.ctl{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:8px 0}.ctl input{font:inherit;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:6px 10px}.ctl input[type=number]{width:90px}.ctl input[type=search]{flex:1;min-width:160px}
table.t2{width:100%;border-collapse:collapse;font-size:13px}table.t2 th{color:var(--mut);font-weight:500;text-align:left;padding:4px 6px;font-size:11.5px}table.t2 td{padding:6px;border-top:1px solid var(--line)}
.scrollx{overflow-x:auto}.w{color:var(--ok);font-weight:650}.l{color:var(--no);font-weight:650}
"""

JS = """
<script>
function bet(btn){var s=parseFloat(document.getElementById('stake').value);btn.disabled=true;
fetch('/api/bet',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:btn.dataset.id,market:btn.dataset.m,sel:btn.dataset.s,stake:s})})
.then(function(r){return r.json()}).then(function(j){if(j.ok){location.reload()}else{alert(j.error||'Could not place that paper bet');btn.disabled=false}})
.catch(function(){alert('Could not reach the paper server');btn.disabled=false})}
function tick(b){b.disabled=true;b.textContent='Checking...';fetch('/api/tick',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(function(){location.reload()}).catch(function(){b.disabled=false})}
function filt(q){q=q.toLowerCase();document.querySelectorAll('.fx').forEach(function(e){e.style.display=e.dataset.q.indexOf(q)>-1?'':'none'})}
</script>
"""

SELNAME = {"H": "Home", "D": "Draw", "A": "Away", "O25": "Over 2.5", "U25": "Under 2.5"}


def _gbp(x, signed=False):
    return "n/a" if not _num(x) else (f"{'+' if signed and x > 0 else '-' if x < 0 else ''}£{abs(x):.2f}")


def _curve(curve, start) -> str:
    if len(curve) < 2:
        return '<p class="vs">The bankroll chart appears after the first paper bet settles.</p>'
    lo, hi = min(curve + [start]), max(curve + [start])
    pad = (hi - lo) * 0.1 or 1
    lo, hi = lo - pad, hi + pad
    W, H = 700, 150
    X = lambda i: 8 + i / (len(curve) - 1) * (W - 16)
    Y = lambda v: H - 10 - (v - lo) / (hi - lo) * (H - 20)
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(curve))
    col = "var(--ok)" if curve[-1] >= start else "var(--no)"
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Virtual bankroll after each settled paper bet"><line x1="0" y1="{Y(start):.1f}" x2="{W}" y2="{Y(start):.1f}" class="zero"/>'
            f'<text x="{W - 4}" y="{Y(start) - 4:.1f}" class="tick" text-anchor="end">£{start:.0f} start</text><polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.5" stroke-linejoin="round"/>'
            f'<circle cx="{X(len(curve) - 1):.1f}" cy="{Y(curve[-1]):.1f}" r="4.5" fill="{col}"/></svg>')


def _bet_rows(bets, n=30):
    if not bets:
        return '<p class="vs">None yet.</p>'
    rows = []
    for b in bets[:n]:
        st = {"won": '<span class="w">WON</span>', "lost": '<span class="l">LOST</span>'}.get(b["status"], "open")
        rows.append(f'<tr><td>{E(b["date"])}</td><td>{E(b["home"])} v {E(b["away"])}</td><td>{E(SELNAME.get(b["sel"], b["sel"]))}</td><td>{b["odds"]:.2f}</td><td>£{b["stake"]:.2f}</td>'
                    f'<td>{st}</td><td>{_gbp(b["pnl"], True) if b["pnl"] is not None else ""}</td><td>{E(b["rule"])}</td></tr>')
    return ('<div class="scrollx"><table class="t2"><tr><th>Date</th><th>Match</th><th>Pick</th><th>Price</th><th>Stake</th><th>Status</th><th>P/L</th><th>By</th></tr>'
            + "".join(rows) + "</table></div>")


def render_paper(p: dict) -> str:
    eq = p["equity"]
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
    roi = p["roi"]
    rules = "".join(f'<tr><td>{E(k)}</td><td>{v["n"]}</td><td>{v["won"]}</td><td>{_gbp(v["pnl"], True)}</td><td>{pct(v["pnl"] / v["staked"], True) if v["staked"] else "n/a"}</td></tr>' for k, v in sorted(p["by_rule"].items()))
    tick = E(p["last_tick"] or "never")
    return f"""<section class="paper"><h2><span class="ptag">PAPER</span>Paper trading · £{p["start"]:.0f} virtual bankroll</h2>
<p class="sub">Pretend money only. Nothing is ever sent to Bet365 or any bookmaker. Prices are Bet365's from football-data.co.uk's free fixtures file and may differ from what you'd see live. Last check: {tick} UTC.</p>
<div class="stats"><div class="stat"><span>Virtual bankroll</span><b class="{cls}">£{eq:.2f}</b></div><div class="stat"><span>Free to stake</span><b>£{p["available"]:.2f}</b></div>
<div class="stat"><span>Open bets</span><b>{len(p["open"])}</b></div><div class="stat"><span>Settled (won)</span><b>{p["n_settled"]} ({p["won"]})</b></div>
<div class="stat"><span>Return on stakes</span><b class="{"up" if (roi or 0) > 0 else "dn" if (roi or 0) < 0 else ""}">{pct(roi, True)}</b></div></div>
{_curve(p["curve"], p["start"])}
<h2 style="margin-top:14px">Place a paper bet</h2><div class="ctl"><label>Stake £ <input id="stake" type="number" min="{p["min_stake"]}" step="0.5" value="{p["auto_stake"]:.2f}"></label>
<input type="search" placeholder="Search team or league (e.g. Arsenal, E0)" oninput="filt(this.value)"><button class="pbtn" onclick="tick(this)" style="font:inherit;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;padding:6px 12px;cursor:pointer">Refresh prices &amp; results</button></div>
{"".join(fx) or '<p class="vs">No upcoming matches loaded yet. Press "Refresh prices &amp; results".</p>'}
<h2 style="margin-top:16px">Open paper bets</h2>{_bet_rows(p["open"])}
<h2 style="margin-top:16px">Settled paper bets</h2>{_bet_rows(p["settled"])}
{('<h2 style="margin-top:16px">By strategy</h2><div class="scrollx"><table class="t2"><tr><th>Strategy</th><th>Settled</th><th>Won</th><th>P/L</th><th>Return</th></tr>' + rules + '</table></div><p class="sub" style="margin-top:6px">V1 / V1P = automatic bets from the research rule (Shin / plain margin removal), flat £' + f"{p['auto_stake']:.2f}" + ' each. MANUAL = your clicks.</p>') if rules else ""}
</section>{JS}"""


def render(res: dict | None, paper: dict | None = None) -> str:
    rules = (res or {}).get("rules", [])
    lvl = level(res)
    scored = [r for r in rules if "roi" in r]
    passed = [r for r in scored if r["passes"]]
    if not scored:
        verdict = ('<div class="verdict empty"><div class="big">—</div><div><div class="vt">No results yet</div>'
                   '<div class="vs">Run <code>bash deploy/run_bets.sh</code> on the VM. This page shows only real results from docs/results/bets.json.</div></div></div>')
    elif passed:
        names = ", ".join(NAMES.get(r["rule"], (r["rule"],))[0] for r in passed)
        verdict = (f'<div class="verdict ok"><div class="big">{len(passed)}</div><div><div class="vt">{len(passed)} rule(s) cleared the gate: {E(names)}</div>'
                   '<div class="vs">Treat as a lead, not a result: still needs the sealed holdout season, and real prices may be worse than the historical ones.</div></div></div>')
    else:
        avg = sum(r["roi"] for r in scored) / len(scored)
        verdict = (f'<div class="verdict no"><div class="big">{pct(avg, True)}</div><div><div class="vt">No proven edge: every rule loses to the bookmaker\'s margin</div>'
                   f'<div class="vs">Average return per £1 staked across {len(scored)} pre-registered rules. A rule only counts if its whole {lvl} range is above zero after the multiple-testing penalty and it beats random betting.</div></div></div>')
    cards = []
    for r in rules:
        name, desc = NAMES.get(r["rule"], (r["rule"], ""))
        if "roi" not in r:
            cards.append(f'<div class="card"><span class="badge na">{E(str(r.get("verdict", "no result")))}</span><h3>{E(name)}</h3><div class="d">{E(desc)}</div>'
                         f'<div class="vs">Only {r.get("n", 0):,} bets: too few to judge.</div></div>')
            continue
        cls = "ok" if r["passes"] else "no"
        cards.append(
            f'<div class="card"><span class="badge {cls}">{"CLEARED GATE" if r["passes"] else "NO EDGE"}</span><h3>{E(name)}</h3><div class="d">{E(desc)}</div>'
            f'<div class="kv"><div><span>Return per £1</span><b>{pct(r["roi"], True, 2)}</b></div><div><span>{lvl} range</span><b>{pct(r["ci95_lo"], True)} to {pct(r["ci95_hi"], True)}</b></div>'
            f'<div><span>Bets · hit rate</span><b>{r["n"]:,} · {pct(r["hit_rate"])}</b></div><div><span>Beat the closing line</span><b>{pct(r.get("clv_vs_close"), True)}</b></div></div>'
            f'<div class="d" style="margin:6px 0 2px">Return by season (green up, red down)</div>{_seasons(r.get("by_season"))}</div>')
    seasons = E(str((res or {}).get("seasons", "—")))
    trials = (res or {}).get("n_trials", "—")
    body = f"""<div class="wrap"><header><h1>Bookie Engine<small>research only</small></h1>
<div class="chips">{'<span class="chip">PAPER ONLY</span>' if paper is not None else ''}<span class="chip">Seasons {seasons}</span><span class="chip">{trials} rules tried</span><span class="chip">Latest seasons sealed (never looked at)</span><span class="chip">Never places a bet</span></div></header>
{render_paper(paper) if paper is not None else ""}
{verdict}
<section><h2>Did any rule make money after the bookmaker's cut?</h2><p class="sub">Each row: profit per £1 staked at Bet365's own historical price. Dot = result, line = {lvl} range (already includes the penalty for trying several rules), blue triangle = the level random betting beats only 5% of the time.</p>
<div class="scroll">{_forest(rules, lvl) or '<p class="vs">No scored rules yet.</p>'}</div>
<div class="legend"><span><i style="background:var(--no)"></i>no proven edge</span><span><i style="background:var(--ok)"></i>cleared the gate</span><span><i style="background:var(--accent)"></i>random-bet 95th percentile</span><span>dashed line = break-even</span></div></section>
<section><h2>The rules, one by one</h2><p class="sub">Past results on past matches. A winning past is not a promise.</p><div class="cards">{"".join(cards) or '<p class="vs">Nothing to show yet.</p>'}</div></section>
<section><h2>Chance of turning £100 into £1,000</h2><p class="sub">Replaying each rule's real historical bets with 5% of the bankroll staked each time. Green = reaches £1,000, red = bankroll gone.</p>
{_lottery(rules) or '<p class="vs">No simulation yet.</p>'}
<div class="note">Even with zero margin, going all-in at even money reaches £1,000 only 10% of the time (1 in 10); with a typical 5% margin about 1 in 12. A 10x target is a lottery ticket whether or not an edge exists.</div></section>
<section><h2>What this cannot tell you</h2><ul class="lim"><li>Historical prices are closing-time snapshots; today's Bet365 price may differ.</li>
<li>Free data has no stake limits. Bet365 limits or closes accounts that win, so real profit would be lower than any backtest.</li>
<li>Only money you can afford to lose entirely. This engine never logs in, never places or suggests a bet; any bet is yours alone, at your own risk.</li></ul></section>
<footer>Generated from docs/results/bets.json · numbers are shown only if they are in that file</footer></div>"""
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bookie Engine</title><style>{CSS}{PAPER_CSS if paper is not None else ''}</style></head><body>{body}</body></html>'


def write(res_path=Path("docs/results/bets.json"), out=Path("docs/results/bets.html")) -> Path:
    res = json.loads(Path(res_path).read_text()) if Path(res_path).exists() else None
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(res))
    return out


if __name__ == "__main__":
    print("wrote", write(*(Path(a) for a in sys.argv[1:3])))
