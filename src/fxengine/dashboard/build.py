"""Institutional-style static dashboard: ONE self-contained HTML file (inline SVG, no external calls, no tracking).
Private by construction: it lives on your machine; nothing is uploaded.
PYTHONPATH=src python -m fxengine.dashboard.build   ->  dashboard/index.html   (open it in a browser)"""
from __future__ import annotations
import html as H, json
from pathlib import Path
import numpy as np
import pandas as pd
from ..data import store
from ..engine.costs import pip
from ..research import stats

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"]
TOK = {"S1": "#3987e5", "S2": "#d95926", "GOOD": "#0ca30c", "WARN": "#fab219", "CRIT": "#d03b3b"}


def e(s):
    return H.escape(str(s))


def px(sym, v):
    return f"{float(v):.3f}" if sym.endswith('JPY') else f"{float(v):.5f}"


# ---------- data ----------
def health(root, now):
    m5 = store.load("EURUSD", "M5", root)
    age = None if m5.empty else (now - (m5.index[-1] + pd.Timedelta(minutes=5))).total_seconds() / 60
    dow, hr = now.day_of_week, now.hour
    closed = dow == 5 or (dow == 6 and hr < 22) or (dow == 4 and hr >= 22)
    if age is None:
        return "crit", "NO DATA", age, closed
    if closed:
        return "warn", "MARKET CLOSED", age, closed
    return ("good", "DATA FRESH", age, closed) if age <= 15 else ("crit", "DATA STALE", age, closed)


def strength(root):
    fr = {s: store.load(s, "H4", root).tail(150) for s in PAIRS}
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
        d = store.load(s, "H1", root).tail(24 * 60)
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
    d = store.load(c["pair"], c["tf"], root).tail(48)
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


