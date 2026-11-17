"""Institutional-style static dashboard: ONE self-contained HTML file (inline SVG, no external calls, no tracking).
Private by construction: it lives on your machine; nothing is uploaded.
PYTHONPATH=src python -m fxengine.dashboard.build   ->  dashboard/index.html   (open it in a browser)"""
from __future__ import annotations
import html as H, json
from pathlib import Path
import numpy as np
import pandas as pd
from ..calendar import market_closed
from ..data import store
from ..engine.costs import pip
from ..research import stats
from . import journal as J

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"]
TOK = {"S1": "#3987e5", "S2": "#d95926", "GOOD": "#0ca30c", "WARN": "#fab219", "CRIT": "#d03b3b"}


def e(s):
    return H.escape(str(s))


def px(sym, v):
    return f"{float(v):.3f}" if sym.endswith('JPY') else f"{float(v):.5f}"


# ---------- data ----------
STALE_MIN = 12.0     # same threshold as the live loop (live/loop.py)


def health(root, now):
    """Age of the OLDEST pair's last closed M5 candle (same rule as the live loop); market hours in New York time."""
    ages = []
    for s in PAIRS:
        m5 = store.load(s, "M5", root, tail=3)
        if len(m5):
            ages.append((now - (m5.index[-1] + pd.Timedelta(minutes=5))).total_seconds() / 60)
    age = max(ages) if ages else None
    closed = market_closed(now)
    if age is None:
        return "crit", "NO DATA", age, closed
    if closed:
        return "warn", "MARKET CLOSED", age, closed
    return ("good", "DATA FRESH", age, closed) if age <= STALE_MIN else ("crit", "DATA STALE", age, closed)


def strength(root):
    fr = {s: store.load(s, "H4", root, tail=150) for s in PAIRS}
    fr = {k: v for k, v in fr.items() if len(v)}
    if not fr:
        return None
    close = pd.DataFrame({k: v.bid_c for k, v in fr.items()}).sort_index()
    ret = np.log(close).diff(30)
    ccy = {}
    for s in close.columns:
        ccy.setdefault(s[:3], []).append(ret[s]); ccy.setdefault(s[3:], []).append(-ret[s])
    return (pd.DataFrame({c: pd.concat(v, axis=1).mean(axis=1) for c, v in ccy.items()}).dropna().tail(24) * 100)


def vol_by_hour(root):
    ds = []
    for s in PAIRS[:6]:
        d = store.load(s, "H1", root, tail=24 * 60)
        if len(d):
            ds.append(((d.bid_h - d.bid_l) / pip(s)).groupby(d.index.hour).mean())
    if not ds:
        return None
    df = pd.concat(ds, axis=1)
    return (df / df.mean()).mean(axis=1).reindex(range(24)).fillna(1.0)


def research():
    files = sorted(Path("data").glob("phase3_v1_*setups.parquet"))
    out = {}
    for f in files:
        name = f.stem.replace("phase3_v1_", "").replace("_setups", "")
        name = name if name in ("H1", "M15") else "M15"
        out[name] = pd.read_parquet(f)
    return out


# ---------- svg helpers ----------
def scale(vals, lo, hi, a, b):
    return [a + (v - lo) / ((hi - lo) or 1) * (b - a) for v in vals]


def mini_chart(c, root):
    d = store.load(c["pair"], c["tf"], root, tail=48)
    px = list(d.bid_c) or [c["entry"]]
    lo = min(px + [c["stop"], c["target"]]); hi = max(px + [c["stop"], c["target"]])
    pad = (hi - lo) * .08
    lo, hi = lo - pad, hi + pad
    W, Hh = 220, 96
    y = lambda v: Hh - (v - lo) / ((hi - lo) or 1) * Hh
    pts = " ".join(f"{i * W / max(len(px) - 1, 1):.1f},{y(v):.1f}" for i, v in enumerate(px))
    ye, ys, yt = y(c["entry"]), y(c["stop"]), y(c["target"])
    return (f"<svg viewBox='0 0 {W} {Hh}' class='mini' preserveAspectRatio='none' role='img' aria-label='price with entry, stop and target'>"
            f"<rect x='0' y='{min(ye, ys):.1f}' width='{W}' height='{abs(ys - ye):.1f}' fill='{TOK['CRIT']}' opacity='.14'/>"
            f"<rect x='0' y='{min(ye, yt):.1f}' width='{W}' height='{abs(yt - ye):.1f}' fill='{TOK['GOOD']}' opacity='.14'/>"
            f"<line x1='0' x2='{W}' y1='{ye:.1f}' y2='{ye:.1f}' stroke='var(--s1)' stroke-dasharray='4 3' vector-effect='non-scaling-stroke'/>"
            f"<line x1='0' x2='{W}' y1='{ys:.1f}' y2='{ys:.1f}' stroke='{TOK['CRIT']}' vector-effect='non-scaling-stroke'/>"
            f"<line x1='0' x2='{W}' y1='{yt:.1f}' y2='{yt:.1f}' stroke='{TOK['GOOD']}' vector-effect='non-scaling-stroke'/>"
            f"<polyline points='{pts}' fill='none' stroke='var(--ink)' stroke-width='1.6' stroke-linejoin='round' vector-effect='non-scaling-stroke'/></svg>")


def sparkline(vals, color):
    if len(vals) < 2:
        return ""
    ys = scale(vals, min(vals), max(vals), 22, 2)
    pts = " ".join(f"{i * 100 / (len(vals) - 1):.1f},{y:.1f}" for i, y in enumerate(ys))
    return f"<svg viewBox='0 0 100 24' class='spark' preserveAspectRatio='none'><polyline points='{pts}' fill='none' stroke='{color}' stroke-width='1.6'/></svg>"


def line_chart(series, ylabel, pre="", suf="R", base=0.0):
    """series: list of (name, color_var, pd.Series indexed by time). Crosshair tooltip via inline JS."""
    W, Hh, L, B, R = 560, 220, 44, 22, 84
    allv = np.concatenate([s.values for _, _, s in series])
    lo, hi = min(allv.min(), base), max(allv.max(), base)
    pad = (hi - lo) * .06 or 1
    lo, hi = lo - pad, hi + pad
    t0 = min(s.index[0] for _, _, s in series); t1 = max(s.index[-1] for _, _, s in series)
    span = (t1 - t0).total_seconds() or 1
    x = lambda t: L + (t - t0).total_seconds() / span * (W - L - R)
    y = lambda v: 8 + (hi - v) / (hi - lo) * (Hh - B - 8)
    g, data = "", []
    raw = (hi - lo) / 4
    mag = 10 ** np.floor(np.log10(raw or 1))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    v = np.ceil(lo / step) * step
    while v <= hi:
        g += f"<line x1='{L}' x2='{W - R + 6}' y1='{y(v):.1f}' y2='{y(v):.1f}' class='grid'/><text x='{L - 6}' y='{y(v) + 3:.1f}' class='ax' text-anchor='end'>{pre}{v:,.0f}</text>"
        v += step
    g += f"<line x1='{L}' x2='{W - R + 6}' y1='{y(base):.1f}' y2='{y(base):.1f}' class='zero'/>"
    for k in range(4):
        t = t0 + (t1 - t0) * k / 3
        g += f"<text x='{x(t):.1f}' y='{Hh - 6}' class='ax' text-anchor='middle'>{t:%b %y}</text>"
    lines = ""
    for name, col, s in series:
        idx = np.linspace(0, len(s) - 1, min(len(s), 140)).astype(int)
        ss = s.iloc[idx]
        pts = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in ss.items())
        lines += f"<polyline points='{pts}' fill='none' stroke='var({col})' stroke-width='2' stroke-linejoin='round'/>"
        lines += f"<text x='{x(ss.index[-1]) + 6:.1f}' y='{y(ss.iloc[-1]) + 4:.1f}' class='lbl'>{e(name)} {pre}{ss.iloc[-1]:,.0f}{suf}</text>"
        data.append(dict(n=name, c=col, t=[f"{t:%d %b %Y}" for t in ss.index], v=[round(float(v), 1) for v in ss.values], x=[round(x(t), 1) for t in ss.index]))
    legend = "".join(f"<span><i style='background:var({c})'></i>{e(n)}</span>" for n, c, _ in series)
    return (f"<div class='lc' data-pre='{pre}' data-suf='{suf}' data-j='{e(json.dumps(data))}'><div class='legend'>{legend}</div>"
            f"<svg viewBox='0 0 {W} {Hh}' class='chart'>{g}{lines}<line class='cross' y1='8' y2='{Hh - B}' x1='0' x2='0'/></svg><div class='tip'></div></div>")


def diverge(v, m):
    """blue(+) <-> gray <-> red(-) diverging cell colour."""
    t = max(-1, min(1, v / (m or 1)))
    mid, blue, red = (56, 56, 53), (57, 135, 229), (208, 59, 59)
    tgt = blue if t > 0 else red
    a = abs(t) ** .85
    c = [round(mid[i] + (tgt[i] - mid[i]) * a) for i in range(3)]
    return f"rgb({c[0]},{c[1]},{c[2]})"


def heat(st):
    if st is None:
        return "<p class='muted'>No data yet.</p>"
    m = float(np.abs(st.values).max()) or 1
    order = list(st.iloc[-1].sort_values(ascending=False).index)
    rows = ""
    for c in order:
        cells = "".join(f"<td style='background:{diverge(v, m)}' title='{c} {t:%d %b %H:%M}: {v:+.2f}%'></td>" for t, v in st[c].items())
        last = st[c].iloc[-1]
        rows += f"<tr><th>{c}</th>{cells}<td class='num {'up' if last > 0 else 'dn'}'>{last:+.2f}%</td></tr>"
    return f"<table class='heat'>{rows}</table><div class='scale'><span>weakest</span><i></i><span>strongest</span></div>"


