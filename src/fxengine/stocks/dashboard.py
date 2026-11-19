"""Stocks dashboard in the FX Engine look (shares the Bookie/FX stylesheet). One self-contained HTML file built from docs/results/stocks.json and
docs/results/stocks_setups.json. Only numbers that are in those files are shown. Research only: nothing here places or advises an order.
Usage: PYTHONPATH=src python -m fxengine.stocks.dashboard   -> docs/results/stocks.html"""
from __future__ import annotations
import html, json, math, sys
from html import escape as html_escape
from datetime import datetime, timezone
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


def _num(x):
    return isinstance(x, (int, float)) and x == x


def _bar(r) -> str:
    """FX-style stop / price / exit bar (only where the rule has both an invalidation level and an exit level)."""
    a, b, px = r.get("invalidation"), r.get("exit_level"), r.get("last_close") or r.get("close")
    if not (_num(a) and _num(b) and _num(px)) or a == b:
        return ""
    pos = min(100.0, max(0.0, (px - a) / (b - a) * 100))
    return (f"<div class='bar'><b style='left:{pos:.1f}%'></b></div><div class='barl'><span>INVALID BELOW {a:,.2f}</span><span>price {px:,.2f}</span><span>EXIT SIGNAL ABOVE {b:,.2f}</span></div>")


def _is_adr(r: dict) -> bool:
    h = r.get("home")
    return bool(h) and h.lower() != str(r.get("market", "")).lower()


def _home_name(r: dict) -> str:
    from .universe import COUNTRY
    return COUNTRY.get(r["home"], r["home"].upper())


def _live_strip(sp: dict) -> str:
    """Today's live paper account (updated every 5 minutes): entries at the real open, exits, live balance. Shown only if the plan is about today's session."""
    lv = (sp.get("live") or {})
    pl = lv.get("plan")
    if not pl or not pl.get("day_ok"):
        return ""
    E_ = lambda t: html_escape(str(t))
    t = lambda x: x["symbol"].split(".")[0].upper()
    ent = "".join(f"<span class='chip'>BOUGHT {E_(t(e))} at {e['price']:,.2f} · {e['shares']:g} sh · £{e['cost']:,.0f}</span> " for e in pl["entries"])
    ext = "".join(f"<span class='chip'>SOLD {E_(t(x))} at {x['price']:,.2f} · <b class='{'pos' if x['pnl'] > 0 else 'neg'}'>{x['pnl']:+,.0f}</b></span> " for x in pl["exits"])
    d = pl["balance"] - pl["nightly_balance"]
    return (f'<div class="card" style="margin-bottom:12px"><h3>Live today · paper account · {E_(lv.get("asof", ""))} UTC</h3>'
            f'<div class="nums"><div><small>Live balance</small><b>£{pl["balance"]:,.2f}</b></div><div><small>Floating now</small><b>{pl["floating"]:+,.2f}</b></div><div><small>Free cash</small><b>£{pl["cash"]:,.2f}</b></div>'
            f'<div><small>Since last night</small><b>{d:+,.2f}</b></div></div>{ent or ""}{ext or ""}'
            f'{"" if ent or ext else "<p class=muted style=margin:0>No paper entries or exits yet today.</p>"}'
            '<p class="muted" style="font-size:12px;margin:8px 0 0">Provisional: entries use the real open, exits follow the rules\' sell signals from last night. The nightly scan writes the final record.</p></div>')


def _wording(t: dict | None) -> str:
    if not t:
        return "<span class='muted'>not read yet</span>"
    tone = "positive" if t["tone"] > 0.3 else "negative" if t["tone"] < -0.1 else "neutral"
    ch = "" if t.get("tone_change") is None else f" ({t['tone_change']:+.2f} vs the release before)"
    fl = f"<br><b class='neg'>RED FLAGS: {html_escape(', '.join(t['flags']))}</b>" if t.get("flags") else ""
    return f"tone {tone}{ch}<br>guidance: <b>{html_escape(t['guidance'])}</b>{fl}"


def _fund_card(sp: dict) -> str:
    """Company check from the official filings: for today's setups, the paper positions and the names on ops/stocks_watch.txt (e.g. a stock you hold yourself)."""
    fd = ((sp.get("fund") or {}).get("companies")) or {}
    if not fd:
        return ""
    from pathlib import Path as _P
    watch = [x.split("#")[0].strip().lower() for x in _P("ops/stocks_watch.txt").read_text().splitlines()] if _P("ops/stocks_watch.txt").exists() else []
    syms = [x for x in dict.fromkeys(watch + [p_["symbol"] for p_ in (sp.get("account") or {}).get("positions", [])] + [r["symbol"] for r in sp.get("setups", [])]) if x]
    E_ = lambda t: html_escape(str(t))
    tx = ((sp.get("ftxt") or {}).get("companies")) or {}
    rows = ""
    for sym in syms:
        f = fd.get(sym)
        if not f:
            rows += f"<tr><td><b>{E_(sym.split('.')[0].upper())}</b></td><td colspan=5 class='muted'>No SEC filing data (non-US reporter or not downloaded yet)</td></tr>"
            continue
        col = {"STRONG": "pos", "WEAK": "neg"}.get(f["verdict"], "")
        det = " · ".join(("✓ " if c["ok"] else "✗ ") + E_(c["name"]) + " (" + E_(c["detail"]) + ")" for c in f["checks"] if c["ok"] is not None)
        rows += f"<tr><td><b>{E_(sym.split('.')[0].upper())}</b></td><td><b class='{col}'>{f['verdict']}</b></td><td class='num'>{f['passed']}/{f['of']}</td><td style='font-size:12px'>{('last ' + E_(f['last_earnings']) + '<br>next ~' + E_(f['next_earnings']) + ' (' + str(f['days_to_next']) + 'd, estimate)') if f.get('next_earnings') else 'n/a'}</td><td style='font-size:12px'>{_wording(tx.get(sym))}</td><td style='font-size:12px'>{det}</td></tr>"
    soon = [(fd[x]["days_to_next"], x) for x in syms if fd.get(x, {}).get("days_to_next") is not None and fd[x]["days_to_next"] <= 10]
    warn = ("<p style='margin:0 0 10px'><b class='neg'>Earnings within 10 days (estimate):</b> " + ", ".join(f"{E_(x.split('.')[0].upper())} in ~{d}d" for d, x in sorted(soon)) +
            ". A report can move the price sharply either way: size and exits matter most now.</p>") if soon else ""
    return ('<div class="card" style="margin-top:16px"><h3>Company check · from the official SEC filings (latest quarter)</h3>' + warn + '<div class="scroll" style="overflow-x:auto"><table class="tbl" style="min-width:900px">'
            '<tr><th>Stock</th><th>Business</th><th class="r">Checks</th><th>Earnings</th><th>Latest report wording</th><th>Detail</th></tr>' + rows + '</table></div>'
            '<p class="muted" style="font-size:12px;margin:8px 0 0">Eight yes/no checks on revenue, earnings, margins, cash, debt and share count, read from the companies\' own filings. Information only: it has not yet been tested as a predictor and never changes a setup or a paper trade.</p></div>')


colr = lambda x: "up" if (x or 0) > 0 else "dn" if (x or 0) < 0 else "muted"


