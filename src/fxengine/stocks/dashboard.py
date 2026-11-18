"""Stocks dashboard in the FX Engine look (shares the Bookie/FX stylesheet). One self-contained HTML file built from docs/results/stocks.json and
docs/results/stocks_setups.json. Only numbers that are in those files are shown. Research only: nothing here places or advises an order.
Usage: PYTHONPATH=src python -m fxengine.stocks.dashboard   -> docs/results/stocks.html"""
from __future__ import annotations
import html, json, math, sys
from datetime import datetime
from pathlib import Path
from ..bets.dashboard import CSS as BASE_CSS, JS as _JS
from .strategies import INFO

E = html.escape
CSS = BASE_CSS + """
.badge{display:inline-block;border-radius:4px;padding:1px 8px;font-size:10px;font-weight:700;letter-spacing:.06em;color:#fff;white-space:nowrap}
.badge.v{background:#0a6e0a}.badge.w{background:#8a5f00}.badge.x{background:#9c2b2b}.badge.n{background:var(--line);color:var(--ink2)}.badge.u{background:color-mix(in srgb,var(--s1) 35%,var(--card));color:var(--ink)}
.chk{display:flex;gap:10px;flex-wrap:wrap;font-size:11.5px;margin:6px 0}.chk span{color:var(--mute)}.chk b.ok{color:#3fd13f}.chk b.no{color:#e0605a}
"""
TAB_JS = _JS.split("function bet(")[0] + "</script>"        # only the tab switcher (the Bookie part of the shared script is not needed here)


def pct(x, signed=True, d=2):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else (f"{x * 100:+.{d}f}%" if signed else f"{x * 100:.{d}f}%")


def _forest(rules) -> str:
    rs = [r for r in rules if "roi" in r]
    if not rs:
        return ""
    vals = [v for r in rs for v in (r["ci95_lo"], r["ci95_hi"], r["roi"], r.get("challenger_p95")) if isinstance(v, (int, float)) and v == v] + [0.0]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.08 or 0.005
    lo, hi = lo - pad, hi + pad
    W, LBL, RH, TOP = 760, 200, 54, 26
    H = TOP + RH * len(rs) + 34
    X = lambda v: LBL + (v - lo) / (hi - lo) * (W - LBL - 16)
    step = 0.02 if hi - lo > 0.06 else 0.01 if hi - lo > 0.03 else 0.005
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Average price gain per trade for each rule, with its confidence range">']
    t = math.ceil(lo / step) * step
    while t <= hi:
        o.append(f'<line x1="{X(t):.1f}" y1="{TOP - 6}" x2="{X(t):.1f}" y2="{H - 28}" class="gridl"/><text x="{X(t):.1f}" y="{H - 12}" class="tick" text-anchor="middle">{t * 100:+.1f}%</text>')
        t += step
    o.append(f'<line x1="{X(0):.1f}" y1="{TOP - 10}" x2="{X(0):.1f}" y2="{H - 28}" class="zero"/><text x="{X(0):.1f}" y="{TOP - 12}" class="tick" text-anchor="middle">break-even</text>')
    for i, r in enumerate(rs):
        y = TOP + RH * i + RH / 2
        name = INFO.get(r["rule"], (r["rule"], ""))[0]
        cls = "ok" if r["passes"] else "no"
        o.append(f'<text x="0" y="{y - 3:.1f}" class="rl">{E(name)}</text><text x="0" y="{y + 13:.1f}" class="rs">{r["n"]:,} trades</text>')
        for a, b in ((r["ci95_lo"], r["ci95_hi"]),):
            o.append(f'<line x1="{X(a):.1f}" y1="{y:.1f}" x2="{X(b):.1f}" y2="{y:.1f}" class="ci {cls}"/><line x1="{X(a):.1f}" y1="{y - 6:.1f}" x2="{X(a):.1f}" y2="{y + 6:.1f}" class="ci {cls}"/><line x1="{X(b):.1f}" y1="{y - 6:.1f}" x2="{X(b):.1f}" y2="{y + 6:.1f}" class="ci {cls}"/>')
        if isinstance(r.get("challenger_p95"), (int, float)) and r["challenger_p95"] == r["challenger_p95"]:
            o.append(f'<path d="M{X(r["challenger_p95"]):.1f} {y - 11:.1f} l4 -6 l-8 0 z" class="chal"><title>Random entries beat this only 5% of the time: {pct(r["challenger_p95"])}</title></path>')
        o.append(f'<circle cx="{X(r["roi"]):.1f}" cy="{y:.1f}" r="5.5" class="dot {cls}"/><text x="{min(X(r["ci95_hi"]) + 8, W - 50):.1f}" y="{y + 4:.1f}" class="val">{pct(r["roi"], d=2)}</text>')
    return "".join(o) + "</svg>"