def line_chart(series, ylabel):
    """series: list of (name, color_var, pd.Series indexed by time). Crosshair tooltip via inline JS."""
    W, Hh, L, B, R = 560, 220, 44, 22, 84
    allv = np.concatenate([s.values for _, _, s in series])
    lo, hi = min(allv.min(), 0), max(allv.max(), 0)
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
        g += f"<line x1='{L}' x2='{W - R + 6}' y1='{y(v):.1f}' y2='{y(v):.1f}' class='grid'/><text x='{L - 6}' y='{y(v) + 3:.1f}' class='ax' text-anchor='end'>{v:.0f}</text>"
        v += step
    g += f"<line x1='{L}' x2='{W - R + 6}' y1='{y(0):.1f}' y2='{y(0):.1f}' class='zero'/>"
    for k in range(4):
        t = t0 + (t1 - t0) * k / 3
        g += f"<text x='{x(t):.1f}' y='{Hh - 6}' class='ax' text-anchor='middle'>{t:%b %y}</text>"
    lines = ""
    for name, col, s in series:
        idx = np.linspace(0, len(s) - 1, min(len(s), 140)).astype(int)
        ss = s.iloc[idx]
        pts = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in ss.items())
        lines += f"<polyline points='{pts}' fill='none' stroke='var({col})' stroke-width='2' stroke-linejoin='round'/>"
        lines += f"<text x='{x(ss.index[-1]) + 6:.1f}' y='{y(ss.iloc[-1]) + 4:.1f}' class='lbl'>{e(name)} {ss.iloc[-1]:.0f}R</text>"
        data.append(dict(n=name, c=col, t=[f"{t:%d %b %Y}" for t in ss.index], v=[round(float(v), 1) for v in ss.values], x=[round(x(t), 1) for t in ss.index]))
    legend = "".join(f"<span><i style='background:var({c})'></i>{e(n)}</span>" for n, c, _ in series)
    return (f"<div class='lc' data-j='{e(json.dumps(data))}'><div class='legend'>{legend}</div>"
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


# ---------- page ----------
CSS = """
:root{--bg:#111110;--card:#1a1a19;--line:#2c2c2a;--ink:#f0efec;--ink2:#c3c2b7;--mute:#8d8c84;--s1:#3987e5;--s2:#d95926;--good:#0ca30c;--warn:#fab219;--crit:#d03b3b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.45 -apple-system,'Inter','Segoe UI',sans-serif}
.wrap{max-width:1320px;margin:0 auto;padding:14px 16px 40px}
.top{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:6px 0 14px;border-bottom:1px solid var(--line)}
.brand{font-weight:700;letter-spacing:.14em;font-size:13px}.chip{border:1px solid var(--line);border-radius:999px;padding:3px 10px;font-size:11px;color:var(--ink2)}
.pill{display:inline-flex;align-items:center;gap:7px;border-radius:999px;padding:4px 12px;font-weight:700;font-size:12px;letter-spacing:.06em;color:#fff}
.pill.good{background:#0a6e0a}.pill.warn{background:#8a5f00}.pill.crit{background:#9c2b2b}
.sp{flex:1}.mono,.num{font-family:ui-monospace,'SF Mono',Menlo,monospace;font-variant-numeric:tabular-nums}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:14px 0}
.kpi,.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.kpi small{color:var(--mute);text-transform:uppercase;letter-spacing:.08em;font-size:10px}.kpi b{display:block;font:600 22px ui-monospace,Menlo,monospace;margin-top:2px}
.kpi span{color:var(--mute);font-size:11px}
.verdict{border:1px solid var(--crit);background:color-mix(in srgb,var(--crit) 12%,var(--card));border-radius:10px;padding:10px 14px;margin:0 0 14px}
h3{margin:0 0 8px;font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--ink2);font-weight:600}
.grid{display:grid;gap:12px;grid-template-columns:repeat(12,1fr)}.c12{grid-column:span 12}.c8{grid-column:span 8}.c7{grid-column:span 7}.c6{grid-column:span 6}.c5{grid-column:span 5}.c4{grid-column:span 4}
@media(max-width:900px){.c8,.c7,.c6,.c5,.c4{grid-column:span 12}}
.setup{display:grid;grid-template-columns:150px minmax(240px,440px) 1fr;gap:12px;align-items:center;padding:10px 0;border-top:1px solid var(--line)}
.setup:first-of-type{border-top:0}.setup .pair{font-weight:700;font-size:15px}
.dir{display:inline-block;padding:1px 8px;border-radius:4px;font-size:11px;font-weight:700;margin-left:6px}.dir.long{background:#0a6e0a;color:#fff}.dir.short{background:#9c2b2b;color:#fff}
.st{border:1px solid var(--line);border-radius:4px;padding:1px 7px;font-size:10px;letter-spacing:.08em;color:var(--ink2)}
.meta{color:var(--mute);font-size:11px;margin-top:4px}.warnt{color:var(--warn);font-weight:600}
@media(max-width:700px){.setup{grid-template-columns:1fr}}
.mini{width:100%;height:96px;display:block;background:color-mix(in srgb,var(--bg) 60%,var(--card));border-radius:6px}.spark{width:100%;height:24px}
.chart{width:100%;display:block}.ax{fill:var(--ink2);font-size:10px}.bt{fill:#fff;font-size:9px;font-weight:700;letter-spacing:.06em}.lbl{fill:var(--ink2);font-size:11px;font-weight:600}.grid{stroke:var(--line)}
svg .grid{stroke:var(--line);stroke-width:1}.zero{stroke:var(--mute);stroke-width:1}
.legend{display:flex;gap:14px;margin-bottom:4px;color:var(--ink2);font-size:11px}.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
.lc{position:relative}.cross{stroke:var(--mute);stroke-width:1;display:none}.tip{position:absolute;display:none;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:6px 9px;font-size:11px;pointer-events:none;white-space:nowrap;top:22px}
.heat{border-collapse:separate;border-spacing:2px;width:100%}.heat th{width:42px;text-align:left;color:var(--ink2);font-size:11px}.heat td{height:18px;border-radius:2px}.heat td.num{width:62px;background:none;text-align:right;font-size:11px}
.scale{display:flex;align-items:center;gap:8px;color:var(--mute);font-size:10px;margin-top:6px}.scale i{flex:1;height:5px;border-radius:3px;background:linear-gradient(90deg,#d03b3b,#383835,#3987e5)}
.up{color:#3fb950}.dn{color:#ec6a5e}.muted{color:var(--mute)}
.frow{display:grid;grid-template-columns:130px 1fr 64px;gap:10px;align-items:center;margin:7px 0}.fbar{height:12px;background:var(--line);border-radius:3px}.fbar b{display:block;height:100%;background:var(--s1);border-radius:3px}.frow em{font:600 12px ui-monospace,Menlo,monospace;text-align:right;font-style:normal}
.split{display:flex;gap:14px;margin:8px 0;color:var(--ink2);font-size:11px;flex-wrap:wrap}
.tbl{width:100%;border-collapse:collapse}.tbl th{color:var(--mute);font-size:10px;text-transform:uppercase;letter-spacing:.06em;text-align:left;padding:4px 6px;border-bottom:1px solid var(--line)}.tbl td{padding:7px 6px;border-bottom:1px solid var(--line)}.tbl td.num,.tbl th.r{text-align:right}.ci{width:160px;height:14px;display:block}
.card{overflow-x:auto}@media(max-width:700px){.ci{width:90px}.tbl td[style]{width:100px!important}.tbl th,.tbl td{padding:6px 3px}}.cyc{display:flex;gap:4px;flex-wrap:wrap;margin:8px 0}.cyc i{width:16px;height:16px;border-radius:3px;border:1px dashed var(--line)}
.sample{background:var(--warn);color:#000;text-align:center;font-weight:700;padding:6px;border-radius:6px;margin-bottom:10px}
"""

JS = """<script>
document.querySelectorAll('.lc').forEach(function(el){var d=JSON.parse(el.dataset.j),svg=el.querySelector('svg'),cr=el.querySelector('.cross'),tp=el.querySelector('.tip');
svg.addEventListener('mousemove',function(ev){var r=svg.getBoundingClientRect(),px=(ev.clientX-r.left)/r.width*560,best=0,bd=1e9;d[0].x.forEach(function(x,i){var q=Math.abs(x-px);if(q<bd){bd=q;best=i}});
cr.setAttribute('x1',d[0].x[best]);cr.setAttribute('x2',d[0].x[best]);cr.style.display='block';
tp.innerHTML='<b>'+d[0].t[best]+'</b><br>'+d.map(function(s){var i=Math.round(best/(d[0].x.length-1)*(s.v.length-1));return s.n+': '+s.v[i]+'R'}).join('<br>');
tp.style.display='block';tp.style.left=Math.min(ev.clientX-r.left+12,r.width-150)+'px'});
svg.addEventListener('mouseleave',function(){cr.style.display='none';tp.style.display='none'})});
</script>"""


def build(root="data/candles", out="dashboard/index.html", now=None, banner=""):
    root = Path(root)
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    state, label, age, closed = health(root, now)
    scan = json.load(open("data/latest_scan.json")) if Path("data/latest_scan.json").exists() else {}
    cands = scan.get("candidates", [])
    trials = sum(1 for _ in open("docs/trials.jsonl")) if Path("docs/trials.jsonl").exists() else 0
    res = research()
    base = res.get("H1") if res.get("H1") is not None else (next(iter(res.values())) if res else None)
    sc = base[base.triggered] if base is not None else None
    icon = {"good": "●", "warn": "◐", "crit": "▲"}[state]
    kp = [("Data age", "n/a" if age is None else f"{age:.0f} min", "limit 15 min in session"),
          ("Next cycle", "—", "live loop not running yet"),
          ("Setups today", f"{len(cands)} / 5", "cap 5 · none is valid"),
          ("Backtest net R / trade", "n/a" if sc is None else f"{sc.net_r.mean():+.2f}R", "stressed costs, H1" if sc is not None else ""),
          ("Tests run", str(trials), "multiple-testing penalty applied")]
    kpis = "".join(f"<div class='kpi'><small>{a}</small><b>{b}</b><span>{c}</span></div>" for a, b, c in kp)
    setups = ""
    for c in cands:
        left = max(0, (pd.Timestamp(c["expires"]) - now).total_seconds() / 3600)
        setups += (f"<div class='setup'><div><span class='pair'>{c['pair']}</span><span class='dir {c['direction']}'>{c['direction'].upper()}</span>"
                   f"<div class='meta'><span class='st'>PENDING</span> {e(c['type'])} · {c['tf']}</div></div>{mini_chart(c, root)}"
                   f"<div class='mono'>entry {px(c['pair'], c['entry'])}<br>stop {px(c['pair'], c['stop'])} <span class='muted'>({c['stop_pips']}p)</span><br>target {px(c['pair'], c['target'])}"
                   f"<div class='meta'>{c['lots_for_20gbp_risk']} lots = £20 · {left:.1f}h left · score {c['score']}<br><span class='warnt'>UNPROVEN</span></div></div></div>")
    if not setups:
        setups = "<p class='muted' style='padding:18px 0'><b style='color:var(--ink)'>No setups right now.</b> That is a valid outcome. The scan runs when the market is open.</p>"
    curves = [(n, c, d[d.triggered].sort_values("created").set_index("created").net_r.cumsum())
              for (n, d), c in zip(sorted(res.items()), ("--s2", "--s1"))]
    curves = [x for x in curves if len(x[2]) > 2]
    page = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>FX Engine</title><style>{CSS}</style></head><body><div class='wrap'>{banner}
<div class='top'><span class='brand'>FX ENGINE</span><span class='pill {state}'>{icon} {label}</span><span class='chip'>RESEARCH ONLY · NO ORDERS</span>
<span class='sp'></span><span class='mono muted'>{now:%a %d %b %Y %H:%M} UTC</span></div>
<div class='kpis'>{kpis}</div>
<div class='verdict'><b>Research verdict: no edge found.</b> Every tested setup rule lost money after stressed costs in backtests. Anything shown below is UNPROVEN and for research only.</div>
<div class='grid'>
<div class='card c12'><h3>Today's setups</h3>{setups}</div>
<div class='card c7'><h3>Currency strength · 5-day momentum, last 24 four-hour bars</h3>{heat(strength(root))}</div>
<div class='card c5'><h3>Sessions &amp; typical volatility by hour (UTC)</h3>{sessions(vol_by_hour(root))}</div>
<div class='card c7'><h3>Cumulative hypothetical R after stressed costs · backtest</h3>{line_chart(curves, 'R') if curves else "<p class='muted'>No backtest files found.</p>"}</div>
<div class='card c5'><h3>Funnel · backtest</h3>{funnel(base) if base is not None else "<p class='muted'>No backtest files found.</p>"}</div>
<div class='card c7'><h3>Results by setup type · backtest</h3>{by_type(base) if base is not None else "<p class='muted'>No backtest files found.</p>"}</div>
<div class='card c5'><h3>Reliability · live cycles &amp; data freshness</h3><div class='cyc'>{"<i></i>" * 24}</div>
<p class='muted'>No live cycles recorded yet. This panel fills in once the live loop runs. It is never filled with made-up numbers.</p></div>
</div></div>{JS}</body></html>"""
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(page)
    return out


if __name__ == "__main__":
    print("wrote", build())
