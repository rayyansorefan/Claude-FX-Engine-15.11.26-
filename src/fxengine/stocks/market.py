"""Market context, charts and system health for the Stocks dashboard, computed from the price panel (deterministic, descriptive only: nothing here predicts).
Writes docs/results/stocks_market.json. Called by the nightly scan."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path
import numpy as np
import pandas as pd
from . import indicators as I
from .universe import kind as kind_of

SECTORS = {"xlk.us": "Technology", "xlf.us": "Financials", "xle.us": "Energy", "xlv.us": "Health care", "xly.us": "Consumer discretionary", "xlp.us": "Consumer staples",
           "xli.us": "Industrials", "xlu.us": "Utilities", "gld.us": "Gold", "tlt.us": "Long-term US bonds"}
INDICES = {"spy.us": "S&P 500 (SPY)", "qqq.us": "Nasdaq 100 (QQQ)", "iwm.us": "US small caps (IWM)", "isf.uk": "FTSE 100 (ISF)"}
CHART_BARS = 250


def _ret(c: pd.Series, n: int):
    return float(c.iloc[-1] / c.iloc[-1 - n] - 1) if len(c) > n + 1 else None


def indices(panel) -> list[dict]:
    out = []
    for s, name in INDICES.items():
        d = panel.get(s)
        if d is None or len(d) < 210:
            continue
        c = d["close"]
        s50, s200 = float(I.sma(c, 50).iloc[-1]), float(I.sma(c, 200).iloc[-1])
        out.append(dict(symbol=s, name=name, close=round(float(c.iloc[-1]), 2), vs50=round(float(c.iloc[-1] / s50 - 1), 4), vs200=round(float(c.iloc[-1] / s200 - 1), 4),
                        r1m=_ret(c, 21), r3m=_ret(c, 63), vol20=round(float(c.pct_change().tail(20).std() * np.sqrt(252)), 4), trend="UP" if c.iloc[-1] > s200 and s50 > s200 else "DOWN" if c.iloc[-1] < s200 and s50 < s200 else "MIXED"))
    return out


def breadth(panel) -> dict:
    st = [d for s, d in panel.items() if not kind_of(s).endswith("_etf") and len(d) > 210]
    a50 = sum(d["close"].iloc[-1] > I.sma(d["close"], 50).iloc[-1] for d in st)
    a200 = sum(d["close"].iloc[-1] > I.sma(d["close"], 200).iloc[-1] for d in st)
    hi = sum(d["close"].iloc[-1] >= d["high"].tail(20).max() * 0.999 for d in st)
    lo = sum(d["close"].iloc[-1] <= d["low"].tail(20).min() * 1.001 for d in st)
    n = len(st) or 1
    return dict(n=len(st), above50=round(a50 / n, 3), above200=round(a200 / n, 3), new_highs=int(hi), new_lows=int(lo))


def regime(ix: list[dict], br: dict) -> dict:
    spy = next((x for x in ix if x["symbol"] == "spy.us"), None)
    if not spy:
        return dict(label="UNKNOWN", detail="No SPY data.")
    label = {"UP": "UPTREND", "DOWN": "DOWNTREND", "MIXED": "MIXED"}[spy["trend"]]
    bits = [f"SPY is {spy['vs200'] * 100:+.1f}% vs its 200-day average", f"{br['above200'] * 100:.0f}% of the stocks are above their own 200-day", f"20-day volatility {spy['vol20'] * 100:.0f}% a year"]
    return dict(label=label, detail=" · ".join(bits), calm=bool(spy["vol20"] < 0.20))


def sectors(panel) -> list[dict]:
    out = []
    for s, name in SECTORS.items():
        d = panel.get(s)
        if d is not None and len(d) > 70:
            c = d["close"]
            out.append(dict(symbol=s, name=name, r5=_ret(c, 5), r21=_ret(c, 21), r63=_ret(c, 63)))
    return sorted(out, key=lambda x: -(x["r21"] if x["r21"] is not None else -9))


def movers(panel) -> dict:
    rows = []
    for s, d in panel.items():
        if not kind_of(s).endswith("_etf") and len(d) > 3:
            rows.append((s, float(d["close"].iloc[-1] / d["close"].iloc[-2] - 1)))
    rows.sort(key=lambda x: x[1])
    return dict(down=[dict(symbol=s, r=round(r, 4)) for s, r in rows[:5]], up=[dict(symbol=s, r=round(r, 4)) for s, r in rows[::-1][:5]])


def charts(panel, setups: list[dict], extra=("spy.us", "qqq.us", "iwm.us", "isf.uk")) -> dict:
    syms = []
    for r in setups:
        if r["symbol"] not in syms:
            syms.append(r["symbol"])
    for s in extra:
        if s not in syms:
            syms.append(s)
    out = {}
    for s in syms[:24]:
        d = panel.get(s)
        if d is None or len(d) < 60:
            continue
        c = d["close"]
        t = d.tail(CHART_BARS)
        s50, s200 = I.sma(c, 50).reindex(t.index), I.sma(c, 200).reindex(t.index)
        lv = [dict(kind=("invalidation" if k == "invalidation" else "exit" if k == "exit_level" else "entry"), price=r[k], rule=r["rule"], status=r["status"])
              for r in setups if r["symbol"] == s for k in ("invalidation", "exit_level", "entry_price") if r.get(k)]
        rd = lambda a: [None if x != x else round(float(x), 4) for x in a]
        out[s] = dict(dates=[f"{x:%Y-%m-%d}" for x in t.index], o=rd(t["open"]), h=rd(t["high"]), l=rd(t["low"]), c=rd(t["close"]), s50=rd(s50), s200=rd(s200), levels=lv)
    return out


def system(panel, root: Path = Path(".")) -> dict:
    asof = max(d.index.max() for d in panel.values())
    stale = sorted(s for s, d in panel.items() if (asof - d.index.max()).days > 4)
    q = {}
    qp = root / "data/stocks/quality.json"
    if qp.exists():
        q = json.loads(qp.read_text())
    nl = root / "data/stocks_nightly.log"
    try:
        rev = subprocess.run(["git", "log", "--oneline", "-1"], capture_output=True, text=True, timeout=5, cwd=root).stdout.strip()
    except Exception:
        rev = ""
    reg = root / "docs/stocks_trials.jsonl"
    hl = root / "docs/stocks_holdout_log.txt"
    return dict(asof=f"{asof:%Y-%m-%d}", symbols=len(panel), stale=stale, gaps=q.get("gaps", []), suspicious=[r["symbol"] for r in q.get("symbols", []) if r.get("bad_bars", 0) > 0],
                nightly=nl.read_text().splitlines()[-6:] if nl.exists() else [], code=rev, trials=len(reg.read_text().splitlines()) if reg.exists() else 0,
                holdout=hl.read_text().splitlines() if hl.exists() else [], rows=int(sum(len(d) for d in panel.values())))


def build(panel, setups: list[dict], root: Path = Path(".")) -> dict:
    ix, br = indices(panel), breadth(panel)
    asof = max(d.index.max() for d in panel.values())
    return dict(asof=f"{asof:%Y-%m-%d}", indices=ix, breadth=br, regime=regime(ix, br), sectors=sectors(panel), movers=movers(panel), charts=charts(panel, setups), system=system(panel, root))


def write(panel, setups: list[dict], out: Path = Path("docs/results/stocks_market.json"), root: Path = Path(".")) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(panel, setups, root), default=str))
    return out