def _badge(status: str) -> str:
    cls = {"VALID": "v", "PENDING": "n", "WEAKENING": "w", "INVALIDATED": "x", "EXIT SIGNAL": "w", "TIME STOP": "n"}.get(status, "n")
    return f'<span class="badge {cls}">{E(status)}</span>'


def _setups_tab(sp: dict | None) -> str:
    if not sp or not sp.get("setups"):
        return ('<div class="card"><h3>Setups</h3><p class="muted">No setups yet. Run <code>bash deploy/stocks_all.sh</code> on the VM; after each market close the scanner lists the setups that fired, '
                'and re-checks every earlier one against the newest prices.</p></div>')
    rows = sp["setups"]

    def table(items):
        if not items:
            return '<p class="muted">None.</p>'
        body = "".join(
            f'<tr><td><b>{E(r["symbol"].split(".")[0].upper())}</b> <span class="muted">{E(r["market"])}</span></td><td>{E(INFO.get(r["rule"], (r["rule"],))[0])}</td><td>{E(r["signal_date"])}</td>'
            f'<td class="r num">{r["close"]:,.2f}</td><td class="r num">{"" if r.get("invalidation") is None else format(r["invalidation"], ",.2f")}</td><td>{_badge(r["status"])}</td>'
            f'<td class="muted">{E(r.get("detail") or r["exit_text"])}</td><td>{"<span class=badge&#32;n>PASSED RESEARCH TEST</span>" if r["proven"] else "<span class=badge&#32;u>UNPROVEN</span>"}</td></tr>' for r in items)
        return ('<div class="scroll" style="overflow-x:auto"><table class="tbl" style="min-width:820px"><tr><th>Stock</th><th>Setup</th><th>Signal (close of)</th><th class="r">Last close</th><th class="r">Invalid below</th><th>Status</th><th>What happens next</th><th>Evidence</th></tr>'
                + body + "</table></div>")
    new = [r for r in rows if r["status"] == "PENDING"]
    live = [r for r in rows if r["status"] in ("VALID", "WEAKENING")]
    att = [r for r in rows if r["status"] in ("EXIT SIGNAL", "INVALIDATED", "TIME STOP")]
    return (f'<div class="paperbanner"><b>RESEARCH ONLY.</b> These are what the pre-registered rules flag, as of the close of {E(sp["asof"])}. Nothing here is advice or an order. Every setup is <b>UNPROVEN</b>; "passed research test" means only that the rule cleared the historical test, not that it is proven to make money. Check the stock is available to trade on Revolut before anything else.</div>'
            f'<div class="card"><h3>New for the next open · {len(new)}</h3>{table(new)}</div>'
            f'<div class="card" style="margin-top:12px"><h3>Being tracked · {len(live)}</h3>{table(live)}</div>'
            f'<div class="card" style="margin-top:12px"><h3>Needs attention · {len(att)}</h3><p class="muted" style="margin-top:0">The rule says exit, the setup is invalidated, or its time limit is up.</p>{table(att)}</div>')