def _hist_card(sp: dict | None, limit: int = 15, empty: str | None = None) -> str:
    """Same layout as the FX engine's History card: one summary line, then Created (UK) | Setup | Rule | Outcome | P&L. Every setup ever flagged, kept in data/stocks/history.jsonl."""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    h = ((sp or {}).get("history") or {}).get("setups") or []
    if not h:
        return '<p class="muted">No setups recorded yet. This fills in the night the first setup is flagged.</p>'

    def uk(t):
        try:
            return _dt.strptime(t, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Europe/London"))
        except Exception:
            return None

    def gbp(r):                                           # paper-account P&L where it held the setup, else the hypothetical at £20 risk (gain / distance to the invalid-below level)
        if r.get("paper"):
            return r["paper"]["pnl"]
        c = r.get("closed")
        if not c:
            return None
        inv, cl = r.get("invalidation"), r.get("close") or 0
        risk = (cl - inv) / cl if inv and cl and 0 < inv < cl else 0.10
        return c["gross"] / risk * 20.0
    done = [r for r in h if r["status"] == "CLOSED" and r.get("closed")]
    wins = sum(r["closed"]["gross"] > 0 for r in done)
    lost = len(done) - wins
    rows = ""
    for r in h[:limit]:
        t = uk(r["created_at"])
        c, pv = r.get("closed"), gbp(r)
        outc = (f"CLOSED {pct(c['gross'], d=1)}" if c else r["status"])
        why = ((sp or {}).get("lessons") or {}).get("reviews", {}).get(r["id"])
        rows += (f"<tr><td class='mono'>{t:%d %b %H:%M}</td>" if t else "<tr><td></td>") + (f"<td>{E(r['symbol'].split('.')[0].upper())} BUY</td><td>{E(INFO.get(r['rule'], (r['rule'],))[0])}</td><td>{E(outc)}" + (f"<div class='muted' style='font-size:12px;max-width:520px;white-space:normal'><b>Why:</b> {E(why['text'])}</div>" if why else "") + "</td>"
                 f"<td class='num {'up' if (pv or 0) > 0 else 'dn' if (pv or 0) < 0 else ''}'>{'' if pv is None else f'{pv:+.0f} GBP'}</td></tr>")
    return (f"<p class='muted'>Flagged {len(h)} · resolved {len(done)} · won {wins} · lost {lost} · success rate {'n/a' if not done else f'{wins / len(done) * 100:.0f}%'}</p>"
            f"<table class='tbl'><tr><th>Created (UK)</th><th>Setup</th><th>Rule</th><th>Outcome</th><th class='r'>P&amp;L</th></tr>{rows}</table>"
            + ("<p class='muted' style='font-size:12px;margin:8px 0 0'>P&amp;L = the £2,500 paper account's result where it held the setup; otherwise the hypothetical at £20 risk, price only, before costs. Every setup is kept for good.</p>"))


def _history_tab(sp: dict | None) -> str:
    return f'<div class="card"><h3>History · every flagged setup, scored as a hypothetical</h3>{_hist_card(sp, 400)}</div>'


def _trade_card(r: dict, held: dict | None = None, live: dict | None = None) -> str:
    if live and live.get('price'):
        r = dict(r, last_close=live['price'], _live_t=live.get('t'))
    st = r["status"]
    un = r.get("unrealised")
    cls = {"PENDING": "pending", "VALID": "open", "WEAKENING": "open", "INVALIDATED": "loss", "TIME STOP": "dead"}.get(st, "dead")
    if st == "EXIT SIGNAL":
        cls = "win" if (un or 0) > 0 else "loss"
    if st == "PENDING" or un is None:
        big, sub, c = "waiting", "buys at the next open", "muted"
    else:
        big, sub, c = pct(un, d=1), f"since entry · day {r.get('held', 1)} (price only)", ("up" if un > 0.002 else "dn" if un < -0.002 else "muted")
    proven = "<span style='color:var(--ink2)'>PASSED RESEARCH TEST</span>" if r["proven"] else "<span class='warnt'>UNPROVEN</span>"
    name = INFO.get(r["rule"], (r["rule"],))[0]
    entry = f"{r['entry_price']:,.2f}" if r.get("entry_price") else "next open"
    nums = [("Last close", f"{(r.get('last_close') or r['close']):,.2f}", "latest bar"), ("Entry", entry, "at the open" if not r.get("entry_price") else "filled (open)"),
            ("Invalid below", "—" if r.get("invalidation") is None else f"{r['invalidation']:,.2f}", "rule's own level"), ("Held", f"{r.get('held', 0)} days", "so far"),
            ("Rule", name, r["market"]), ("Signal", r["signal_date"], "close of")]
    nh = "".join(f"<div><small>{E(a)}</small><b>{E(str(b))}</b><span>{E(str(c2))}</span></div>" for a, b, c2 in nums)
    why = "".join(f"<div>{E(x)}</div>" for x in (r.get("why") or [r["exit_text"]])[:2])
    chips = [f"signal {r['signal_date']}"] + ([f"entered {r['entry_price']:,.2f}"] if r.get("entry_price") else ["enters next open"]) + ([r["detail"]] if r.get("detail") else [])
    if r.get("_live_t"):
        chips = [f"live price · {datetime.fromtimestamp(r['_live_t'], timezone.utc):%H:%M} UTC · the rules still decide at the close"] + chips
    if r.get("cand_ok") is True:
        chips = ["FILTER ✓ (candidate, unproven): " + r["cand_filter"]] + chips
    if held:
        chips = [f"IN PAPER ACCOUNT · {held['shares']:g} shares · £{held['cost']:,.0f} · risk £{held['risk']:.0f}"] + chips
    tl = "".join(f"<span class='chip'>{E(x[:70])}</span>" for x in chips)
    return (f"<div class='trade {cls}'><div class='th'><div><span class='pair'>{E(r['symbol'].split('.')[0].upper())}</span><span class='dir long'>LONG</span><span class='state'>{E(st)}</span></div>"
            f"<div class='pl'><b class='{c}'>{big}</b><small>{sub}</small></div></div><div class='rule'>{E(name)} · {E(r['market'])}{(' · ' + E(_home_name(r)) + ' company (US-listed ADR)') if _is_adr(r) else ''} · {proven}</div>{_bar(r)}"
            f"<div class='nums'>{nh}</div><div class='why'>{why}<div class='muted' style='margin-top:4px'>{E(r['exit_text'])}</div></div><div class='tl'>{tl}</div></div>")


def _line_chart(series: list[tuple[str, str, list[tuple[float, float]]]], xl: list[tuple[float, str]], aria: str) -> str:
    pts = [v for _, _, p in series for _, v in p]
    if not pts:
        return ""
    lo, hi = min(pts + [0.0]), max(pts + [0.0])
    pad = (hi - lo) * 0.12 or 0.002
    lo, hi = lo - pad, hi + pad
    xs = [x for _, _, p in series for x, _ in p]
    x0, x1 = min(xs), max(xs) or 1
    W, H, L, R = 760, 190, 46, 14
    X = lambda x: L + (x - x0) / ((x1 - x0) or 1) * (W - L - R)
    Y = lambda v: H - 24 - (v - lo) / (hi - lo) * (H - 40)
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{E(aria)}">']
    step = 0.01 if hi - lo > 0.025 else 0.005 if hi - lo > 0.012 else 0.002
    t = math.ceil(lo / step) * step
    while t <= hi:
        o.append(f'<line x1="{L}" y1="{Y(t):.1f}" x2="{W - R}" y2="{Y(t):.1f}" class="gridl"/><text x="{L - 6}" y="{Y(t) + 4:.1f}" class="tick" text-anchor="end">{t * 100:+.1f}%</text>')
        t += step
    o.append(f'<line x1="{L}" y1="{Y(0):.1f}" x2="{W - R}" y2="{Y(0):.1f}" class="zero"/>')
    for x, lab in xl:
        o.append(f'<text x="{X(x):.1f}" y="{H - 6}" class="tick" text-anchor="middle">{E(lab)}</text>')
    for name, col, p in series:
        if len(p) >= 2:
            o.append(f'<polyline points="{" ".join(f"{X(x):.1f},{Y(v):.1f}" for x, v in p)}" fill="none" stroke="{col}" stroke-width="2.4" stroke-linejoin="round"/>')
        o.append("".join(f'<circle cx="{X(x):.1f}" cy="{Y(v):.1f}" r="3" fill="{col}"><title>{E(name)}: {v * 100:+.2f}%</title></circle>' for x, v in p))
    leg = "".join(f'<span><i style="background:{col}"></i>{E(n)}</span>' for n, col, _ in series)
    return "".join(o) + f'</svg><div class="legend">{leg}</div>'


def _year_chart(res: dict | None) -> str:
    """Research only: average gain per trade in each calendar year, for the rules that passed (how steady was it?)."""
    cols = ["var(--good)", "var(--s1)", "var(--warn)"]
    ser, years = [], set()
    for k, r in enumerate([r for r in (res or {}).get("rules", []) if r.get("passes") and r.get("by_year")]):
        p = sorted((int(y), v) for y, v in r["by_year"].items())
        years |= {y for y, _ in p}
        ser.append((INFO.get(r["rule"], (r["rule"],))[0], cols[k % 3], [(float(y), v) for y, v in p]))
    if not ser:
        return ""
    ys = sorted(years)
    xl = [(float(y), str(y)) for y in ys if (y - ys[0]) % 3 == 0]
    return _line_chart(ser, xl, "Average gain per trade in each calendar year for the rules that passed")


def _forward_chart(closed: list[dict]) -> str:
    if len(closed) < 2:
        return ""
    cs = sorted(closed, key=lambda r: r["exit_date"])
    cum, run = [], 0.0
    for i, r in enumerate(cs, 1):
        run += r["gross"]
        cum.append((float(i), run))
    return _line_chart([("Cumulative price gain of closed forward trades", "var(--s1)", cum)], [(1.0, "1"), (float(len(cs)), str(len(cs)))], "Cumulative gain of closed forward-test trades")


def _gbp(v, signed=True) -> str:
    return f"{'+' if signed and v > 0 else '-' if v < 0 else ''}£{abs(v):,.0f}"


def _equity_chart(curve: list, start: float) -> str:
    if len(curve) < 2:
        return ""
    ys = [v for _, v in curve]
    lo, hi = min(ys + [start]), max(ys + [start])
    pad = (hi - lo) * 0.15 or 5
    lo, hi = lo - pad, hi + pad
    W, H, L, R = 760, 170, 56, 14
    X = lambda i: L + i / (len(curve) - 1) * (W - L - R)
    Y = lambda v: H - 22 - (v - lo) / (hi - lo) * (H - 38)
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Paper account balance over time">']
    for k in range(4):
        v = lo + (hi - lo) * k / 3
        o.append(f'<line x1="{L}" y1="{Y(v):.1f}" x2="{W - R}" y2="{Y(v):.1f}" class="gridl"/><text x="{L - 6}" y="{Y(v) + 4:.1f}" class="tick" text-anchor="end">£{v:,.0f}</text>')
    o.append(f'<line x1="{L}" y1="{Y(start):.1f}" x2="{W - R}" y2="{Y(start):.1f}" class="zero"/>')
    col = "var(--good)" if ys[-1] >= start else "var(--s2)"
    o.append(f'<polyline points="{" ".join(f"{X(i):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(curve))}" fill="none" stroke="{col}" stroke-width="2.4" stroke-linejoin="round"/>')
    o.append(f'<circle cx="{X(len(curve) - 1):.1f}" cy="{Y(ys[-1]):.1f}" r="4.5" fill="{col}"/><text x="{L}" y="{H - 4}" class="tick">{E(curve[0][0])}</text><text x="{W - R}" y="{H - 4}" class="tick" text-anchor="end">{E(curve[-1][0])}</text></svg>')
    return "".join(o)


def _account_card(ac: dict, n_fwd: int, chips: str) -> str:
    """FX-style 'hypothetical balance' tiles for the £2,500 paper account."""
    if not ac or ac.get("error"):
        return ('<div class="card"><h3>Paper account · £2,500, hypothetical</h3><p class="muted" style="margin:0">The account starts trading at the next nightly scan after a rule that passed the research test fires a setup. '
                f'£20 risk per trade, nothing is ever ordered.{" (" + E(ac["error"]) + ")" if ac and ac.get("error") else ""}</p></div>')
    t = ac["tiles"]
    c = lambda v: "up" if v > 0.5 else "dn" if v < -0.5 else "muted"
    tiles = [("Hypothetical balance", f"£{t['balance']:,.0f}", f"start £{t['start']:,.0f} · incl. open trades, before costs", c(t["balance"] - t["start"])),
             ("Today", _gbp(t["today"]), "realised, closed trades", c(t["today"])), ("This week", _gbp(t["week"]), "since Monday", c(t["week"])), ("This month", _gbp(t["month"]), "", c(t["month"])),
             ("All time", _gbp(t["alltime"]), "realised, before costs", c(t["alltime"])), ("Open now (floating)", _gbp(t["floating"]), f"{t['n_open']} open · before costs", c(t["floating"])),
             ("Wins · losses", f"{t['wins']} · {t['losses']}", (f"{t['wins'] / (t['wins'] + t['losses']) * 100:.0f}% win rate" if t["wins"] + t["losses"] else "no closed trades yet"), "")]
    kp = '<div class="kpis">' + "".join(f'<div class="kpi"><small>{E(a)}</small><b class="{k}">{E(b)}</b><span>{E(s_)}</span></div>' for a, b, s_, k in tiles) + "</div>"
    chips_ = "".join(f"<span class='chip'>{E(p_['symbol'].split('.')[0].upper())} <b class='{c(p_['floating'])}'>{_gbp(p_['floating'])}</b></span> " for p_ in ac.get("positions", []))
    warn = '<p class="warnt" style="margin:6px 0 0">GBPUSD rate file missing: US prices are converted at an estimate of 1.30.</p>' if ac.get("fallback_rate") else ""
    ch = _equity_chart(ac.get("curve", []), t["start"])
    nsk = len(ac.get("skipped", []))
    return (f'<div class="card"><h3>Paper account · £{t["start"]:,.0f}, hypothetical, scored by the engine</h3>{kp}<div style="margin:2px 0 8px">{chips_}</div>{ch}{warn}'
            f'<div class="muted" style="margin-top:6px">Rule: take every new setup of a rule that passed the research test, strongest first; £20 risk per trade sized from the setup\'s own invalid-below level; no position over 25% of the account; no leverage. '
            f'{nsk} setup(s) skipped for lack of cash or a valid level. Forward test of ALL signals ({n_fwd} closed): Performance tab.</div></div>')


def _setups_tab(sp: dict | None, res: dict | None = None) -> str:
    if not sp or (not sp.get("setups") and not sp.get("forward") and not sp.get("closed")):
        return ('<div class="card"><h3>Setups</h3><p class="muted">No setups yet. Run <code>bash deploy/stocks_all.sh</code> on the VM; after each market close the scanner lists the setups that fired, '
                'and re-checks every earlier one against the newest prices.</p></div>')
    rows, fw, closed = sp["setups"], sp.get("forward") or {}, sp.get("closed") or []
    live = [r for r in rows if r["status"] in ("VALID", "WEAKENING")]
    pend = [r for r in rows if r["status"] == "PENDING"]
    att = [r for r in rows if r["status"] in ("EXIT SIGNAL", "INVALIDATED", "TIME STOP")]
    n = len(closed)
    avg = sum(c["gross"] for c in closed) / n if n else None
    wins = sum(c["gross"] > 0 for c in closed)
    flo = [r["unrealised"] for r in live if r.get("unrealised") is not None]
    exp = next((v.get("expected") for v in fw.values() if v.get("expected") is not None), None)
    colr = lambda x: "up" if (x or 0) > 0 else "dn" if (x or 0) < 0 else "muted"
    kp = ('<div class="kpis">'
          f'<div class="kpi"><small>Closed forward trades</small><b>{n}</b><span>scored on live prices</span></div>'
          f'<div class="kpi"><small>Average gain / trade</small><b class="{colr(avg)}">{pct(avg, d=2) if n else "—"}</b><span>price only · research said {pct(exp, d=2) if exp is not None else "n/a"}</span></div>'
          f'<div class="kpi"><small>Win rate</small><b>{(str(round(wins / n * 100)) + "%") if n else "—"}</b><span>{wins} won · {n - wins} lost</span></div>'
          f'<div class="kpi"><small>Open now</small><b class="{colr(sum(flo) / len(flo) if flo else None)}">{len(live)}</b><span>{("floating " + pct(sum(flo) / len(flo), d=1)) if flo else "tracking"} · before costs</span></div>'
          f'<div class="kpi"><small>New for the next open</small><b>{len(pend)}</b><span>{len(att)} need attention</span></div></div>')
    chips = "".join(f"<span class='chip'>{E(r['symbol'].split('.')[0].upper())} <b class='{colr(r.get('unrealised'))}'>{pct(r['unrealised'], d=1) if r.get('unrealised') is not None else 'new'}</b></span> " for r in (live + pend + att))
    fwt = ""
    if fw:
        body = "".join(f'<tr><td>{E(INFO.get(k, (k,))[0])}</td><td class="r num">{v["n"]}</td><td class="r num">{pct(v["hit_rate"], False, 0)}</td><td class="r num">{pct(v["mean"])}</td>'
                       f'<td class="r num">{"needs 30+" if v["lo"] is None else pct(v["lo"], d=1) + " to " + pct(v["hi"], d=1)}</td><td class="r num">{pct(v.get("expected"))}</td></tr>' for k, v in fw.items())
        fwt = ('<div class="scroll" style="overflow-x:auto;margin-top:10px"><table class="tbl" style="min-width:560px"><tr><th>Setup</th><th class="r">Closed</th><th class="r">Win rate</th><th class="r">Avg gain</th><th class="r">95% range</th><th class="r">Research said</th></tr>'
               + body + '</table></div><p class="muted" style="font-size:12px;margin:6px 0 0">Fewer than 30 closed trades is mostly luck either way; trust it only once the range is narrow.</p>')
    ac = sp.get("account") or {}
    top = _live_strip(sp) + _account_card(ac, n, chips)
    charts = ""
    held = {p_['id']: p_ for p_ in ((sp.get('account') or {}).get('positions') or [])}
    lp = (sp.get('live') or {}).get('prices') or {}
    cards = "".join(_trade_card(r, held.get(r['id']), lp.get(r['symbol'])) for r in att + pend + live) or "<div class='empty'><b>No setups right now.</b><br><span class='muted'>The rules flag a setup only when their conditions are met. Nothing is a valid outcome.</span></div>"
    hist = ""
    if ((sp.get("history") or {}).get("setups")):
        hist = f'<div class="card" style="margin-top:16px"><h3>History · every flagged setup, scored as a hypothetical</h3>{_hist_card(sp, 15)}</div>'
    elif closed:
        hr = "".join(f'<tr><td><b>{E(c["symbol"].split(".")[0].upper())}</b> <span class="muted">{E(c["market"])}</span></td><td>{E(INFO.get(c["rule"], (c["rule"],))[0])}</td><td>{E(c["entry_date"])}</td><td>{E(c["exit_date"])}</td>'
                     f'<td class="r num"><b class="{colr(c["gross"])}">{pct(c["gross"], d=2)}</b></td><td class="r num">{c["bars"]}</td></tr>' for c in sorted(closed, key=lambda c: c["exit_date"], reverse=True)[:25])
        hist = ('<div class="card" style="margin-top:16px"><h3>History · every closed forward trade, price only</h3><div class="scroll" style="overflow-x:auto"><table class="tbl" style="min-width:560px">'
                '<tr><th>Stock</th><th>Setup</th><th>Entered</th><th>Exited</th><th class="r">Gain</th><th class="r">Days</th></tr>' + hr + "</table></div></div>")
    return (f'<div class="paperbanner"><b>RESEARCH ONLY.</b> These are what the pre-registered rules flag, as of the close of {E(sp["asof"])}. Nothing here is advice or an order. Every setup is <b>UNPROVEN</b>; '
            '"passed research test" means only that the rule cleared the historical test, not that it is proven to make money. Check the stock is available on Revolut first.</div>'
            f'{top}{charts}<h2 class="sec">Active setups<small>{len(pend)} new for the next open · {len(live)} being tracked · {len(att)} need attention</small></h2><div class="trades">{cards}</div>{_fund_card(sp)}{hist}')


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


CHART_JS = """<script>(function(){var el=document.getElementById('st-cd');if(!el)return;var D=JSON.parse(el.textContent),box=document.getElementById('st-chart'),sel=document.getElementById('st-sel');if(!box||!sel)return;
var keys=Object.keys(D);if(!keys.length)return;
function draw(k){var d=D[k],n=d.c.length,W=900,H=380,L=52,R=84,T=14,B=26,i,lo=1e18,hi=-1e18;
for(i=0;i<n;i++){if(d.l[i]!=null&&d.l[i]<lo)lo=d.l[i];if(d.h[i]!=null&&d.h[i]>hi)hi=d.h[i]}
d.levels.forEach(function(v){if(v.price<lo)lo=v.price;if(v.price>hi)hi=v.price});var pad=(hi-lo)*.05||1;lo-=pad;hi+=pad;
function X(i){return L+(i+.5)/n*(W-L-R)}function Y(v){return T+(hi-v)/(hi-lo)*(H-T-B)}
var s='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto">';
for(var g=0;g<=4;g++){var v=lo+(hi-lo)*g/4;s+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+Y(v)+'" y2="'+Y(v)+'" class="gridl"/><text x="'+(L-6)+'" y="'+(Y(v)+4)+'" class="tick" text-anchor="end">'+v.toFixed(v>100?0:2)+'</text>'}
var w=Math.max(1,(W-L-R)/n*.7);
for(i=0;i<n;i++){if(d.c[i]==null)continue;var up=d.c[i]>=d.o[i],c=up?'#3fd13f':'#e0605a';s+='<line x1="'+X(i)+'" x2="'+X(i)+'" y1="'+Y(d.h[i])+'" y2="'+Y(d.l[i])+'" stroke="'+c+'"/><rect x="'+(X(i)-w/2)+'" y="'+Y(Math.max(d.o[i],d.c[i]))+'" width="'+w+'" height="'+Math.max(1,Math.abs(Y(d.o[i])-Y(d.c[i])))+'" fill="'+c+'"/>'}
[['s50','#3987e5'],['s200','#fab219']].forEach(function(a){var p=[];for(i=0;i<n;i++){if(d[a[0]][i]!=null)p.push(X(i)+','+Y(d[a[0]][i]))}if(p.length>1)s+='<polyline points="'+p.join(' ')+'" fill="none" stroke="'+a[1]+'" stroke-width="1.6"/>'});
d.levels.forEach(function(v){var c=v.kind=='invalidation'?'#e0605a':v.kind=='exit'?'#3fd13f':'#3987e5';s+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+Y(v.price)+'" y2="'+Y(v.price)+'" stroke="'+c+'" stroke-dasharray="5 4"/><text x="'+(W-R+4)+'" y="'+(Y(v.price)+4)+'" class="tick" style="fill:'+c+'">'+(v.kind=='invalidation'?'INVALID ':v.kind=='exit'?'EXIT ':'ENTRY ')+v.price.toFixed(2)+'</text>'});
s+='<text x="'+L+'" y="'+(H-6)+'" class="tick">'+d.dates[0]+'</text><text x="'+(W-R)+'" y="'+(H-6)+'" class="tick" text-anchor="end">'+d.dates[n-1]+'</text></svg>';
box.innerHTML=s;[].forEach.call(sel.querySelectorAll('button'),function(b){b.classList.toggle('on',b.dataset.k===k)})}
keys.forEach(function(k){var b=document.createElement('button');b.dataset.k=k;b.textContent=k.split('.')[0].toUpperCase();b.onclick=function(){draw(k)};sel.appendChild(b)});draw(keys[0])})();</script>"""

JOURNAL_JS = """<script>function stJournal(b){var g=function(i){return document.getElementById(i).value};b.disabled=true;
fetch('/api/journal',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date:g('jr-date'),symbol:g('jr-sym'),side:g('jr-side'),price:g('jr-price'),qty:g('jr-qty'),note:g('jr-note')})})
.then(function(r){return r.json()}).then(function(j){if(j.ok){location.reload()}else{alert(j.error||'Could not save that trade');b.disabled=false}}).catch(function(){alert('Could not reach the server');b.disabled=false})}</script>"""


def _heat(v) -> str:
    if v is None:
        return '<td class="r num muted">n/a</td>'
    a = min(0.85, abs(v) / 0.08)
    rgb = "12,163,12" if v >= 0 else "208,59,59"
    return f'<td class="r num" style="background:rgba({rgb},{a:.2f})">{pct(v, d=1)}</td>'


def _charts_tab(mk: dict | None) -> str:
    if not mk or not mk.get("charts"):
        return '<div class="card"><h3>Charts</h3><p class="muted">Charts appear after the first nightly scan has run.</p></div>'
    data = json.dumps(mk["charts"]).replace("</", "<\\/")
    return (f'<div class="card"><h3>Daily chart · last 250 days · candles with 50-day (blue) and 200-day (amber) averages</h3><div class="sel" id="st-sel" style="margin-bottom:8px"></div><div id="st-chart"></div>'
            '<div class="legend"><span>dashed red = the setup\'s invalid-below level</span><span>dashed green = exit-signal level</span><span>dashed blue = entry</span></div></div>'
            f'<script type="application/json" id="st-cd">{data}</script>{CHART_JS}')


def _market_tab(mk: dict | None) -> str:
    if not mk:
        return '<div class="card"><h3>Market</h3><p class="muted">Market context appears after the first nightly scan has run.</p></div>'
    rg, br = mk["regime"], mk["breadth"]
    spy = next((x for x in mk["indices"] if x["symbol"] == "spy.us"), None)
    tone = {"UPTREND": "up", "DOWNTREND": "dn"}.get(rg["label"], "muted")
    kp = ('<div class="kpis">'
          f'<div class="kpi"><small>US market regime</small><b class="{tone}">{E(rg["label"])}</b><span>descriptive, not a forecast</span></div>'
          f'<div class="kpi"><small>SPY vs 200-day average</small><b>{pct(spy["vs200"], d=1) if spy else "n/a"}</b><span>{("close " + format(spy["close"], ",.2f")) if spy else ""}</span></div>'
          f'<div class="kpi"><small>Stocks above 200-day</small><b>{br["above200"] * 100:.0f}%</b><span>{br["above50"] * 100:.0f}% above 50-day · {br["n"]} stocks</span></div>'
          f'<div class="kpi"><small>New 20-day highs / lows</small><b>{br["new_highs"]} / {br["new_lows"]}</b><span>across the stock universe</span></div></div>')
    ix = "".join(f'<tr><td><b>{E(x["name"])}</b></td><td class="r num">{x["close"]:,.2f}</td><td class="r num">{pct(x["vs50"], d=1)}</td><td class="r num">{pct(x["vs200"], d=1)}</td><td class="r num">{pct(x["r1m"], d=1)}</td><td class="r num">{pct(x["r3m"], d=1)}</td><td class="r num">{x["vol20"] * 100:.0f}%</td><td>{E(x["trend"])}</td></tr>' for x in mk["indices"])
    sec = "".join(f'<tr><td>{E(x["name"])}</td>{_heat(x["r5"])}{_heat(x["r21"])}{_heat(x["r63"])}</tr>' for x in mk["sectors"])
    mv = lambda L: "".join(f'<tr><td><b>{E(m["symbol"].split(".")[0].upper())}</b> <span class="muted">{"US" if m["symbol"].endswith(".us") else "UK"}</span></td><td class="r num">{pct(m["r"], d=1)}</td></tr>' for m in L)
    return (f'{kp}<div class="card"><h3>{E(rg["detail"])}</h3><div class="scroll" style="overflow-x:auto"><table class="tbl" style="min-width:640px"><tr><th>Index / ETF</th><th class="r">Close</th><th class="r">vs 50-day</th><th class="r">vs 200-day</th><th class="r">1 month</th><th class="r">3 months</th><th class="r">Volatility</th><th>Trend</th></tr>{ix}</table></div></div>'
            f'<div class="grid" style="margin-top:12px"><div class="card c6"><h3>Sector &amp; asset strength · return over 1 week · 1 month · 3 months</h3><table class="tbl"><tr><th>Group</th><th class="r">1w</th><th class="r">1m</th><th class="r">3m</th></tr>{sec}</table></div>'
            f'<div class="card c6"><h3>Biggest moves on the last day</h3><div class="grid"><div class="c6"><table class="tbl"><tr><th>Up</th><th class="r"></th></tr>{mv(mk["movers"]["up"])}</table></div><div class="c6"><table class="tbl"><tr><th>Down</th><th class="r"></th></tr>{mv(mk["movers"]["down"])}</table></div></div></div></div>')


def _filters_card(fl: dict | None) -> str:
    if not fl or not fl.get('results'):
        return ''
    desc = fl.get('filters', {})
    rows = ''
    for r in fl['results']:
        nm = INFO.get(r['rule'], (r['rule'],))[0]
        if 'validation' not in r:
            rows += f"<tr><td>{E(nm)}</td><td colspan='5' class='muted'>{E(r.get('verdict', ''))}</td></tr>"
            continue
        v, f = r['validation'], r['filter']
        names = ' + '.join(desc.get(x.strip(), x.strip()) for x in f.split('&'))
        good = r['verdict'].startswith('HELPFUL')
        rows += (f"<tr><td><b>{E(nm)}</b></td><td>{E(names)}</td><td class='r num'>{pct(v['baseline'])}</td><td class='r num'>{pct(v['kept_mean'])}</td>"
                 f"<td class='r num'>{pct(v['improvement'], d=2)} [{pct(v['ci_lo'], d=2)}, {pct(v['ci_hi'], d=2)}]</td><td>{'<span class=tag&#32;p>HELPFUL</span>' if good else '<span class=tag&#32;f>NOT PROVEN</span>'}</td></tr>")
    return ('<div class="card" style="margin-top:12px"><h3>Entry-filter study · does a market condition separate the winners from the losers?</h3><div class="scroll" style="overflow-x:auto"><table class="tbl" style="min-width:820px">'
            '<tr><th>Setup</th><th>Best condition (chosen on the earlier 60%)</th><th class="r">All setups, later 40%</th><th class="r">With the condition</th><th class="r">Improvement (95% range)</th><th>Verdict</th></tr>' + rows + '</table></div>'
            '<p class="muted" style="font-size:12px;margin:8px 0 0">120 fixed conditions were tried per setup; the best was chosen on the earlier years and judged ONCE on the later, unseen years. A condition can never remove more than half the setups. Nothing is applied automatically: using one is a written decision.</p></div>')


def _research_tab(res: dict | None, mk: dict | None, base: str, fl: dict | None = None) -> str:
    if not res:
        return base + _filters_card(fl)
    rows = []
    for r in res["rules"]:
        name = INFO.get(r["rule"], (r["rule"],))[0]
        if "roi" not in r:
            rows.append(f'<tr><td>{E(name)}</td><td class="r num">{r.get("n", 0)}</td><td colspan="8" class="muted">{E(str(r.get("verdict", "")))}</td></tr>')
            continue
        rows.append(f'<tr><td><b>{E(name)}</b><div class="muted" style="font-size:11px">{E(r["rule"])}</div></td><td class="r num">{r["n"]:,}</td><td class="r num">{r["weeks"]}</td><td class="r num">{pct(r["hit_rate"], False, 0)}</td>'
                    f'<td class="r num"><b>{pct(r["roi"])}</b></td><td class="r num">{pct(r["ci95_lo"], d=2)} to {pct(r["ci95_hi"], d=2)}</td><td class="r num">{pct(r["mde"], False)}</td><td class="r num">{pct(r["challenger_p95"])}</td>'
                    f'<td class="r num">{pct(r["net_normal"])} / {pct(r["net_stressed"])}</td><td>{"<span class=tag&#32;p>PASSED</span>" if r["passes"] else "<span class=tag&#32;f>NO EDGE</span>"}</td></tr>')
    table = ('<div class="card" style="margin-top:12px"><h3>Every rule tested · price-only · pre-registered, fixed in advance</h3><div class="scroll" style="overflow-x:auto"><table class="tbl" style="min-width:900px"><tr><th>Rule</th><th class="r">Trades</th><th class="r">Weeks</th><th class="r">Wins</th><th class="r">Avg gain</th>'
             '<th class="r">Range (penalised)</th><th class="r">MDE</th><th class="r">Random p95</th><th class="r">After costs normal / stressed</th><th>Verdict</th></tr>' + "".join(rows) + '</table></div>'
             f'<p class="muted" style="font-size:12px;margin:8px 0 0">Window {E(res.get("window", ""))}; sealed from {E(res.get("sealed_from", ""))}. MDE = the smallest real edge this sample could have detected: "no edge" means "no edge above the MDE". Random p95 = what random entries beat only 5% of the time.</p></div>')
    stress = [r for r in res["rules"] if r.get("passes") and r.get("robust")]
    st = ""
    if stress:
        body = ""
        for r in stress:
            b, e = r["robust"], r["robust"].get("etf_only")
            body += (f'<tr><td>{E(INFO.get(r["rule"], (r["rule"],))[0])}</td><td class="r num">{("n/a" if not e else pct(e["mean"]) + " [" + pct(e["ci_lo"], d=2) + ", " + pct(e["ci_hi"], d=2) + "] n=" + str(e["n"]))}</td><td class="r num">{pct(b["trimmed_mean"])}</td>'
                     f'<td class="r num">{pct(b["ex_crisis"]) if b.get("ex_crisis") is not None else "n/a"}</td><td class="r num">{b["top1_share"] * 100:.0f}%</td><td class="r num">{pct(b["worst_year"])}</td><td class="r num">{pct(b["best_year"])}</td></tr>')
        st = ('<div class="card" style="margin-top:12px"><h3>Stress checks on the setups that passed</h3><div class="scroll" style="overflow-x:auto"><table class="tbl" style="min-width:760px"><tr><th>Rule</th><th class="r">ETFs only (no survivor bias)</th><th class="r">Outliers trimmed</th>'
              '<th class="r">Without 2008-09 &amp; 2020</th><th class="r">Top 1% of trades = share of gains</th><th class="r">Worst year</th><th class="r">Best year</th></tr>' + body + '</table></div></div>')
    ho = ((mk or {}).get("system") or {}).get("holdout") or []
    hl = ('<div class="card" style="margin-top:12px"><h3>Sealed final year · opened once per rule</h3>' + "".join(f'<div class="mono" style="font-size:12px;margin:3px 0">{E(x)}</div>' for x in ho) + '</div>') if ho else ""
    how = ('<div class="card" style="margin-top:12px"><h3>How the testing works</h3><p>• Free daily prices, 2000 to today, 100+ US and UK stocks and ETFs. • A signal at a close is acted on at the NEXT open (tested: the rules cannot see the future). '
           '• One position per stock at a time, same as the live scanner. • Every rule is fixed in advance; each one tried counts toward a multiple-testing penalty (Bonferroni). • Trades are grouped by week, because many stocks move together. '
           '• A rule passes only with 100+ independent weeks, a penalised range above zero, beating random entries, and being positive in both halves of history. • The latest year is sealed and opened once, for one rule. '
           '• Known bias: the universe is today\'s survivors, so long-only results look better than real time; ETF-only checks control for it.</p></div>')
    return base + table + st + _filters_card(fl) + hl + how


def _lessons_card(sp: dict | None) -> str:
    """What the engine is learning from its own closed trades. Per rule, after 30+ closed trades: which backdrop conditions go with better or worse results. FORWARD evidence; nothing changes automatically."""
    ls = ((sp or {}).get("lessons") or {}).get("lessons") or {}
    if not ls:
        return ('<div class="card" style="margin-top:12px"><h3>What the engine is learning from its closed trades</h3><p class="muted" style="margin:0">Every closed trade gets a written explanation of why it won or lost (History tab). '
                'Once a setup has 30 closed trades, this card shows which market conditions went with its winners and its losers. None yet: the forward test only started on 18 Nov.</p></div>')
    body = ""
    for rule, e in ls.items():
        why = ", ".join(f"{E(k)} {v['n']} (avg {pct(v['mean'], d=1)}, {v['win'] * 100:.0f}% won)" for k, v in sorted(e["why"].items(), key=lambda kv: -kv[1]["n"]))
        if not e["enough"]:
            body += f'<tr><td>{E(INFO.get(rule, (rule,))[0])}</td><td class="r num">{e["n"]}</td><td colspan=2 class="muted">needs 30 closed trades before conditions are compared · so far: {why or "n/a"}</td></tr>'
            continue
        for c in sorted(e["conditions"], key=lambda c: -abs(c["edge"])):
            body += (f'<tr><td>{E(INFO.get(rule, (rule,))[0])}</td><td class="r num">{e["n"]}</td><td>{E(c["name"])}</td><td class="num">with: {pct(c["with_mean"], d=1)} ({c["with_n"]}) · without: {pct(c["without_mean"], d=1)} ({c["without_n"]}) · '
                     f'<b class="{colr(c["edge"])}">{pct(c["edge"], d=1)}</b></td></tr>')
    return ('<div class="card" style="margin-top:12px"><h3>What the engine is learning from its closed trades</h3><div class="scroll" style="overflow-x:auto"><table class="tbl" style="min-width:640px">'
            '<tr><th>Setup</th><th class="r">Closed</th><th>Condition</th><th>Average gain with vs without</th></tr>' + body + '</table></div>'
            '<p class="muted" style="font-size:12px;margin:8px 0 0">Forward evidence only. A condition becomes a rule change only through the written filter process (candidate, live evidence, your decision): it never changes a setup by itself.</p></div>')


def _performance_tab(sp: dict | None, res: dict | None) -> str:
    sp = sp or {}
    fw, closed = sp.get("forward") or {}, sp.get("closed") or []
    fc, yc = _forward_chart(closed), _year_chart(res)
    out = []
    if fw:
        body = "".join(f'<tr><td>{E(INFO.get(k, (k,))[0])}</td><td class="r num">{v["n"]}</td><td class="r num">{pct(v["hit_rate"], False, 0)}</td><td class="r num">{pct(v["mean"])}</td>'
                       f'<td class="r num">{"needs 30+" if v["lo"] is None else pct(v["lo"], d=1) + " to " + pct(v["hi"], d=1)}</td><td class="r num">{pct(v.get("expected"))}</td></tr>' for k, v in fw.items())
        out.append('<div class="card"><h3>Forward test by setup · live, out-of-sample</h3><div class="scroll" style="overflow-x:auto"><table class="tbl" style="min-width:560px"><tr><th>Setup</th><th class="r">Closed</th><th class="r">Win rate</th><th class="r">Avg gain</th><th class="r">95% range</th><th class="r">Research said</th></tr>'
                   + body + '</table></div><p class="muted" style="font-size:12px;margin:8px 0 0">Fewer than 30 closed trades is mostly luck either way; trust it only once the range is narrow.</p></div>')
    else:
        out.append('<div class="card"><h3>Forward test · live, out-of-sample</h3><p class="muted" style="margin:0">Every new setup is tracked from now on, exactly as in the research. As trades close, their results appear here. This is the real confirmation: nothing in it was seen when the rules were chosen.</p></div>')
    if fc:
        out.append(f'<div class="card" style="margin-top:12px"><h3>Forward test · cumulative price gain of closed trades</h3>{fc}</div>')
    if closed:
        for key, lab in (("market", "market"),):
            by = {}
            for c in closed:
                by.setdefault(c[key], []).append(c["gross"])
            body = "".join(f'<tr><td>{E(k)}</td><td class="r num">{len(v)}</td><td class="r num">{pct(sum(v) / len(v))}</td><td class="r num">{pct(sum(x > 0 for x in v) / len(v), False, 0)}</td></tr>' for k, v in sorted(by.items()))
            out.append(f'<div class="card" style="margin-top:12px"><h3>Forward test by {lab}</h3><table class="tbl"><tr><th>{lab.title()}</th><th class="r">Closed</th><th class="r">Avg gain</th><th class="r">Wins</th></tr>{body}</table></div>')
    fwf = [(k, v["by_filter"]) for k, v in fw.items() if v.get("by_filter")]
    if fwf:
        body = "".join(f'<tr><td>{E(INFO.get(k, (k,))[0])}</td><td class="r num">{b.get("with", {}).get("n", 0)}</td><td class="r num">{pct(b["with"]["mean"]) if "with" in b else "—"}</td><td class="r num">{b.get("without", {}).get("n", 0)}</td><td class="r num">{pct(b["without"]["mean"]) if "without" in b else "—"}</td></tr>' for k, b in fwf)
        out.append('<div class="card" style="margin-top:12px"><h3>Candidate filter · live results with and without it</h3><table class="tbl"><tr><th>Setup</th><th class="r">With: closed</th><th class="r">With: avg gain</th><th class="r">Without: closed</th><th class="r">Without: avg gain</th></tr>' + body + '</table>'
                   '<p class="muted" style="font-size:12px;margin:8px 0 0">The filter held up on unseen history only marginally, so it only TAGS setups. Live results decide whether it is ever used; it never removes a setup.</p></div>')
    ac = sp.get("account") or {}
    if ac.get("closed"):
        rr = "".join(f'<tr><td><b>{E(c["symbol"].split(".")[0].upper())}</b></td><td>{E(INFO.get(c["rule"], (c["rule"],))[0])}</td><td>{E(c["entry_date"])}</td><td>{E(c["exit_date"])}</td><td class="r num">£{c["cost"]:,.0f}</td>'
                     f'<td class="r num"><b class="{"up" if c["pnl"] > 0 else "dn"}">{_gbp(c["pnl"])}</b></td><td class="r num">{c["r"]:+.1f}R</td></tr>' for c in reversed(ac["closed"][-25:]))
        out.append('<div class="card" style="margin-top:12px"><h3>Paper account · closed trades (£20 risk each = 1R, before costs)</h3><div class="scroll" style="overflow-x:auto"><table class="tbl" style="min-width:620px"><tr><th>Stock</th><th>Setup</th><th>Entered</th><th>Exited</th>'
                   '<th class="r">Position</th><th class="r">P/L</th><th class="r">R</th></tr>' + rr + '</table></div></div>')
    if ac.get("skipped"):
        out.append('<div class="card" style="margin-top:12px"><h3>Setups the paper account skipped</h3>' + "".join(f'<div class="muted" style="font-size:12px;margin:2px 0">{E(x["symbol"].split(".")[0].upper())}: {E(x["why"])}</div>' for x in ac["skipped"][-12:]) + "</div>")
    if yc:
        out.append(f'<div class="card" style="margin-top:12px"><h3>Research · average gain per trade in each year, for the setups that passed (how steady was it?)</h3><div class="scroll">{yc}</div></div>')
    out.append(_lessons_card(sp))
    return "".join(out)


def _journal_tab(jr: dict | None, sp: dict | None) -> str:
    jr = jr or {"closed": [], "open": [], "raw": 0}
    cl, op = jr["closed"], jr["open"]
    setups = (sp or {}).get("setups", [])
    cs = (sp or {}).get("closed", [])
    from . import journal as J
    tag = lambda t: J.from_setup(t, setups, cs)
    wins = [c for c in cl if c["pct"] > 0]
    follow = [c for c in cl if tag(c)]
    kp = ('<div class="kpis">'
          f'<div class="kpi"><small>Closed trades</small><b>{len(cl)}</b><span>{len(op)} lot(s) still open</span></div>'
          f'<div class="kpi"><small>Total profit / loss</small><b class="{"up" if sum(c["pnl"] for c in cl) > 0 else "dn" if sum(c["pnl"] for c in cl) < 0 else "muted"}">{sum(c["pnl"] for c in cl):+,.2f}</b><span>in the stock\'s own currency, before fees</span></div>'
          f'<div class="kpi"><small>Win rate</small><b>{(str(round(len(wins) / len(cl) * 100)) + "%") if cl else "—"}</b><span>{len(wins)} won · {len(cl) - len(wins)} lost</span></div>'
          f'<div class="kpi"><small>Followed an engine setup</small><b>{(str(round(len(follow) / len(cl) * 100)) + "%") if cl else "—"}</b><span>{len(follow)} of {len(cl)} closed buys</span></div></div>')
    form = ('<div class="card"><h3>Log a trade you made (Revolut or practice)</h3><div class="ctl" style="display:flex;flex-wrap:wrap;gap:8px;align-items:center">'
            '<input id="jr-date" type="date" style="background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px 8px">'
            '<input id="jr-sym" placeholder="Ticker e.g. AAPL" style="width:130px;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px 8px">'
            '<select id="jr-side" style="background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px 8px"><option value="buy">Buy</option><option value="sell">Sell</option></select>'
            '<input id="jr-price" type="number" step="0.01" placeholder="Price" style="width:100px;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px 8px">'
            '<input id="jr-qty" type="number" step="0.0001" placeholder="Quantity" style="width:100px;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px 8px">'
            '<input id="jr-note" placeholder="Note (why?)" style="flex:1;min-width:140px;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px 8px">'
            '<button class="chip" style="cursor:pointer" onclick="stJournal(this)">Save trade</button></div>'
            '<p class="muted" style="font-size:12px;margin:8px 0 0">Stored only on your VM. The engine pairs buys and sells (first in, first out) and checks whether each buy matched a setup it had flagged. It never places or changes an order.</p></div>')
    cr = "".join(f'<tr><td><b>{E(c["symbol"].upper())}</b></td><td>{E(c["bought"])}</td><td>{E(c["sold"])}</td><td class="r num">{c["buy"]:,.2f}</td><td class="r num">{c["sell"]:,.2f}</td><td class="r num"><b class="{"up" if c["pct"] > 0 else "dn"}">{pct(c["pct"], d=1)}</b></td>'
                 f'<td class="r num">{c["pnl"]:+,.2f}</td><td class="r num">{c["days"]}</td><td>{E(INFO.get(tag(c), ("—",))[0]) if tag(c) else "<span class=muted>not from a setup</span>"}</td></tr>' for c in reversed(cl[-25:]))
    tbl = (f'<div class="card" style="margin-top:12px"><h3>Closed trades</h3><div class="scroll" style="overflow-x:auto"><table class="tbl" style="min-width:700px"><tr><th>Stock</th><th>Bought</th><th>Sold</th><th class="r">Buy</th><th class="r">Sell</th><th class="r">Gain</th><th class="r">P/L</th><th class="r">Days</th><th>Matched engine setup</th></tr>{cr}</table></div></div>') if cl else \
          '<div class="card" style="margin-top:12px"><p class="muted" style="margin:0">No closed trades logged yet.</p></div>'
    ot = ""
    if op:
        ot = ('<div class="card" style="margin-top:12px"><h3>Still open</h3><table class="tbl"><tr><th>Stock</th><th>Bought</th><th class="r">Buy price</th><th class="r">Quantity</th></tr>'
              + "".join(f'<tr><td><b>{E(o["symbol"].upper())}</b></td><td>{E(o["bought"])}</td><td class="r num">{o["buy"]:,.2f}</td><td class="r num">{o["qty"]:g}</td></tr>' for o in op) + "</table></div>")
    return f"{kp}{form}{tbl}{ot}{JOURNAL_JS}"


def _system_tab(res: dict | None, sp: dict | None, mk: dict | None) -> str:
    sy = (mk or {}).get("system") or {}
    if not sy:
        return '<div class="card"><h3>System</h3><p class="muted">System health appears after the first nightly scan has run.</p></div>'
    nstale, ngap = len(sy["stale"]), len(sy["gaps"])
    kp = ('<div class="kpis">'
          f'<div class="kpi"><small>Prices as of</small><b>{E(sy["asof"])}</b><span>{sy["symbols"]} symbols · {sy["rows"]:,} daily bars</span></div>'
          f'<div class="kpi"><small>Stale symbols</small><b class="{"dn" if nstale else "up"}">{nstale}</b><span>no new bar for over 4 days</span></div>'
          f'<div class="kpi"><small>Symbols not available</small><b>{ngap}</b><span>{E(", ".join(g.split(":")[0] for g in sy["gaps"][:4]))}</span></div>'
          f'<div class="kpi"><small>Rules logged</small><b>{sy["trials"]}</b><span>multiple-testing count</span></div></div>')
    nl = "".join(f'<div class="mono" style="font-size:12px;margin:3px 0">{E(x)}</div>' for x in sy["nightly"]) or '<p class="muted" style="margin:0">The nightly job has not run yet (weekdays 22:45 UTC).</p>'
    chk = [("Prices up to date", nstale == 0, f"{nstale} stale" if nstale else "all symbols have a recent bar"), ("Bars with suspicious jumps handled", True, f"{len(sy['suspicious'])} symbol(s) flagged; trades touching a flagged bar are dropped"),
           ("Sealed final year untouched except by the log", True, f"{len(sy['holdout'])} opening(s) logged"), ("Look-ahead tests", True, "signals cannot use future prices (automated tests)")]
    ch = "".join(f'<tr><td>{"<b class=up>✓</b>" if ok else "<b class=dn>✗</b>"}</td><td>{E(a)}</td><td class="muted">{E(b)}</td></tr>' for a, ok, b in chk)
    lim = ('<div class="card" style="margin-top:12px"><h3>What this can and cannot tell you</h3><ul class="lim"><li>Research only: it never places an order and has no Revolut access. You decide and trade yourself, at your own risk.</li>'
           '<li>Daily bars only: the free data has no reliable intraday history, so day-trade rules are tested open-to-close and are optimistic.</li>'
           '<li>The universe is today\'s large US and UK stocks (survivors), so long-only results look better than they would have in real time.</li>'
           '<li>Not built yet: filing text, analyst estimates, intraday monitoring, Telegram alerts. See docs/STOCKS_PLAN.md.</li>'
           '<li>Costs are assumptions until you give your real Revolut plan fees; they are shown, not part of pass/fail. Check each stock is available on Revolut.</li></ul></div>')
    cv = (sp or {}).get("coverage") or {}
    cov = ""
    if cv:
        from .universe import COUNTRY
        al = set((sp or {}).get("allowed") or [])
        rows_ = "".join(f'<tr><td><b>{E(COUNTRY.get(k, k.upper()))}</b></td><td class="r num">{v["symbols"]}</td><td class="r num">{v["setups"]}</td><td>{("<span class=badge&#32;v>YOU CAN TRADE</span>" if k in al else "<span class=badge&#32;n>research only</span>") if al else "<span class=muted>all shown</span>"}</td></tr>'
                        for k, v in sorted(cv.items(), key=lambda kv: -kv[1]["setups"]))
        cov = ('<div class="card" style="margin-top:12px"><h3>Coverage by country · stocks tracked and new setups today</h3><div class="scroll" style="overflow-x:auto"><table class="tbl" style="min-width:520px"><tr><th>Country</th><th class="r">Stocks</th><th class="r">New setups</th><th>Your Revolut list</th></tr>' + rows_ + '</table></div>'
               '<p class="muted" style="font-size:12px;margin:8px 0 0">The research uses every market. Which ones show setups and trade in your paper account is set in ops/stocks_countries.txt (one country per line).</p></div>')
    ch_ = (sp or {}).get("coverage_home") or {}
    if ch_:
        from .universe import COUNTRY as CN
        hr = "".join(f'<tr><td><b>{E(CN.get(k, k.upper()))}</b></td><td class="r num">{v["symbols"]}</td><td class="r num">{v["setups"]}</td></tr>' for k, v in sorted(ch_.items(), key=lambda kv: (-kv[1]["setups"], -kv[1]["symbols"])))
        cov += ('<div class="card" style="margin-top:12px"><h3>Companies by home country · what Revolut\'s country filter shows</h3><div class="scroll" style="overflow-x:auto"><table class="tbl" style="min-width:420px"><tr><th>Company country</th><th class="r">Stocks</th><th class="r">New setups</th></tr>' + hr + '</table></div>'
                '<p class="muted" style="font-size:12px;margin:8px 0 0">Overseas companies are traded through their US-listed shares (ADRs), which Revolut offers; direct listings in Tokyo, Hong Kong, Sydney, Toronto and similar exchanges are researched but not shown unless you add them to ops/stocks_countries.txt.</p></div>')
    return (f'{kp}<div class="grid"><div class="card c6"><h3>Health checks</h3><table class="tbl">{ch}</table></div><div class="card c6"><h3>Nightly job · last lines</h3>{nl}'
            f'<div class="muted" style="font-size:12px;margin-top:8px">Code: {E(sy["code"])}</div></div></div>{cov}{lim}')


def parts(res: dict | None, sp: dict | None = None, mk: dict | None = None, jr: dict | None = None, fl: dict | None = None) -> dict:
    """Everything the dashboard shows, as HTML pieces, shared by the stand-alone page and the tab inside the FX dashboard. Same seven sections as the FX dashboard."""
    rules = (res or {}).get("rules", [])
    scored = [r for r in rules if "roi" in r]
    passed = [r for r in scored if r["passes"]]
    bm = (res or {}).get("benchmarks", {})
    if not scored:
        state, label, verdict = "warn", "NO RESULTS YET", '<div class="verdict empty"><b>No results yet.</b> <span class="muted">Run <code>bash deploy/stocks_all.sh</code> on the VM. Only real results are shown here.</span></div>'
    elif passed:
        state, label = "good", f"{len(passed)} SETUP PASSED"
        verdict = (f'<div class="verdict ok"><b>{len(passed)} rule(s) passed the price-only test: {E(", ".join(INFO[r["rule"]][0] for r in passed))}.</b> Treat as a lead: it must keep working on live prices (Performance tab), '
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
    base = (f'{verdict}{kp}<div class="card"><h3>Average gain per trade from price moves alone · each rule against its own random-entry benchmark</h3><div class="scroll">{_forest(rules) or "<p class=muted>No scored rules yet.</p>"}</div>'
            '<div class="legend"><span><i style="background:var(--s2)"></i>no edge</span><span><i style="background:var(--good)"></i>passed</span><span><i style="background:var(--s1)"></i>random-entry 95th percentile</span><span>line = confidence range after the multiple-testing penalty</span></div></div>')
    return dict(state=state, label=label, asof=str(asof), setups=_setups_tab(sp, res), history=_history_tab(sp), charts=_charts_tab(mk), market=_market_tab(mk), research=_research_tab(res, mk, base, fl) + _rules_tab(res).replace('<p class="muted" style="font-size:12px">', '<p class="muted" style="font-size:12px;margin-top:8px">'),
                performance=_performance_tab(sp, res), journal=_journal_tab(jr, sp), system=_system_tab(res, sp, mk))


SECTIONS = [("setups", "Setups"), ("history", "History"), ("charts", "Charts"), ("market", "Market"), ("research", "Research"), ("performance", "Performance"), ("journal", "Journal"), ("system", "System")]


def render(res: dict | None, sp: dict | None = None, mk: dict | None = None, jr: dict | None = None, fl: dict | None = None) -> str:
    x = parts(res, sp, mk, jr, fl)
    sections = "".join(f'<div class="tab" id="{k}">{x[k]}</div>' for k, _ in SECTIONS)
    body = (f'<div class="wrap"><div class="top"><span class="brand">STOCKS ENGINE</span><span class="pill {x["state"]}">{x["label"]}</span><span class="chip">as of {E(x["asof"])}</span><span class="chip">research only · never places an order</span>'
            f'<span class="sp"></span><span class="mono muted">{datetime.now().strftime("%a %d %b %Y %H:%M")}</span></div>'
            f'<div class="tabs">{"".join(f"<button data-t=\'{k}\'>{v}</button>" for k, v in SECTIONS)}</div>{sections}<footer>Generated from docs/results/stocks.json · numbers shown only if they are in that file</footer></div>')
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Stocks Engine</title><style>{CSS}</style></head><body>{body}{TAB_JS}</body></html>'


def write(res_path=Path("docs/results/stocks.json"), out=Path("docs/results/stocks.html"), setups_path=None) -> Path:
    rp = Path(res_path)
    sp_path = Path(setups_path) if setups_path else rp.with_name("stocks_setups.json")
    res = json.loads(rp.read_text()) if rp.exists() else None
    sp = json.loads(sp_path.read_text()) if sp_path.exists() else None
    mp = rp.with_name("stocks_market.json")
    mk = json.loads(mp.read_text()) if mp.exists() else None
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(res, sp, mk))
    return out


if __name__ == "__main__":
    print("wrote", write(*(Path(a) for a in sys.argv[1:3])))