def sessions(vol):
    if vol is None:
        return "<p class='muted'>No data yet.</p>"
    W, Hh, top = 560, 190, 62
    bw = (W - 8) / 24
    mx = float(vol.max()) or 1
    bars = ""
    for h in range(24):
        hh = vol[h] / mx * (Hh - top - 24)
        bars += (f"<rect x='{4 + h * bw + 2:.1f}' y='{Hh - 20 - hh:.1f}' width='{bw - 4:.1f}' height='{hh:.1f}' rx='2' fill='var(--s1)' opacity='.85'>"
                 f"<title>{h:02d}:00 UTC, relative range {vol[h]:.2f}</title></rect>")
        if h % 3 == 0:
            bars += f"<text x='{4 + h * bw + bw / 2:.1f}' y='{Hh - 5}' class='ax' text-anchor='middle'>{h:02d}</text>"
    bands = ""
    for row, (name, a, b, col) in enumerate((("TOKYO", 0, 9, TOK["S2"]), ("LONDON", 7, 16, TOK["S1"]), ("NEW YORK", 12, 21, TOK["GOOD"]))):
        y0 = 2 + row * 18
        bands += (f"<rect x='{4 + a * bw:.1f}' y='{y0}' width='{(b - a) * bw:.1f}' height='14' rx='5' fill='{col}' opacity='.95'/>"
                  f"<text x='{4 + a * bw + 8:.1f}' y='{y0 + 10.5}' class='bt'>{name}</text>")
    return f"<svg viewBox='0 0 {W} {Hh}' class='chart'>{bands}{bars}</svg>"


def funnel(df):
    sc = df[df.triggered]
    stages = [("Signals generated", len(df)), ("Triggered (filled)", int(df.triggered.sum())), ("Resolved", len(sc))]
    top = stages[0][1] or 1
    out = ""
    for n, v in stages:
        out += f"<div class='frow'><span>{n}</span><div class='fbar'><b style='width:{v / top * 100:.1f}%'></b></div><em>{v:,}</em></div>"
    ex = sc.reason.value_counts()
    out += "<div class='split'>" + "".join(f"<span>{k.title()} <b>{v:,}</b></span>" for k, v in ex.items()) + "</div>"
    out += f"<small class='muted'>Reconciles: {len(df):,} signals = {int(df.triggered.sum()):,} triggered + {int((~df.triggered).sum()):,} not triggered.</small>"
    return out


def by_type(df):
    sc = df[df.triggered]
    rows = ""
    for t, g in sc.groupby("type"):
        r = g.net_r.values
        lo, hi = stats.bootstrap_ci(r, n=2000)
        m = r.mean()
        pos = lambda v: 50 + max(-0.7, min(0.7, v)) / 0.7 * 46
        rows += (f"<tr><td>{e(t)}</td><td class='num'>{len(r):,}</td><td class='num'>{(r > 0).mean() * 100:.0f}%</td>"
                 f"<td class='num {'up' if m > 0 else 'dn'}'>{m:+.2f}R</td>"
                 f"<td style='width:170px'><svg viewBox='0 0 100 14' class='ci'><line x1='50' x2='50' y1='0' y2='14' class='zero'/>"
                 f"<line x1='{pos(lo):.1f}' x2='{pos(hi):.1f}' y1='7' y2='7' stroke='var(--ink2)' stroke-width='2'/>"
                 f"<circle cx='{pos(m):.1f}' cy='7' r='3.5' fill='{TOK['GOOD'] if m > 0 else TOK['CRIT']}'/></svg></td></tr>")
    return ("<table class='tbl'><tr><th>Setup type</th><th class='r'>Trades</th><th class='r'>Win</th><th class='r'>Net R / trade</th><th>95% range (±0.7R)</th></tr>" + rows + "</table>")


# ---------- extra data ----------
import re, sqlite3

START = 2500.0
RISK = 20.0
STRATS = {
    "asia_breakout": ("Asian-range breakout", "Trade the first close beyond the overnight range during London's first hours. Stop 1.5 ATR, target 2R."),
    "trend_pullback": ("Trend pullback", "In an EMA50>EMA200 trend, buy when price dips to the EMA20 and closes back above it (mirror for shorts)."),
    "range_reversion": ("Range reversion", "In a flat market, fade a close 2 ATR away from the EMA20, aiming back to the average."),
    "E1_strength": ("Currency-strength momentum", "Trade the pair whose two currencies have diverged most over 5 days, in the direction of the momentum."),
    "E2_donchian": ("Donchian trend breakout", "Buy a close above the 55-bar high in an uptrend (mirror for shorts). Wide stop 3 ATR, target 2R."),
    "E4": ("Donchian + trailing exit", "Same entries as the breakout, but let winners run behind a 20-bar trailing stop."),
    "E5": ("Strength momentum + trailing exit", "Same entries as currency-strength momentum, exit by 20-bar trailing stop."),
}
TA = [("EMA 20 / 50 / 200 trend", "trend pullback, breakout", "Tested: no edge after costs"),
      ("ATR (14) stops and targets", "all setups", "Sizing tool, not a signal"),
      ("Donchian 55-bar channel breakout", "breakout, trailing exit", "Tested: no edge"),
      ("Asian-range breakout (session structure)", "Asian breakout", "Tested: no edge"),
      ("Z-score mean reversion", "range reversion", "Tested: no edge"),
      ("Currency-strength momentum (5-day)", "strength momentum", "Tested: no edge"),
      ("Trailing-stop exits (let winners run)", "E4, E5", "Tested: no edge"),
      ("Session / time-of-day filter", "pre-registered filter", "Not run: no strategy was promising enough"),
      ("Market structure / key levels", "-", "NOT tested yet"),
      ("Scheduled-news blackout", "-", "NOT tested yet (needs a free calendar source)"),
      ("RSI / MACD oscillators", "-", "Not tested: overlap with trend and ATR families")]


def parse_batch_md():
    out = {}
    for f in ("docs/results/experiments_summary.md", "docs/results/batch2_summary.md"):
        if not Path(f).exists():
            continue
        for line in open(f):
            m = re.match(r"- (E\d)[^:]*: n=(\d+) exp=([-\d.]+)R penalised-low=([-\w.]+)(?:.*?win=(\d+)%)?", line.strip())
            if m:
                out[m.group(1)] = dict(n=int(m.group(2)), exp=float(m.group(3)), lo=m.group(4), win=m.group(5), fail="FAIL" in line)
    return out


def research_rows(res, n_trials):
    rows = []
    for tf in ("M15", "H1"):
        if tf not in res:
            continue
        sc = res[tf][res[tf].triggered]
        for t, g in sc.groupby("type"):
            r = g.net_r.values
            gb = stats.gate_b(r, 100, n_trials)
            rows.append((STRATS[t][0], tf, len(r), (r > 0).mean() * 100, r.mean(), gb["ci_lo"], gb["pass"]))
    bm = parse_batch_md()
    for key, name, tf in (("E1", "E1_strength", "H4"), ("E2", "E2_donchian", "H4"), ("E4", "E4", "H4"), ("E5", "E5", "H4")):
        if key in bm:
            b = bm[key]
            try:
                lo = float(b["lo"])
            except ValueError:
                lo = float("nan")
            rows.append((STRATS[name][0], tf, b["n"], float(b["win"]) if b["win"] else float("nan"), b["exp"], lo, not b["fail"]))
    return rows


def live_db(path="data/engine.db"):
    if not Path(path).exists():
        return None
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def ops_chips(c, now):
    """Availability = cycles that completed OK / cycles EXPECTED (every 5 minutes while the market is open, since the first recorded
    cycle, last 7 days). A frozen or switched-off server writes no rows, so it now lowers this number. Plus the next scheduled cycle."""
    from ..calendar import market_closed, next_open
    up = "n/a"
    if c is not None:
        since = max(now - pd.Timedelta(days=7), now)
        first = c.execute("SELECT MIN(ts) FROM cycles").fetchone()[0]
        if first:
            since = max(now - pd.Timedelta(days=7), pd.Timestamp(first))
            slots = pd.date_range(since.ceil("5min"), now, freq="5min")
            expected = sum(1 for t in slots if not market_closed(t))
            ok = c.execute("SELECT COUNT(*) FROM cycles WHERE ts>=? AND ok=1 AND status!='CLOSED'", (str(since),)).fetchone()[0]
            if expected:
                up = f"{min(ok, expected) / expected * 100:.1f}% ({min(ok, expected)} of {expected} cycles, 7d)"
    if market_closed(now):
        nxt = f"market opens {next_open(now):%a %H:%M} UTC"
    else:
        n = now.floor("5min") + pd.Timedelta(minutes=5, seconds=20)
        nxt = f"{n:%H:%M} UTC"
    return up, nxt


def live_candidates(c):
    """Setups the live loop has published and not yet resolved, straight from the ledger (never from a scan file)."""
    rows = c.execute("""SELECT s.run_id, s.record, (SELECT to_state FROM events e WHERE e.run_id=s.run_id ORDER BY idx DESC LIMIT 1) AS state
        FROM setups s WHERE s.run_id NOT IN (SELECT run_id FROM outcomes) ORDER BY s.created_at DESC""").fetchall()
    return [json.loads(r["record"]) | {"run_id": r["run_id"], "state": r["state"] or "PENDING"} for r in rows]


def m5_rerun_rows(files=("docs/results/m5_rerun.json", "docs/results/batch3.json")):
    """Rows from the M5-resolution reruns: R0 (the seven original variants) and batch 3 (E6 momentum, E7 carry)."""
    rows = []
    for fn in files:
        f = Path(fn)
        if not f.exists():
            continue
        res = json.load(open(f))
        for v, modes in res["summary"].items():
            for k, m in modes.items():
                if m["scored"]:
                    rows.append((v, k, m["scored"], m["pair_days"], m["win"] * 100, m["exp_r"], m["penalised_lo"], m["mde_r"], m["challenger_p95"], m["challenger_pct"], m["passes"]))
    return rows


def gbp(v: float, signed=True) -> str:
    s = f"£{abs(v):,.0f}"
    return (("+" if v > 0 else "−" if v < 0 else "") + s) if signed else s