def _rules_tab(res: dict | None) -> str:
    if not res:
        return '<div class="card"><p class="muted">No results yet.</p></div>'
    cards = []
    for r in res["rules"]:
        name, desc = INFO.get(r["rule"], (r["rule"], ""))
        if "roi" not in r:
            cards.append(f'<div class="card c4 rulecard"><span class="tag n">{E(str(r.get("verdict", "no result")))}</span><h4>{E(name)}</h4><div class="d">{E(desc)}</div><p class="muted">Only {r.get("n", 0):,} trades: too few to judge.</p></div>')
            continue
        g = r["gates"]
        mk = lambda ok, t: f'<b class="{"ok" if ok else "no"}">{"✓" if ok else "✗"}</b> <span>{t}</span>'
        parts = [
            f'<div class="card c4 rulecard"><span class="tag {"p" if r["passes"] else "f"}">{"PASSED" if r["passes"] else "NO EDGE"}</span><h4>{E(name)}</h4><div class="d">{E(desc)}</div>'
            f'<div class="nums"><div><small>Avg gain / trade</small><b>{pct(r["roi"])}</b></div><div><small>Range</small><b style="font-size:13px">{pct(r["ci95_lo"], d=1)} to {pct(r["ci95_hi"], d=1)}</b></div>'
            f'<div><small>Trades · wins</small><b style="font-size:14px">{r["n"]:,} · {r["hit_rate"]:.0%}</b></div><div><small>Avg hold</small><b style="font-size:14px">{"same day" if r["avg_hold"] == 0 else format(r["avg_hold"], ".0f") + " days"}</b></div>'
            f'<div><small>After costs (normal)</small><b style="font-size:14px">{pct(r["net_normal"])}</b></div><div><small>After costs (stressed)</small><b style="font-size:14px">{pct(r["net_stressed"])}</b></div></div>'
            f'<div class="chk">{mk(g["weeks"], "100+ weeks")}{mk(g["lower_bound"], "range above 0")}{mk(g["beats_random"], "beats random")}{mk(g["both_halves"], "both halves")}</div>'
        ]
        parts.append((f'<div class="muted" style="font-size:11.5px;margin-top:4px"><b>Stress checks:</b> ETFs only {pct(r["robust"]["etf_only"]["mean"]) if r["robust"].get("etf_only") else "n/a"} · outliers trimmed {pct(r["robust"]["trimmed_mean"])} · without 2008-09 &amp; 2020 {pct(r["robust"]["ex_crisis"]) if r["robust"].get("ex_crisis") is not None else "n/a"} · top 1% of trades = {r["robust"]["top1_share"] * 100:.0f}% of all gains · worst year {pct(r["robust"]["worst_year"])}</div>' if r.get("robust") else ""))
        parts.append(f'<div class="muted" style="font-size:11.5px">US {pct(r["by_market"].get("US"))} · UK {pct(r["by_market"].get("UK"))} · first half {pct(r["halves"].get("first"))} · second half {pct(r["halves"].get("second"))}</div></div>')
        cards.append("".join(parts))
    return f'<div class="grid">{"".join(cards)}</div><p class="muted" style="font-size:12px">Pass/fail uses price moves only; the two "after costs" numbers are information (see the plan for the cost assumptions).</p>'