def live_pnl(c, root, now):
    """Live (hypothetical) profit and loss from the engine's own ledger. Realised = resolved trades after modelled costs.
    Floating = open triggered trades marked to the latest bid (before commission/swap). Nothing here is typed in."""
    rows = c.execute("SELECT o.reason, o.net_r, o.resolved_at FROM outcomes o").fetchall()
    trades = sorted((pd.Timestamp(r["resolved_at"]), float(r["net_r"]), r["reason"]) for r in rows if r["reason"] in ("TARGET", "STOP", "TIMEOUT"))
    today = now.normalize()
    wk, mo = today - pd.Timedelta(days=today.day_of_week), today.replace(day=1)
    pay = lambda lo: sum(r for t, r, _ in trades if t >= lo) * RISK
    n_pub = c.execute("SELECT COUNT(*) FROM setups").fetchone()[0]
    n_fill = c.execute("SELECT COUNT(DISTINCT run_id) FROM events WHERE to_state='TRIGGERED'").fetchone()[0]
    n_nt = c.execute("SELECT COUNT(*) FROM outcomes WHERE reason IN ('EXPIRED','INVALIDATED')").fetchone()[0]
    opens, float_r, note = [], 0.0, ""
    try:
        from ..live import loop as L
        for s in live_candidates(c):
            if s.get("state") not in ("TRIGGERED", "ADJUSTED"):
                continue
            t, m5 = L.replay(s, root)
            if t.fill is None or not t.active or m5.empty:
                continue
            last = m5.iloc[-1]
            exit_px = last.bid_c if s["direction"] == "long" else (last.ask_c if "ask_c" in m5.columns else last.bid_c)
            fr = (exit_px - t.fill) / t.s.risk if s["direction"] == "long" else (t.fill - exit_px) / t.s.risk
            opens.append((s["pair"], s["direction"], float(fr)))
            float_r += float(fr)
    except Exception as ex:                                   # show that it failed; never hide it as zero
        note = f"floating P&L unavailable ({type(ex).__name__})"
    realised = sum(r for _, r, _ in trades) * RISK
    curve = pd.Series([START + sum(r for _, r, _ in trades[:i + 1]) * RISK for i in range(len(trades))],
                      index=pd.DatetimeIndex([t for t, _, _ in trades], tz="UTC") if trades and trades[0][0].tzinfo is None else pd.DatetimeIndex([t for t, _, _ in trades]))
    return dict(today=pay(today), week=pay(wk), month=pay(mo), total=realised, floating=float_r * RISK, opens=opens, note=note,
                balance=START + realised + float_r * RISK, wins=sum(1 for _, r, _ in trades if r > 0), losses=sum(1 for _, r, _ in trades if r <= 0),
                n_pub=n_pub, n_fill=n_fill, n_nt=n_nt, curve=curve)


def live_panel(lp):
    if lp is None:
        return ("<div class='card c12'><h3>Live profit &amp; loss · hypothetical</h3><p class='muted'>No live ledger on this machine yet. "
                "It appears once the live loop has run.</p></div>")
    cls = lambda v: "up" if v > 0.005 else ("dn" if v < -0.005 else "muted")
    tiles = [("Hypothetical balance", f"£{lp['balance']:,.0f}", f"start £{START:,.0f} · incl. open trades, before costs", cls(lp["balance"] - START)),
             ("Today", gbp(lp["today"]), "realised, closed trades", cls(lp["today"])),
             ("This week", gbp(lp["week"]), "since Monday", cls(lp["week"])),
             ("This month", gbp(lp["month"]), "", cls(lp["month"])),
             ("All time", gbp(lp["total"]), "realised after modelled costs", cls(lp["total"])),
             ("Open now (floating)", gbp(lp["floating"]), f"{len(lp['opens'])} open · before commission/swap", cls(lp["floating"])),
             ("Wins · losses", f"{lp['wins']} · {lp['losses']}", (f"{lp['wins'] / (lp['wins'] + lp['losses']) * 100:.0f}% win rate" if lp["wins"] + lp["losses"] else "no closed trades yet"), "")]
    html = "".join(f"<div class='kpi'><small>{a}</small><b class='{c}'>{b}</b><span>{d}</span></div>" for a, b, d, c in tiles)
    opens = "".join(f"<span class='chip'>{p} {d.upper()} <b class='mono {cls(r)}'>{gbp(r * RISK)}</b></span> " for p, d, r in lp["opens"])
    curve = ""
    if len(lp["curve"]) > 5:
        curve = f"<div style='margin-top:10px'>{line_chart([('Live', '--s1', lp['curve'])], '£', pre='£', suf='', base=START)}</div>"
    foot = (f"Published {lp['n_pub']} · filled {lp['n_fill']} · closed {lp['wins'] + lp['losses']} · expired or invalidated without a trade {lp['n_nt']}. "
            f"Hypothetical: £{RISK:.0f} risk per setup, nothing was traded. {e(lp['note'])}")
    return (f"<div class='card c12'><h3>Live profit &amp; loss · hypothetical, scored by the engine</h3><div class='kpis' style='margin:0 0 8px'>{html}</div>"
            f"<div>{opens}</div><p class='muted' style='margin:6px 0 0'>{foot}</p>{curve}</div>")

def trades_data(c, root, now, closed_n=6):
    """Every active setup plus the last few closed ones, each with everything needed for ONE complete card."""
    from ..live import loop as L
    rows = c.execute("""SELECT s.run_id, s.record, o.reason, o.net_r, o.resolved_at FROM setups s LEFT JOIN outcomes o USING(run_id)
                        ORDER BY s.created_at DESC""").fetchall()
    out, n_closed = [], 0
    for r in rows:
        rec = json.loads(r["record"]); closed = r["reason"] is not None
        if closed:
            n_closed += 1
            if n_closed > closed_n:
                continue
        ev = [dict(ts=x["ts"], to=x["to_state"], d=x["detail"]) for x in c.execute("SELECT ts,to_state,detail FROM events WHERE run_id=? ORDER BY idx", (r["run_id"],))]
        pair, dirn = rec["pair"], rec["direction"]
        fill = fill_ts = None
        price = ask = None
        try:
            t, m5 = L.replay(dict(rec, run_id=r["run_id"]), root)
            fill, fill_ts = t.fill, (None if t.fill_time is None else int(pd.Timestamp(t.fill_time).timestamp()))
        except Exception:
            m5 = store.load(pair, "M5", root, tail=3)
        if len(m5):
            price = float(m5.bid_c.iloc[-1])
            ask = float(m5.ask_c.iloc[-1]) if "ask_c" in m5.columns else price
        risk = abs(rec["entry"] - rec["stop"]) or 1e-9
        reward = abs(rec["target"] - rec["entry"])
        float_r = None
        if fill is not None and not closed and price is not None:
            float_r = (price - fill) / risk if dirn == "long" else (fill - ask) / risk
        state = r["reason"] if closed else ("OPEN" if fill is not None else "PENDING")
        if not closed and any("trail" in x["d"] or "adjusted" in x["d"] for x in ev):
            state = "OPEN"
        p_ = pip(pair)
        out.append(dict(run_id=r["run_id"], pair=pair, dir=dirn, tf=rec["tf"], type=rec["type"], state=state, closed=closed,
                        entry=rec["entry"], entry_kind=rec.get("entry_kind", ""), stop=rec["stop"], target=rec["target"], fill=fill, fill_ts=fill_ts,
                        created=int(pd.Timestamp(rec["created"]).timestamp()), created_s=rec["created"], expires_s=rec["expires"], price=price,
                        lots=rec.get("lots_for_20gbp_risk"), stop_pips=rec.get("stop_pips"), rr=reward / risk, reward_gbp=RISK * reward / risk,
                        float_r=float_r, pnl_gbp=(None if not closed else float(r["net_r"] or 0) * RISK), reason=str(rec.get("reason", "")),
                        pips_to_entry=(None if price is None else (rec["entry"] - price) / p_), score=rec.get("score"), events=ev,
                        resolved_at=r["resolved_at"]))
    return out


def trade_card(i, t, now):
    st = t["state"]
    cls = {"OPEN": "open", "PENDING": "pending", "TARGET": "win", "STOP": "loss", "TIMEOUT": "loss"}.get(st, "dead")
    name = STRATS.get(t["type"], (t["type"],))[0]
    d = t["dir"]
    if t["closed"] and t["pnl_gbp"] is not None and st in ("TARGET", "STOP", "TIMEOUT"):
        big, sub, c = gbp(t["pnl_gbp"]), f"closed · {st.lower()}", ("up" if t["pnl_gbp"] > 0 else "dn")
    elif t["closed"]:
        big, sub, c = "£0", f"{st.lower()} · no trade taken", "muted"
    elif t["float_r"] is not None:
        g = t["float_r"] * RISK
        big, sub, c = gbp(g), f"floating · {t['float_r']:+.2f}R (before commission/swap)", ("up" if g > 0.5 else "dn" if g < -0.5 else "muted")
    else:
        pe = t["pips_to_entry"]
        big, sub, c = "waiting", ("" if pe is None else f"price is {abs(pe):.1f} pips {'below' if pe > 0 else 'above'} the entry"), "muted"
    exp = pd.Timestamp(t["expires_s"])
    if st == "PENDING":
        when = f"expires in {max(0, (exp - now).total_seconds() / 3600):.1f}h"
    elif st == "OPEN" and t["fill_ts"]:
        when = f"open for {(now - pd.Timestamp(t['fill_ts'], unit='s', tz='UTC')).total_seconds() / 3600:.1f}h"
    else:
        when = f"{t['resolved_at'][5:16]} UTC" if t["resolved_at"] else ""
    bar = ""
    if not t["closed"] and t["price"] is not None:
        a, b = t["stop"], t["target"]
        pct = 0 if a == b else min(100, max(0, (t["price"] - a) / (b - a) * 100))
        pe = 0 if a == b else min(100, max(0, (t["entry"] - a) / (b - a) * 100))
        bar = (f"<div class='bar'><i style='left:{pe:.1f}%' class='en'></i><b style='left:{pct:.1f}%'></b></div>"
               f"<div class='barl'><span>STOP {px(t['pair'], t['stop'])}</span><span>price {px(t['pair'], t['price'])}</span><span>TARGET {px(t['pair'], t['target'])}</span></div>")
    nums = [("Entry", px(t["pair"], t["entry"]), f"{t['entry_kind']} order"), ("Stop", px(t["pair"], t["stop"]), f"{t['stop_pips']} pips · −£{RISK:.0f}"),
            ("Target", px(t["pair"], t["target"]), f"+£{t['reward_gbp']:.0f} · 1:{t['rr']:.1f}"), ("Size", f"{t['lots']} lots", f"risk £{RISK:.0f}"),
            ("Price now", "—" if t["price"] is None else px(t["pair"], t["price"]), "bid"), ("Filled at", "—" if t["fill"] is None else px(t["pair"], t["fill"]), "hypothetical")]
    nh = "".join(f"<div><small>{a}</small><b>{b}</b><span>{c2}</span></div>" for a, b, c2 in nums)
    why = "".join(f"<div>{e(x)}</div>" for x in t["reason"].split("\n")[:2] if x.strip())
    tl = "".join(f"<span class='chip'>{x['ts'][11:16]} {e(x['d'][:44])}</span>" for x in t["events"][:8])
    return (f"<div class='trade {cls}'><div class='th'><div><span class='pair'>{t['pair']}</span><span class='dir {d}'>{d.upper()}</span>"
            f"<span class='state'>{st}</span></div><div class='pl'><b class='{c}'>{big}</b><small>{sub}</small></div></div>"
            f"<div class='rule'>{e(name)} · {t['tf']} · {when} · <span class='warnt'>UNPROVEN</span></div>"
            f"<div class='tc' data-i='{i}'></div>{bar}<div class='nums'>{nh}</div><div class='why'>{why}</div><div class='tl'>{tl}</div></div>")


def live_record(c):
    rows = c.execute("""SELECT s.run_id, s.created_at, s.pair, s.type, s.tf, s.record, o.reason, o.net_r,
        (SELECT to_state FROM events e WHERE e.run_id=s.run_id ORDER BY idx DESC LIMIT 1) AS state
        FROM setups s LEFT JOIN outcomes o USING(run_id) ORDER BY s.created_at DESC""").fetchall()
    return [dict(r) | {"rec": json.loads(r["record"])} for r in rows]


def balance_series(df):
    sc = df[df.triggered].sort_values("created")
    bal = START + (sc.net_r * RISK).cumsum()
    ruin = bal[bal <= 0]
    if len(ruin):
        bal = bal.copy()
        bal[bal.index >= ruin.index[0]] = 0.0
    return bal.set_axis(pd.to_datetime(sc.created.values, utc=True)), (len(ruin) and int((sc.net_r * RISK).cumsum().le(-START).values.argmax()) + 1) or None


def donut(parts, size=120):
    tot = sum(v for _, v, _ in parts) or 1
    a0, out = -np.pi / 2, ""
    for name, v, col in parts:
        a1 = a0 + v / tot * 2 * np.pi
        if v / tot > .9999:
            out += f"<circle cx='60' cy='60' r='44' fill='none' stroke='{col}' stroke-width='16'/>"
        elif v > 0:
            x0, y0, x1, y1 = 60 + 44 * np.cos(a0), 60 + 44 * np.sin(a0), 60 + 44 * np.cos(a1), 60 + 44 * np.sin(a1)
            out += f"<path d='M{x0:.1f},{y0:.1f} A44,44 0 {1 if a1 - a0 > np.pi else 0} 1 {x1:.1f},{y1:.1f}' fill='none' stroke='{col}' stroke-width='16'><title>{name}: {v:,}</title></path>"
        a0 = a1
    leg = "".join(f"<div><i style='background:{c}'></i>{n} <b class='mono'>{v:,}</b> <span class='muted'>({v / tot * 100:.0f}%)</span></div>" for n, v, c in parts)
    return f"<div class='donut'><svg viewBox='0 0 120 120' width='{size}' height='{size}'>{out}</svg><div class='dl'>{leg}</div></div>"


def hist(r):
    bins = np.linspace(-1.6, 2.6, 22)
    h, _ = np.histogram(np.clip(r, -1.6, 2.6), bins=bins)
    m = h.max() or 1
    bars = "".join(f"<rect x='{4 + i * 24:.0f}' y='{110 - v / m * 100:.0f}' width='20' height='{v / m * 100:.0f}' rx='2' "
                   f"fill='{TOK['CRIT'] if bins[i] < 0 else TOK['GOOD']}' opacity='.85'><title>{bins[i]:+.1f}R to {bins[i + 1]:+.1f}R: {v:,} trades</title></rect>" for i, v in enumerate(h))
    return (f"<svg viewBox='0 0 520 130' class='chart'>{bars}<text x='4' y='125' class='ax'>-1.6R</text><text x='236' y='125' class='ax'>0</text>"
            f"<text x='470' y='125' class='ax'>+2.6R</text></svg>")


def group_table(sc, key, label):
    g = sc.groupby(key).net_r.agg(["count", lambda x: (x > 0).mean() * 100, "mean"])
    rows = "".join(f"<tr><td>{k}</td><td class='num'>{int(c):,}</td><td class='num'>{w:.0f}%</td><td class='num {'up' if m > 0 else 'dn'}'>{m:+.2f}R</td></tr>" for k, (c, w, m) in g.iterrows())
    return f"<table class='tbl'><tr><th>{label}</th><th class='r'>Trades</th><th class='r'>Win</th><th class='r'>Net R</th></tr>{rows}</table>"