def parts(res: dict | None, sp: dict | None = None) -> dict:
    """Everything the dashboard shows, as HTML pieces, shared by the stand-alone page and the tab inside the FX dashboard."""
    rules = (res or {}).get("rules", [])
    scored = [r for r in rules if "roi" in r]
    passed = [r for r in scored if r["passes"]]
    bm = (res or {}).get("benchmarks", {})
    if not scored:
        state, label, verdict = "warn", "NO RESULTS YET", '<div class="verdict empty"><b>No results yet.</b> <span class="muted">Run <code>bash deploy/stocks_all.sh</code> on the VM. Only real results are shown here.</span></div>'
    elif passed:
        state, label = "good", f"{len(passed)} SETUP PASSED"
        verdict = (f'<div class="verdict ok"><b>{len(passed)} rule(s) passed the price-only test: {E(", ".join(INFO[r["rule"]][0] for r in passed))}.</b> Treat as a lead: the sealed latest year has not been opened, '
                   'and the setup may still lose money after your real fees.</div>')
    else:
        state, label = "crit", "NO EDGE FOUND"
        verdict = ('<div class="verdict"><b>No rule passed.</b> None of the pre-registered setups beat random entries with a range above zero. A "no" here means no edge above the stated minimum detectable size, not proof that none exists.</div>')
    kp = ""
    if bm:
        kp = ('<div class="kpis">' + (f'<div class="kpi"><small>Buy &amp; hold SPY</small><b>{pct(bm.get("spy_cagr"), d=1)}</b><span>per year, doing nothing</span></div>' if "spy_cagr" in bm else "")
              + (f'<div class="kpi"><small>Equal-weight universe</small><b>{pct(bm.get("equal_weight_cagr"), d=1)}</b><span>per year (survivors only: flatters)</span></div>' if "equal_weight_cagr" in bm else "")
              + f'<div class="kpi"><small>Rules tested</small><b>{(res or {}).get("n_trials", "—")}</b><span>all logged, fixed in advance</span></div><div class="kpi"><small>Symbols</small><b>{(res or {}).get("symbols", "—")}</b><span>US + UK</span></div></div>')
    asof = (sp or {}).get("asof") or (res or {}).get("window", "—").split("..")[-1]
    research = (f'{verdict}{kp}<div class="card"><h3>Average gain per trade from price moves alone · each rule against its own random-entry benchmark</h3><div class="scroll">{_forest(rules) or "<p class=muted>No scored rules yet.</p>"}</div>'
                '<div class="legend"><span><i style="background:var(--s2)"></i>no edge</span><span><i style="background:var(--good)"></i>passed</span><span><i style="background:var(--s1)"></i>random-entry 95th percentile</span><span>line = confidence range after the multiple-testing penalty</span></div></div>')
    about = ('<div class="card"><h3>What this can and cannot tell you</h3><ul class="lim"><li>Research only: it never places an order and has no Revolut access. You decide and trade yourself, at your own risk.</li>'
             '<li>Daily bars only: the free data has no reliable intraday history, so day-trade rules are tested open-to-close and are optimistic (a real order fills a little after the open).</li>'
             '<li>The universe is today\'s large US and UK stocks, so it is biased toward companies that survived; long-only results look better than they would have in real time.</li>'
             '<li>Costs are assumptions until you give your real Revolut plan fees; they are shown, not part of pass/fail. Check availability of each stock on Revolut.</li>'
             '<li>The latest 365 days are sealed. They are opened once, only for a rule that has passed everything else.</li></ul></div>')
    return dict(state=state, label=label, asof=str(asof), setups=_setups_tab(sp), research=research, rules=_rules_tab(res), about=about)


def render(res: dict | None, sp: dict | None = None) -> str:
    x = parts(res, sp)
    tabs = [("setups", "Setups"), ("research", "Research"), ("rules", "Rules"), ("about", "About")]
    sections = "".join(f'<div class="tab" id="{k}">{x[k]}</div>' for k, _ in tabs)
    body = (f'<div class="wrap"><div class="top"><span class="brand">STOCKS ENGINE</span><span class="pill {x["state"]}">{x["label"]}</span><span class="chip">as of {E(x["asof"])}</span><span class="chip">research only · never places an order</span>'
            f'<span class="sp"></span><span class="mono muted">{datetime.now().strftime("%a %d %b %Y %H:%M")}</span></div>'
            f'<div class="tabs">{"".join(f"<button data-t=\'{k}\'>{v}</button>" for k, v in tabs)}</div>{sections}<footer>Generated from docs/results/stocks.json · numbers shown only if they are in that file</footer></div>')
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Stocks Engine</title><style>{CSS}</style></head><body>{body}{TAB_JS}</body></html>'


def write(res_path=Path("docs/results/stocks.json"), out=Path("docs/results/stocks.html"), setups_path=None) -> Path:
    rp = Path(res_path)
    sp_path = Path(setups_path) if setups_path else rp.with_name("stocks_setups.json")
    res = json.loads(rp.read_text()) if rp.exists() else None
    sp = json.loads(sp_path.read_text()) if sp_path.exists() else None
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(res, sp))
    return out


if __name__ == "__main__":
    print("wrote", write(*(Path(a) for a in sys.argv[1:3])))