def candle_data(root):
    out = {}
    for sym in PAIRS:
        out[sym] = {}
        m5 = store.load(sym, "M5", root, tail=8000)
        srcs = {"H1": store.load(sym, "H1", root, tail=1500), "H4": store.load(sym, "H4", root, tail=1500)}
        if len(m5):
            from ..data.resample import resample
            srcs["M15"] = resample(m5, "M15", base="M5")
        for tf, d in srcs.items():
            if d.empty:
                continue
            c = d.bid_c
            e = {n: c.ewm(span=n, adjust=False, min_periods=n).mean() for n in (20, 50, 200)}
            dl = c.diff()
            up, dn = dl.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(), (-dl.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
            rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
            t = d.tail(300)
            rd = lambda s, k=5: [None if pd.isna(v) else round(float(v), k) for v in s.loc[t.index]]
            out[sym][tf] = dict(t=[f"{i:%d %b %H:%M}" for i in t.index], ts=[int(i.timestamp()) for i in t.index], hr=[int(i.hour) for i in t.index], o=rd(t.bid_o), h=rd(t.bid_h),
                                l=rd(t.bid_l), c=rd(t.bid_c), e20=rd(e[20]), e50=rd(e[50]), e200=rd(e[200]), rsi=rd(rsi, 1))
    return out


def key_levels(m5):
    """Previous-day high/low and today's open (17:00 New York trading day), weekly open, and today's Asian range (00-07 UTC)."""
    from ..data.daily import daily_bars_ny
    from ..calendar import NY
    out = []
    if m5.empty:
        return out
    dly = daily_bars_ny(m5.tail(60000))
    if len(dly):
        out += [dict(k="PDH", v=float(dly.bid_h.iloc[-1])), dict(k="PDL", v=float(dly.bid_l.iloc[-1]))]
        today = m5[m5.index >= dly.close_time.iloc[-1]]
        if len(today):
            out.append(dict(k="DO", v=float(today.bid_o.iloc[0])))
        sun = dly[dly.index.tz_convert(NY).day_of_week == 6]
        if len(sun):
            wk = m5[m5.index >= sun.index[-1]]
            if len(wk):
                out.append(dict(k="WO", v=float(wk.bid_o.iloc[0])))
    day0 = m5.index[-1].normalize()
    asia = m5[(m5.index >= day0) & (m5.index < day0 + pd.Timedelta(hours=7))]
    if len(asia) > 12:
        out += [dict(k="AH", v=float(asia.bid_h.max())), dict(k="AL", v=float(asia.bid_l.min()))]
    return out


def trend_glyph(d):
    if d is None or len(d) < 210:
        return "<span class='muted'>–</span>"
    c = d.bid_c
    e50, e200 = c.ewm(span=50, adjust=False).mean().iloc[-1], c.ewm(span=200, adjust=False).mean().iloc[-1]
    if e50 > e200 and c.iloc[-1] > e50:
        return "<span class='up'>▲</span>"
    if e50 < e200 and c.iloc[-1] < e50:
        return "<span class='dn'>▼</span>"
    return "<span class='warnt'>◆</span>"


def pair_table(root, cands, lv):
    """All 10 pairs at a glance: price, day change, volatility, trend on 3 timeframes, distance to yesterday's range, spread, setup."""
    from ..data.resample import resample
    st = strength(root)
    srow = st.iloc[-1] if st is not None and len(st) else None
    rows = ""
    for sym in PAIRS:
        m5 = store.load(sym, "M5", root, tail=7000)
        if m5.empty:
            continue
        p = pip(sym)
        last = m5.iloc[-1]
        h1 = store.load(sym, "H1", root, tail=1500)
        h4 = store.load(sym, "H4", root, tail=1500)
        m15 = resample(m5.tail(6000), "M15", base="M5")
        levels = {x["k"]: x["v"] for x in lv.get(sym, []) if x["k"] in ("PDH", "PDL", "DO")}
        chg = "" if "DO" not in levels else f"{(last.bid_c / levels['DO'] - 1) * 100:+.2f}%"
        atr_h1 = "" if len(h1) < 20 else f"{((h1.bid_h - h1.bid_l).tail(14).mean() / p):.0f}"
        pdh = "" if "PDH" not in levels else f"{(levels['PDH'] - last.bid_c) / p:+.0f}"
        pdl = "" if "PDL" not in levels else f"{(last.bid_c - levels['PDL']) / p:+.0f}"
        spr = f"{(last.ask_c - last.bid_c) / p:.1f}" if "ask_c" in m5.columns else ""
        sd = "" if srow is None else f"{srow[sym[:3]] - srow[sym[3:]]:+.2f}"
        setup = next((f"<span class='st'>{c.get('state', 'PENDING')}</span> {c['direction'].upper()}" for c in cands if c["pair"] == sym), "<span class='muted'>–</span>")
        cls = "dn" if chg.startswith("-") else "up"
        rows += (f"<tr class='pk' onclick=\"pickPair('{sym}')\"><td><b>{sym}</b></td><td class='num'>{px(sym, last.bid_c)}</td><td class='num {cls}'>{chg}</td>"
                 f"<td class='num hm'>{atr_h1}</td><td>{trend_glyph(m15)} {trend_glyph(h1)} {trend_glyph(h4)}</td><td class='num hm'>{pdh} / {pdl}</td>"
                 f"<td class='num hm'>{spr}</td><td class='num hm'>{sd}</td><td>{setup}</td></tr>")
    return ("<table class='tbl'><tr><th>Pair</th><th class='r'>Price</th><th class='r'>Day</th><th class='r hm'>H1 range (pips)</th><th>Trend M15 · H1 · H4</th>"
            "<th class='r hm'>To PDH / from PDL (pips)</th><th class='r hm'>Spread (pips)</th><th class='r hm'>Strength gap</th><th>Setup</th></tr>" + rows + "</table>"
            "<p class='muted'>Trend: ▲ EMA50 above EMA200 and price above EMA50 · ▼ the reverse · ◆ mixed. PDH/PDL = previous trading day high/low. "
            "Click a row to chart it. A reading aid, not a signal: every rule built on these failed its tests.</p>")


# ---------- page ----------
CSS = """
:root{--bg:#111110;--card:#1a1a19;--line:#2c2c2a;--ink:#f0efec;--ink2:#c3c2b7;--mute:#8d8c84;--s1:#3987e5;--s2:#d95926;--good:#0ca30c;--warn:#fab219;--crit:#d03b3b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,'Inter','Segoe UI',sans-serif}
.wrap{max-width:1360px;margin:0 auto;padding:14px 16px 40px}
.top{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:6px 0 10px}
.brand{font-weight:700;letter-spacing:.14em;font-size:13px}.chip{border:1px solid var(--line);border-radius:999px;padding:3px 10px;font-size:11px;color:var(--ink2)}
.pill{display:inline-flex;align-items:center;gap:7px;border-radius:999px;padding:4px 12px;font-weight:700;font-size:12px;letter-spacing:.06em;color:#fff}
.pill.good{background:#0a6e0a}.pill.warn{background:#8a5f00}.pill.crit{background:#9c2b2b}
.sp{flex:1}.mono,.num{font-family:ui-monospace,'SF Mono',Menlo,monospace;font-variant-numeric:tabular-nums}
.tabs{display:flex;gap:4px;overflow-x:auto;border-bottom:1px solid var(--line);margin-bottom:12px}
.tabs button{background:none;border:0;color:var(--ink2);padding:9px 14px;font:600 12px inherit;font-family:inherit;letter-spacing:.06em;text-transform:uppercase;cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap}
.tabs button.on{color:var(--ink);border-bottom-color:var(--s1)}.tab{display:none}.tab.on{display:block}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:0 0 12px}
.kpi,.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.kpi small{color:var(--mute);text-transform:uppercase;letter-spacing:.08em;font-size:12px}.kpi b{display:block;font:600 28px ui-monospace,Menlo,monospace;margin-top:2px}
.kpi span{color:var(--mute);font-size:13px}
.verdict{border:1px solid var(--crit);background:color-mix(in srgb,var(--crit) 12%,var(--card));border-radius:10px;padding:10px 14px;margin:0 0 12px}
h3{margin:0 0 10px;font-size:13px;text-transform:uppercase;letter-spacing:.1em;color:var(--ink2);font-weight:600}
.grid{display:grid;gap:12px;grid-template-columns:repeat(12,1fr)}.c12{grid-column:span 12}.c8{grid-column:span 8}.c7{grid-column:span 7}.c6{grid-column:span 6}.c5{grid-column:span 5}.c4{grid-column:span 4}
@media(max-width:900px){.c8,.c7,.c6,.c5,.c4{grid-column:span 12}}
.setup{display:grid;grid-template-columns:150px minmax(240px,440px) 1fr;gap:12px;align-items:center;padding:10px 0;border-top:1px solid var(--line)}
.setup:first-of-type{border-top:0}.setup .pair{font-weight:700;font-size:15px}
.dir{display:inline-block;padding:1px 8px;border-radius:4px;font-size:11px;font-weight:700;margin-left:6px}.dir.long{background:#0a6e0a;color:#fff}.dir.short{background:#9c2b2b;color:#fff}
.st{border:1px solid var(--line);border-radius:4px;padding:1px 7px;font-size:10px;letter-spacing:.08em;color:var(--ink2)}
.meta{color:var(--mute);font-size:11px;margin-top:4px}.warnt{color:var(--warn);font-weight:600}
@media(max-width:700px){.setup{grid-template-columns:1fr}}
.mini{width:100%;height:96px;display:block;background:color-mix(in srgb,var(--bg) 60%,var(--card));border-radius:6px}.spark{width:100%;height:24px}
.chart{width:100%;display:block}.ax{fill:var(--ink2);font-size:12px}.bt{fill:#fff;font-size:9px;font-weight:700;letter-spacing:.06em}.lbl{fill:var(--ink2);font-size:13px;font-weight:600}
svg .grid{stroke:var(--line);stroke-width:1}.zero{stroke:var(--mute);stroke-width:1}
.legend{display:flex;gap:14px;margin-bottom:4px;color:var(--ink2);font-size:11px;flex-wrap:wrap}.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
.lc,.cc{position:relative}.cross{stroke:var(--mute);stroke-width:1;display:none}.tip{position:absolute;display:none;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:6px 9px;font-size:11px;pointer-events:none;white-space:nowrap;top:22px;z-index:3}
.heat{border-collapse:separate;border-spacing:2px;width:100%}.heat th{width:42px;text-align:left;color:var(--ink2);font-size:11px}.heat td{height:18px;border-radius:2px}.heat td.num{width:62px;background:none;text-align:right;font-size:11px}
.scale{display:flex;align-items:center;gap:8px;color:var(--mute);font-size:10px;margin-top:6px}.scale i{flex:1;height:5px;border-radius:3px;background:linear-gradient(90deg,#d03b3b,#383835,#3987e5)}
.up{color:#3fb950}.dn{color:#ec6a5e}.muted{color:var(--mute)}
.frow{display:grid;grid-template-columns:130px 1fr 64px;gap:10px;align-items:center;margin:7px 0}.fbar{height:12px;background:var(--line);border-radius:3px}.fbar b{display:block;height:100%;background:var(--s1);border-radius:3px}.frow em{font:600 12px ui-monospace,Menlo,monospace;text-align:right;font-style:normal}
.split{display:flex;gap:14px;margin:8px 0;color:var(--ink2);font-size:11px;flex-wrap:wrap}
.tbl{width:100%;border-collapse:collapse}.tbl th{color:var(--mute);font-size:12px;text-transform:uppercase;letter-spacing:.06em;text-align:left;padding:5px 6px;border-bottom:1px solid var(--line)}.tbl td{padding:7px 6px;border-bottom:1px solid var(--line);vertical-align:top}.tbl td.num,.tbl th.r{text-align:right}.ci{width:160px;height:14px;display:block}
.card{overflow-x:auto}.tag{display:inline-block;border-radius:4px;padding:1px 8px;font-size:10px;font-weight:700;letter-spacing:.06em}.tag.f{background:#9c2b2b;color:#fff}.tag.p{background:#0a6e0a;color:#fff}.tag.n{background:var(--line);color:var(--ink2)}
.cyc{display:flex;gap:3px;flex-wrap:wrap;margin:8px 0}.cyc i{width:11px;height:16px;border-radius:2px;background:var(--line)}
.donut{display:flex;gap:14px;align-items:center;flex-wrap:wrap}.dl div{margin:3px 0}.dl i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}
.sel{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}.sel button{background:var(--card);border:1px solid var(--line);color:var(--ink2);border-radius:6px;padding:4px 10px;font:600 11px inherit;font-family:inherit;cursor:pointer}.sel button.on{border-color:var(--s1);color:var(--ink)}
.tbl tr.pk{cursor:pointer}.tbl tr.pk:hover{background:#222220}.tabs button{font-size:14px;padding:11px 16px}.chip{font-size:13px}.pill{font-size:14px}.pk td{font-size:14px}
.sec{font-size:16px;margin:18px 0 10px;letter-spacing:.02em}.sec small{color:var(--mute);font-weight:400;font-size:13px;margin-left:8px}
.trades{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,560px),1fr));gap:16px}
.trade{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;border-left:6px solid var(--mute)}
.trade.open{border-left-color:var(--s1)}.trade.pending{border-left-color:var(--warn)}.trade.win{border-left-color:var(--good)}.trade.loss{border-left-color:var(--crit)}.trade.dead{border-left-color:#4a4a46;opacity:.85}
.trade .th{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.trade .pair{font-size:26px;font-weight:700;letter-spacing:.01em}.trade .dir{font-size:14px;padding:3px 10px;margin-left:10px;vertical-align:4px}
.trade .state{margin-left:10px;border:1px solid var(--line);border-radius:6px;padding:3px 10px;font-size:13px;font-weight:700;letter-spacing:.08em;vertical-align:4px;color:var(--ink)}
.trade .pl{text-align:right}.trade .pl b{display:block;font:700 34px ui-monospace,Menlo,monospace}.trade .pl small{color:var(--mute);font-size:13px}
.trade .rule{color:var(--ink2);font-size:14px;margin:6px 0 10px}.tc{width:100%;min-height:200px}
.bar{position:relative;height:12px;border-radius:6px;background:linear-gradient(90deg,#9c2b2b,#3a3a36 45%,#0a6e0a);margin:14px 0 4px}
.bar b{position:absolute;top:-5px;width:6px;height:22px;background:#fff;border-radius:3px;transform:translateX(-3px)}.bar i.en{position:absolute;top:-3px;width:3px;height:18px;background:#5aa0f0}
.barl{display:flex;justify-content:space-between;color:var(--ink2);font-size:13px;font-family:ui-monospace,Menlo,monospace}
.nums{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0 8px}
.nums div{background:color-mix(in srgb,var(--bg) 55%,var(--card));border-radius:8px;padding:9px 12px}.nums small{display:block;color:var(--mute);font-size:12px;text-transform:uppercase;letter-spacing:.07em}
.nums b{display:block;font:600 19px ui-monospace,Menlo,monospace}.nums span{color:var(--mute);font-size:13px}
.why{color:var(--ink);font-size:15px;margin:8px 0}.tl{display:flex;gap:6px;flex-wrap:wrap}.tl .chip{font-size:12px}
.empty{background:var(--card);border:1px dashed var(--line);border-radius:14px;padding:34px;text-align:center;font-size:17px}
.sel button{font-size:14px;padding:7px 14px}.legend{font-size:13px}
@media(max-width:600px){.hm{display:none}.top{gap:6px}.chip{padding:2px 8px;font-size:12px}.kpis{grid-template-columns:repeat(2,1fr);gap:8px}.kpi{padding:10px 12px}.kpi b{font-size:22px}.kpi small{font-size:11px}.kpi span{font-size:12px}.wrap{padding:10px 10px 30px}}
.sample{background:var(--warn);color:#000;text-align:center;font-weight:700;padding:6px;border-radius:6px;margin-bottom:10px}
p{margin:6px 0}
"""

JS = """<script>
const $=s=>document.querySelector(s),tabs=document.querySelectorAll('.tabs button'),secs=document.querySelectorAll('.tab');
function showTab(n){tabs.forEach(b=>b.classList.toggle('on',b.dataset.t===n));secs.forEach(s=>s.classList.toggle('on',s.id===n));history.replaceState(null,'','#'+n);renderAll()}
tabs.forEach(b=>b.onclick=()=>showTab(b.dataset.t));
document.querySelectorAll('.lc').forEach(function(el){var d=JSON.parse(el.dataset.j),pre=el.dataset.pre||'',suf=el.dataset.suf||'',svg=el.querySelector('svg'),cr=el.querySelector('.cross'),tp=el.querySelector('.tip');
svg.addEventListener('mousemove',function(ev){var r=svg.getBoundingClientRect(),px=(ev.clientX-r.left)/r.width*560,best=0,bd=1e9;d[0].x.forEach(function(x,i){var q=Math.abs(x-px);if(q<bd){bd=q;best=i}});
cr.setAttribute('x1',d[0].x[best]);cr.setAttribute('x2',d[0].x[best]);cr.style.display='block';
tp.innerHTML='<b>'+d[0].t[best]+'</b><br>'+d.map(function(s){var i=Math.round(best/(d[0].x.length-1)*(s.v.length-1));return s.n+': '+pre+s.v[i].toLocaleString()+suf}).join('<br>')
;tp.style.display='block';tp.style.left=Math.min(ev.clientX-r.left+12,r.width-170)+'px'});
svg.addEventListener('mouseleave',function(){cr.style.display='none';tp.style.display='none'})});

const CD=JSON.parse($('#cd').textContent),LV=JSON.parse($('#lv').textContent),TR=JSON.parse($('#tr').textContent);
const S={pair:'EURUSD',tf:'H1',n:100,mode:'single',ema:true,sess:true,lvl:true};
const LC={PDH:['#b9b8ae','prev day high'],PDL:['#b9b8ae','prev day low'],DO:['#e6e5de','day open'],WO:['#9085e9','week open'],AH:['#e8793f','Asia high'],AL:['#e8793f','Asia low']};
const dpOf=p=>p.slice(3)==='JPY'?3:5, rc=(x,y,w,h,f,o,x2)=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${f}" opacity="${o}"${x2||''}/>`;
const ln=(x1,x2,y1,y2,c,w,d)=>`<line x1="${x1}" x2="${x2}" y1="${y1}" y2="${y2}" stroke="${c}" stroke-width="${w||1}"${d?` stroke-dasharray="${d}"`:''}/>`;
const tx=(x,y,t,c,a,sz,b)=>`<text x="${x}" y="${y}" fill="${c||'#c3c2b7'}" font-size="${sz||12}" text-anchor="${a||'start'}"${b?' font-weight="700"':''}>${t}</text>`;
function tag(x,y,t,bg,fg){const w=t.length*7.4+12;return `<rect x="${x}" y="${y-11}" width="${w}" height="22" rx="4" fill="${bg}"/>`+tx(x+6,y+4,t,fg||'#fff','start',12,true)}
function chart(d,pair,lv,o){
 const W=Math.max(300,Math.floor(o.w)),H=o.h,sm=W<560,L=sm?54:66,R=sm?70:110,T=14,AX=30,RH=o.rsi?80:0,PH=H-T-AX-(RH?RH+14:0);
 const N=d.c.length,n0=Math.max(0,N-o.n),n=N-n0,dp=dpOf(pair),z=o.z;
 let hi=-1e9,lo=1e9;for(let i=n0;i<N;i++){hi=Math.max(hi,d.h[i]);lo=Math.min(lo,d.l[i])}
 const rg=hi-lo;if(z){[z.entry,z.stop,z.target].concat(z.fill?[z.fill]:[]).forEach(v=>{hi=Math.max(hi,v);lo=Math.min(lo,v)})}
 const show=o.lvl?lv.filter(q=>!['entry','stop','target'].includes(q.k)&&q.v>lo-rg*.35&&q.v<hi+rg*.35):[];
 show.forEach(q=>{hi=Math.max(hi,q.v);lo=Math.min(lo,q.v)});const pd=(hi-lo)*.07;hi+=pd;lo-=pd;
 const y=v=>T+(hi-v)/(hi-lo)*PH,cw=(W-L-R)/n,x=i=>L+(i-n0)*cw+cw/2,F=v=>v.toFixed(dp);let s='';
 if(o.sess)for(let i=n0;i<N;i++){const h=d.hr[i],xx=L+(i-n0)*cw;if(h<7)s+=rc(xx,T,cw+.5,PH,'#d95926',.08);if(h>=7&&h<16)s+=rc(xx,T,cw+.5,PH,'#3987e5',.10);if(h>=12&&h<21)s+=rc(xx,T,cw+.5,PH,'#0ca30c',.08)}
 for(let k=0;k<=4;k++){const v=lo+(hi-lo)*k/4;s+=ln(L,W-R,y(v),y(v),'#2c2c2a',1)+tx(L-8,y(v)+4,F(v),'#c3c2b7','end',sm?11:12)}
 const nl=sm?3:5;for(let k=0;k<nl;k++){const j=n0+Math.round(k*(n-1)/(nl-1));s+=tx(Math.min(Math.max(x(j),L+26),W-R-26),H-8,sm?d.t[j].slice(0,6):d.t[j],'#c3c2b7','middle',sm?11:12)}
 let x0=L;if(z){let si=n0;for(let i=n0;i<N;i++){if(d.ts[i]>=z.created){si=i;break}}x0=L+(si-n0)*cw;
  const yE=y(z.entry),yS=y(z.stop),yT=y(z.target);
  s+=rc(x0,Math.min(yE,yS),W-R-x0,Math.abs(yS-yE),'#d03b3b',.17)+rc(x0,Math.min(yE,yT),W-R-x0,Math.abs(yT-yE),'#0ca30c',.17)}
 for(let i=n0;i<N;i++){const up=d.c[i]>=d.o[i],c=up?'#3fb950':'#ef6a5e';s+=ln(x(i),x(i),y(d.h[i]),y(d.l[i]),c,1.4)+rc(x(i)-cw*.36,y(Math.max(d.o[i],d.c[i])),cw*.72,Math.max(2,Math.abs(y(d.o[i])-y(d.c[i]))),c,1)}
 if(o.ema){let em='';[['e20','#fab219'],['e50','#5aa0f0'],['e200','#e8793f']].forEach(e=>{const p=[];for(let i=n0;i<N;i++)if(d[e[0]][i]!=null)p.push(x(i)+','+y(d[e[0]][i]));if(p.length>1)em+=`<polyline points="${p.join(' ')}" fill="none" stroke="${e[1]}" stroke-width="1.8"/>`});
  const id='cp'+(chart.k=(chart.k||0)+1);s+=`<clipPath id="${id}"><rect x="${L}" y="${T}" width="${W-R-L}" height="${PH}"/></clipPath><g clip-path="url(#${id})">${em}</g>`}
 show.forEach(q=>{const c=LC[q.k]||['#b9b8ae',q.k];s+=ln(L,W-R,y(q.v),y(q.v),c[0],1.2,'3 5')+(sm?'':tx(W-R+6,y(q.v)+4,c[1],c[0],'start',12))});
 if(z){const yE=y(z.entry),yS=y(z.stop),yT=y(z.target);
  s+=ln(L,W-R,yE,yE,'#5aa0f0',2,'7 5')+ln(L,W-R,yS,yS,'#ef4444',2.4)+ln(L,W-R,yT,yT,'#22c55e',2.4);
  s+=tag(W-R+4,yE,'ENTRY '+(sm?'':F(z.entry)),'#2563eb')+tag(W-R+4,yS,'STOP '+(sm?'':F(z.stop)),'#b91c1c')+tag(W-R+4,yT,'TARGET '+(sm?'':F(z.target)),'#15803d');
  if(z.fill){const yF=y(z.fill);s+=ln(L,W-R,yF,yF,'#f0efec',1.4,'2 3')+tx(L+6,yF-5,'filled '+F(z.fill),'#f0efec','start',12,true)}
  s+=ln(x0,x0,T,T+PH,'#f0efec',1,'3 4')+tx(Math.min(x0+4,W-R-90),T+14,'published','#f0efec','start',12);
  if(z.fill_ts){let fi=n0;for(let i=n0;i<N;i++){if(d.ts[i]>=z.fill_ts){fi=i;break}}s+=ln(x(fi),x(fi),T,T+PH,'#fab219',1.2,'3 4')+tx(Math.min(x(fi)+4,W-R-70),T+30,'filled','#fab219','start',12)}}
 const last=d.c[N-1],yl=y(last);s+=ln(L,W-R,yl,yl,'#fff',1,'1 3')+tag(W-R+4,Math.min(Math.max(yl,T+12),T+PH-12),(sm?'NOW':'NOW '+F(last)),'#f0efec','#111');
 if(RH){const r0=T+PH+14,yr=v=>r0+(100-v)/100*RH;s+=`<rect x="${L}" y="${r0}" width="${W-R-L}" height="${RH}" fill="none" stroke="#2c2c2a"/>`+ln(L,W-R,yr(70),yr(70),'#2c2c2a',1)+ln(L,W-R,yr(30),yr(30),'#2c2c2a',1)+tx(L-8,yr(70)+4,'70','#c3c2b7','end',12)+tx(L-8,yr(30)+4,'30','#c3c2b7','end',12)+tx(W-R+6,r0+14,'RSI 14','#c3c2b7','start',12);
  const p=[];for(let i=n0;i<N;i++)if(d.rsi[i]!=null)p.push(x(i)+','+yr(d.rsi[i]));s+=`<polyline points="${p.join(' ')}" fill="none" stroke="#a89cf5" stroke-width="1.8"/>`}
 for(let i=n0;i<N;i++)s+=`<rect x="${x(i)-cw/2}" y="${T}" width="${cw}" height="${PH}" fill="transparent"><title>${d.t[i]}  O ${F(d.o[i])}  H ${F(d.h[i])}  L ${F(d.l[i])}  C ${F(d.c[i])}${d.rsi[i]!=null?'  RSI '+d.rsi[i]:''}</title></rect>`;
 return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" class="chart">${s}</svg>`}
function renderTrades(){document.querySelectorAll('.tc').forEach(el=>{const t=TR[+el.dataset.i],P=CD[t.pair]||{},tf=t.tf==='H4'?'H1':'M15',d=P[tf];if(!d){el.innerHTML='<p class="muted">No price data for this pair yet.</p>';return}
 el.innerHTML=chart(d,t.pair,LV[t.pair]||[],{w:el.clientWidth,h:el.clientWidth<560?320:380,n:el.clientWidth<560?40:(tf==='M15'?96:100),ema:true,sess:true,lvl:true,z:t})})}
function mk(id,items,cur,fn){const el=$('#'+id);if(!el)return;el.innerHTML='';items.forEach(x=>{const b=document.createElement('button');b.textContent=x[1];if(x[0]===cur)b.className='on';b.onclick=()=>fn(x[0]);el.appendChild(b)})}
function pickPair(p){S.pair=p;S.mode='single';showTab('charts');window.scrollTo(0,0)}
function renderCharts(){const cv=$('#cv');if(!cv||!cv.clientWidth)return;
 mk('psel',Object.keys(CD).map(p=>[p,p]),S.pair,x=>{S.pair=x;renderCharts()});
 mk('tsel',[['M15','M15'],['H1','H1'],['H4','H4'],['MTF','All 3']],S.mode==='mtf'?'MTF':S.tf,x=>{if(x==='MTF')S.mode='mtf';else{S.mode='single';S.tf=x}renderCharts()});
 mk('nsel',[[50,'50 candles'],[100,'100'],[200,'200']],S.n,x=>{S.n=x;renderCharts()});
 mk('osel',[['ema','EMAs '+(S.ema?'on':'off')],['sess','Sessions '+(S.sess?'on':'off')],['lvl','Levels '+(S.lvl?'on':'off')]],'',x=>{S[x]=!S[x];renderCharts()});
 const P=CD[S.pair]||{},lv=LV[S.pair]||[],w=cv.clientWidth,
 leg='<div class="legend"><span><i style="background:#fab219"></i>EMA 20</span><span><i style="background:#5aa0f0"></i>EMA 50</span><span><i style="background:#e8793f"></i>EMA 200</span><span><i style="background:#d95926;opacity:.6"></i>Asia</span><span><i style="background:#3987e5;opacity:.7"></i>London</span><span><i style="background:#0ca30c;opacity:.7"></i>New York (UTC)</span></div>';
 const tradeZ=TR.find(t=>t.pair===S.pair&&(t.state==='OPEN'||t.state==='PENDING'));
 if(S.mode==='mtf'){let h='';['H4','H1','M15'].forEach(t=>{if(P[t])h+=`<div style="margin-bottom:10px"><b style="font-size:15px">${S.pair} · ${t}</b>${chart(P[t],S.pair,lv,{w:w,h:300,n:Math.min(S.n,w<560?40:100),ema:S.ema,sess:S.sess&&t!=='H4',lvl:S.lvl,z:tradeZ||null})}</div>`});cv.innerHTML=leg+h;return}
 const d=P[S.tf];if(!d){cv.innerHTML='<p class="muted">No data for this pair/timeframe.</p>';return}
 cv.innerHTML=leg+chart(d,S.pair,lv,{w:w,h:w<560?430:560,n:w<560?Math.min(S.n,60):S.n,rsi:true,ema:S.ema,sess:S.sess&&S.tf!=='H4',lvl:S.lvl,z:tradeZ||null})}
function renderAll(){const on=document.querySelector('.tab.on');if(!on)return;if(on.id==='overview')renderTrades();if(on.id==='charts')renderCharts()}
let rz;window.addEventListener('resize',()=>{clearTimeout(rz);rz=setTimeout(renderAll,150)});
showTab((location.hash||'#overview').slice(1)||'overview');
</script>"""


def tag(ok, label=None):
    return f"<span class='tag {'p' if ok else 'f'}'>{label or ('PASS' if ok else 'FAIL')}</span>"


def build(root="data/candles", out="dashboard/index.html", now=None, banner=""):
    """out=None returns the HTML string instead of writing a file."""
    root = Path(root)
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    state, label, age, closed = health(root, now)
    scan = json.load(open("data/latest_scan.json")) if Path("data/latest_scan.json").exists() else {}
    dbc = live_db()
    cands = live_candidates(dbc) if dbc else []
    cand_src = "published by the live loop (ledger)" if dbc else "no ledger yet"
    if not cands and not dbc:
        cands, cand_src = scan.get("candidates", []), "last manual scan (no live loop ledger found)"
    from ..research import trials as _tr
    trials = _tr.count_trials(Path("docs/trials.jsonl"))
    res = research()
    base = res.get("H1") if res.get("H1") is not None else (next(iter(res.values())) if res else None)
    sc = base[base.triggered] if base is not None else None
    live = live_record(dbc) if dbc else []
    live_net = sum(r["net_r"] or 0 for r in live if r["reason"] in ("TARGET", "STOP", "TIMEOUT"))
    lp = live_pnl(dbc, root, now) if dbc else None
    uptime, next_cycle = ops_chips(dbc, now)
    livehtml = live_panel(lp)
    jr = J.load()
    j_bal = START + (jr.pnl_gbp.sum() if jr is not None else 0)
    icon = {"good": "●", "warn": "◐", "crit": "▲"}[state]
    # --- research rows first: the KPI counts are derived from them, never typed in
    rr = research_rows(res, max(trials, 1))
    m5rows = m5_rerun_rows()
    n_strats = len({(n, tfm) for n, tfm, *_ in rr}) or (7 if trials else 0)
    n_pass = sum(1 for *_, ok in rr if ok) + sum(1 for r in m5rows if r[-1])
    # --- account
    bal = ruin_at = None
    if base is not None:
        bal, ruin_at = balance_series(base)
    bt_end = None if bal is None else float(bal.iloc[-1])
    win = None if sc is None else (sc.net_r > 0).mean() * 100
    kp = [("Paper account (assumed)", f"£{START:,.0f}", f"£{RISK:.0f} risk per trade = {RISK / START * 100:.1f}%"),
          ("If every backtest setup was taken", "n/a" if bt_end is None else f"£{bt_end:,.0f}", "" if ruin_at is None else f"account empty after {ruin_at:,} trades"),
          ("Engine balance (live, hypothetical)", f"£{(lp['balance'] if lp else START):,.0f}", f"{len(live)} setups published so far"),
          ("Your journal balance", f"£{j_bal:,.0f}" if jr is not None else "—", "log trades in data/journal.csv"),
          ("Win rate · loss rate (backtest)", "n/a" if win is None else f"{win:.0f}% · {100 - win:.0f}%", "triggered setups, stressed costs"),
          ("Strategies tested", f"{n_strats}", f"{n_pass} passed · {trials} logged tests")]
    kpis = "".join(f"<div class='kpi'><small>{a}</small><b>{b}</b><span>{c}</span></div>" for a, b, c in kp)
    # --- positions
    levels, cards = {}, ""
    for c in cands:
        left = max(0, (pd.Timestamp(c["expires"]) - now).total_seconds() / 3600)
        risk = abs(c["entry"] - c["stop"]); rew = abs(c["target"] - c["entry"])
        levels.setdefault(c["pair"], []).extend([{"k": "entry", "v": c["entry"]}, {"k": "stop", "v": c["stop"]}, {"k": "target", "v": c["target"]}])
        cards += (f"<div class='setup'><div><span class='pair'>{c['pair']}</span><span class='dir {c['direction']}'>{c['direction'].upper()}</span>"
                  f"<div class='meta'><span class='st'>{e(c.get('state', 'PENDING'))}</span> {e(STRATS.get(c['type'], (c['type'],))[0])} · {c['tf']}</div>"
                  f"<div class='meta'>{e(str(c.get('reason', '')).split(chr(10))[0])}</div></div>{mini_chart(c, root)}"
                  f"<div class='mono'>entry {px(c['pair'], c['entry'])} ({c['entry_kind']})<br>stop {px(c['pair'], c['stop'])} <span class='muted'>({c['stop_pips']}p)</span><br>target {px(c['pair'], c['target'])}"
                  f"<div class='meta'>{c['lots_for_20gbp_risk']} lots · risk £{RISK:.0f} · reward £{RISK * rew / risk:.0f} (1:{rew / risk:.1f})<br>{left:.1f}h left · score {c['score']} · <span class='warnt'>UNPROVEN</span></div></div></div>")
    if not cards:
        cards = "<p class='muted' style='padding:14px 0'><b style='color:var(--ink)'>No setups right now.</b> A valid outcome. The scan runs when the market is open.</p>"
    # live record table
    done = [r for r in live if r["reason"]]
    wins, losses = sum(r["reason"] == "TARGET" for r in done), sum(r["reason"] in ("STOP",) for r in done)
    lr = "".join(f"<tr><td class='mono'>{r['created_at'][5:16]}</td><td>{r['pair']} {r['rec']['direction'].upper()}</td><td>{e(STRATS.get(r['type'], (r['type'],))[0])}</td>"
                 f"<td>{e(r['reason'] or r['state'] or 'PENDING')}</td><td class='num {'up' if (r['net_r'] or 0) > 0 else 'dn'}'>{'' if r['net_r'] is None else f'{r['net_r'] * RISK:+.0f} GBP'}</td></tr>" for r in live[:15])
    livetbl = (f"<p class='muted'>Published {len(live)} · resolved {len(done)} · target {wins} · stop {losses} · "
               f"success rate {'n/a' if not (wins + losses) else f'{wins / (wins + losses) * 100:.0f}%'}</p><table class='tbl'><tr><th>Created (UTC)</th><th>Setup</th><th>Rule</th><th>Outcome</th><th class='r'>P&amp;L</th></tr>{lr}</table>"
              if live else "<p class='muted'>No live setups recorded yet. This fills in once the live loop publishes its first setup.</p>")
    # --- research
    m5tab = "".join(f"<tr><td><b>{e(v)}</b></td><td>{k}</td><td class='num'>{n:,}</td><td class='num'>{pdays:,}</td><td class='num'>{w:.0f}%</td>"
                    f"<td class='num {'up' if m > 0 else 'dn'}'>{m:+.3f}R</td><td class='num'>{lo:+.3f}R</td><td class='num'>{mde:.3f}R</td>"
                    f"<td class='num'>{p95:+.3f}R / {pct:.0f}%</td><td>{tag(ok)}</td></tr>" for v, k, n, pdays, w, m, lo, mde, p95, pct, ok in m5rows)
    rtab = "".join(f"<tr><td><b>{e(n)}</b></td><td>{tfm}</td><td class='num'>{k:,}</td><td class='num'>{'—' if pd.isna(w) else f'{w:.0f}%'}</td>"
                   f"<td class='num {'up' if m > 0 else 'dn'}'>{m:+.2f}R</td><td class='num'>{'—' if pd.isna(lo) else f'{lo:+.2f}R'}</td><td>{tag(ok)}</td></tr>" for n, tfm, k, w, m, lo, ok in rr)
    strat = "".join(f"<tr><td><b>{e(v[0])}</b></td><td>{e(v[1])}</td></tr>" for v in STRATS.values())
    ta = "".join(f"<tr><td>{a}</td><td>{b}</td><td>{tag(c.startswith('Sizing'), 'TOOL') if c.startswith('Sizing') else (tag(False, 'NO EDGE') if c.startswith('Tested') else tag(True, 'TO DO').replace('p','n'))} <span class='muted'>{c}</span></td></tr>" for a, b, c in TA)
    # --- performance
    perf = "<p class='muted'>No backtest files found. Run the backtests on your Mac first.</p>"
    if sc is not None:
        sc2 = sc.copy()
        sc2["weekday"] = sc2.created.dt.day_name().str[:3]
        sc2["hour"] = sc2.created.dt.hour.map(lambda h: f"{h:02d}:00")
        notrig = int((~base.triggered).sum())
        perf = (f"<div class='grid'><div class='card c6'><h3>Success and loss rate · backtest ({len(sc):,} trades)</h3>"
                f"{donut([('Winners', int((sc.net_r > 0).sum()), TOK['GOOD']), ('Losers', int((sc.net_r <= 0).sum()), TOK['CRIT']), ('Never triggered', notrig, '#5a5a56')])}</div>"
                f"<div class='card c6'><h3>Result per trade (R) · distribution</h3>{hist(sc.net_r.values)}</div>"
                f"<div class='card c6'><h3>By setup type</h3>{by_type(base)}</div><div class='card c6'><h3>By pair</h3>{group_table(sc2, 'symbol', 'Pair')}</div>"
                f"<div class='card c6'><h3>By weekday</h3>{group_table(sc2, 'weekday', 'Day')}</div><div class='card c6'><h3>Exits</h3>{funnel(base)}</div></div>")
    curves = [(n, c, balance_series(d)[0]) for (n, d), c in zip(sorted(res.items()), ("--s2", "--s1"))]
    curves = [x for x in curves if len(x[2]) > 2]
    acct = (line_chart(curves, "£", pre="£", suf="", base=START) if curves else "<p class='muted'>No backtest files found.</p>")
    # --- system
    sysc = "<p class='muted'>No live cycles recorded yet. This panel fills in once the live loop runs. It is never filled with made-up numbers.</p>"
    if dbc:
        cy = dbc.execute("SELECT ts, ok, status, data_age_min FROM cycles ORDER BY ts DESC LIMIT 288").fetchall()[::-1]
        if cy:
            colr = {"OK": TOK["GOOD"], "CLOSED": "#4a4a46", "STALE": TOK["WARN"], "ERROR": TOK["CRIT"]}
            sq = "".join(f"<i style='background:{colr.get(r['status'], '#4a4a46')}' title='{r['ts'][5:16]} {r['status']}'></i>" for r in cy)
            sess_ok = [r for r in cy if r["status"] != "CLOSED"]
            okp = (sum(r["ok"] for r in sess_ok) / len(sess_ok) * 100) if sess_ok else 100
            lat = dbc.execute("SELECT COUNT(*) n, SUM(late) l, MAX(latency_s) m, AVG(latency_s) a FROM alerts").fetchone()
            from ..audit.run import audit_text
            sysc = ("<p class='warnt'>No external alert if this server dies (healthchecks.io was declined). The numbers below only cover the time the engine was alive; the uptime chip counts missing cycles as failures.</p>"
            f"<div class='kpis'><div class='kpi'><small>Cycle success (24h)</small><b>{okp:.1f}%</b><span>gate A target 99%</span></div>"
                    f"<div class='kpi'><small>Alerts sent</small><b>{lat['n']}</b><span>{lat['l'] or 0} late</span></div>"
                    f"<div class='kpi'><small>Avg alert latency</small><b>{(lat['a'] or 0):.0f}s</b><span>worst {(lat['m'] or 0):.0f}s</span></div></div>"
                    f"<div class='legend'><span><i style='background:{TOK['GOOD']}'></i>ok</span><span><i style='background:{TOK['WARN']}'></i>stale data</span>"
                    f"<span><i style='background:{TOK['CRIT']}'></i>error</span><span><i style='background:#4a4a46'></i>market closed</span></div><div class='cyc'>{sq}</div>"
                    f"<pre class='mono muted' style='white-space:pre-wrap'>{e(audit_text(dbc, now))}</pre>")
    for sym in PAIRS:
        m5k = store.load(sym, "M5", root, tail=6000)
        levels.setdefault(sym, [])
        levels[sym] = key_levels(m5k) + levels[sym]
    ptable = pair_table(root, cands, levels)
    trades = trades_data(dbc, root, now) if dbc else []
    tcards = "".join(trade_card(i, t, now) for i, t in enumerate(trades)) or (
        "<div class='empty'><b>No trades right now.</b><br><span class='muted'>The engine scans every hour while the market is open and publishes a setup only when a "
        "frozen rule fires. Nothing is a valid outcome.</span></div>")
    n_open = sum(t["state"] == "OPEN" for t in trades); n_pend = sum(t["state"] == "PENDING" for t in trades)
    tcount = f"{n_open} open · {n_pend} waiting for entry · {sum(t['closed'] for t in trades)} recently closed"
    tr_json = json.dumps([{k: t[k] for k in ("pair", "tf", "state", "entry", "stop", "target", "fill", "fill_ts", "created", "price", "dir")} for t in trades])
    cd = json.dumps(candle_data(root)).replace("</", "<\\/")
    page = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>FX Engine</title><style>{CSS}</style></head><body><div class='wrap'>{banner}
<div class='top'><span class='brand'>FX ENGINE</span><span class='pill {state}'>{icon} {label}</span><span class='chip'>data age {'n/a' if age is None else f'{age:.0f} min'}</span><span class='chip'>uptime {uptime}</span><span class='chip'>next cycle {next_cycle}</span><span class='chip'>RESEARCH ONLY · NO ORDERS</span>
<span class='sp'></span><span class='mono muted'>{now:%a %d %b %Y %H:%M} UTC</span></div>
<div class='tabs'><button data-t='overview'>Trades</button><button data-t='charts'>Charts</button><button data-t='market'>Market</button><button data-t='research'>Research</button><button data-t='performance'>Performance</button><button data-t='journal'>Journal</button><button data-t='system'>System</button></div>
<div class='tab' id='overview'><div class='grid' style='margin-bottom:6px'>{livehtml}</div><h2 class='sec'>Your trades<small>{tcount}</small></h2><div class='trades'>{tcards}</div><div class='card' style='margin-top:16px'><h3>History · every published setup, scored as a hypothetical</h3>{livetbl}</div></div>
<div class='tab' id='market'><div class='kpis'>{kpis}</div>
<div class='verdict'><b>Research verdict: no edge found.</b> {n_strats} strategy/timeframe combinations, {trials} logged tests, {n_pass} passed. {'The M5-resolution rerun (R0) is below.' if m5rows else 'The M5-resolution rerun (R0) has not been run yet, so the four H4 verdicts rest on 4h-bar scoring only.'} Candidates are UNPROVEN and research only.</div>
<div class='grid'><div class='card c7'><h3>Account balance if every backtest setup was taken · start £{START:,.0f}, £{RISK:.0f} risk each</h3>{acct}</div>
<div class='card c5'><h3>Currency strength · 5-day momentum</h3>{heat(strength(root))}</div>

<div class='card c6'><h3>Sessions &amp; typical volatility by hour (UTC)</h3>{sessions(vol_by_hour(root))}</div>
<div class='card c6'><h3>Reality check</h3><p>Broker risk warnings in the UK and EU typically show <b>about 70–80%</b> of retail CFD and forex accounts losing money (roughly 50–90% by broker). Independent evidence that AI tools raise retail profitability is thin; the positive claims are vendor-reported. What holds up: costs matter, over-trading hurts, untested rules usually fail. This engine measures all three.</p></div></div></div>
<div class='tab' id='research'><div class='grid'>
<div class='card c12'><h3>Every strategy tested · 2023-11 to 2026-05 · stressed costs · last 6 months held back untouched</h3>
<table class='tbl'><tr><th>Strategy</th><th>Timeframe</th><th class='r'>Trades</th><th class='r'>Win</th><th class='r'>Net R / trade</th><th class='r'>Penalised low</th><th>Verdict</th></tr>{rtab or "<tr><td colspan='7' class='muted'>No result files found on this machine.</td></tr>"}</table>
<div class='card c12'><h3>M5-resolution results · R0 (original seven rules) and batch 3 (E6 daily momentum, E7 carry) · three cost models · random-entry challenger</h3>
<table class='tbl'><tr><th>Variant</th><th>Costs</th><th class='r'>Trades</th><th class='r'>Pair-days</th><th class='r'>Win</th><th class='r'>Net R</th><th class='r'>Penalised low</th><th class='r'>MDE</th><th class='r'>Challenger p95 / real pct</th><th>Verdict</th></tr>{m5tab or "<tr><td colspan='10' class='muted'>Not run yet: PYTHONPATH=src .venv/bin/python -m fxengine.backtest.run_m5 on the VM.</td></tr>"}</table>
<p class='muted'>MDE = the smallest real edge this sample could have detected. "No edge" means "no edge above the MDE". Challenger = the same stop/target rules at random times; a strategy must beat its 95th percentile.</p></div>
<p class='muted'>R = one planned stop distance (your £{RISK:.0f}). Penalised low = lower end of the 95% range after the multiple-testing penalty ({trials} tests). A strategy passes only if that number is above zero, with at least 100 trades, positive in at least 3 calendar years and not carried by one pair.</p></div>
<div class='card c6'><h3>What each strategy does</h3><table class='tbl'>{strat}</table></div>
<div class='card c6'><h3>Technical analysis tested</h3><table class='tbl'><tr><th>Indicator / idea</th><th>Used in</th><th>Status</th></tr>{ta}</table></div>
<div class='card c12'><h3>How the testing works</h3><p>• Real bid and ask prices from OANDA practice, 10 pairs, 3 years. • Candle close = open + timeframe, so no peeking at unfinished candles (unit-tested). • Costs: spread ×2, commission, slippage on stop fills, overnight swap. • Stop wins if stop and target are both touched in one candle. • Rules were fixed and written down before each run; nothing was tuned. • The last six months of data are sealed and have never been opened. • Every variant is counted, and the penalty grows with the number of tests.</p></div></div></div>
<div class='tab' id='charts'><div class='grid'><div class='card c12'><h3>All pairs at a glance</h3>{ptable}</div><div class='card c12'><h3>Chart · bid prices</h3><div class='sel' id='psel'></div><div class='sel' id='tsel'></div><div class='sel' id='nsel'></div><div class='sel' id='osel'></div><div id='cv'></div></div></div></div>
<div class='tab' id='performance'>{perf}</div>
<div class='tab' id='journal'><div class='card'><h3>Your paper trades · behaviour &amp; discipline</h3>{J.panel(jr)}</div></div>
<div class='tab' id='system'><div class='card'><h3>Reliability · live cycles, freshness, alert latency, audit</h3>{sysc}</div></div>
</div><script type='application/json' id='cd'>{cd}</script><script type='application/json' id='lv'>{json.dumps(levels)}</script><script type='application/json' id='tr'>{tr_json}</script>{JS}</body></html>"""
    if out is None:
        return page
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(page)
    return out


if __name__ == "__main__":
    print("wrote", build())
