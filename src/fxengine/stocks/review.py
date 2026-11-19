"""Post-trade review: for every CLOSED trade, a plain-English, deterministic explanation of WHY it was good or bad, and a running tally of which conditions go with winning vs losing trades (the 'learn from every trade' loop).
Explanation inputs (all known from prices and filings, no model): how the trade moved (worst dip / best run inside the hold), how the market (SPY) did over the same days (own move vs market move), how it ended
(rule's exit / invalid-below level broken / time limit), whether earnings came out during the hold, and the market backdrop on the entry day (trend, volatility, dollar, breadth).
Lessons: per rule, win rate and average gain WITH vs WITHOUT each condition, shown only once a rule has 30+ closed trades and labelled as FORWARD EVIDENCE. Nothing here changes a rule or a trade: any adoption follows the written filter process (candidate -> live evidence -> owner decision).
Output docs/results/stocks_lessons.json; per-trade text is added to the history records."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from . import strategies as S

MIN_LESSON = 30
MIN_CELL = 8


def explain(setup: dict, panel: dict, events: pd.DataFrame | None = None) -> dict | None:
    c = setup.get("closed")
    d = panel.get(setup["symbol"])
    if not c or d is None:
        return None
    ent, ex = pd.Timestamp(c["entry_date"]), pd.Timestamp(c["exit_date"])
    if ent not in d.index or ex not in d.index:
        return None
    ep = float(d.loc[ent, "open"])
    hold = d.loc[ent:ex]
    mae = float(hold["low"].min() / ep - 1)
    mfe = float(hold["high"].max() / ep - 1)
    g = float(c["gross"])
    mk = None
    spy = panel.get("spy.us")
    if spy is not None and ent in spy.index and ex in spy.index and setup["symbol"] != "spy.us":
        mk = float(spy.loc[ex, "open"] / spy.loc[ent, "open"] - 1)
    inv = setup.get("invalidation")
    broke = bool(inv and (hold["close"] < inv).any())
    limit = S.MAX_HOLD.get(setup["rule"])
    reason = "invalid-below level broken" if broke else "time limit reached" if limit and c["bars"] >= limit else "the rule's own exit signal"
    earn = False
    if events is not None and len(events):
        e = events[events["symbol"] == setup["symbol"]]
        earn = bool(((e["announce_date"] >= ent) & (e["announce_date"] <= ex)).any()) if len(e) else False
    ctx = setup.get("ctx") or {}
    tags = []
    won = g > 0
    if won and mk is not None and g - mk > 0.01 and abs(mk) < max(0.01, g * 0.5):
        tags.append("stock-driven")
    elif mk is not None and abs(mk) >= 0.01 and (mk > 0) == won:
        tags.append("market-driven")
    if earn:
        tags.append("earnings-in-hold")
    if broke:
        tags.append("stopped-out")
    if won and not broke and reason == "the rule's own exit signal":
        tags.append("worked-as-designed")
    if not won and mk is not None and mk > 0.01:
        tags.append("lost-despite-rising-market")
    parts = [f"{'WON' if won else 'LOST'} {g:+.1%} in {c['bars']} days; exited by {reason}."]
    parts.append(f"Inside the hold it dipped {mae:+.1%} at worst and ran {mfe:+.1%} at best.")
    if mk is not None:
        rel = g - mk
        parts.append(f"The market (SPY) moved {mk:+.1%} over the same days, so the stock {'beat' if rel > 0 else 'lagged'} it by {abs(rel):.1%}" + (": the result is mostly the stock's own move." if "stock-driven" in tags else ": the result mostly followed the market." if "market-driven" in tags else "."))
    if earn:
        parts.append("Earnings were released during the hold, so the report itself may explain the move.")
    if ctx:
        bits = []
        if ctx.get("spy_vs200") is not None:
            bits.append(f"S&P {ctx['spy_vs200'] * 100:+.0f}% vs its 200-day")
        if ctx.get("vix_z") is not None:
            bits.append("volatility " + ("high" if ctx["vix_z"] > 1 else "low" if ctx["vix_z"] < -1 else "normal"))
        if ctx.get("usd_20d_z") is not None:
            bits.append("dollar " + ("strong" if ctx["usd_20d_z"] > 0.5 else "weak" if ctx["usd_20d_z"] < -0.5 else "steady"))
        if bits:
            parts.append("Backdrop at entry: " + ", ".join(bits) + ".")
    return dict(id=setup["id"], text=" ".join(parts), tags=tags, won=won, gross=g, mae=round(mae, 4), mfe=round(mfe, 4), market=None if mk is None else round(mk, 4), reason=reason, earnings=earn)


CONDITIONS = {
    "market uptrend (S&P above its 200-day)": lambda x: (x.get("spy_vs200") or -1) > 0,
    "market calm (low volatility)": lambda x: x.get("vix_z") is not None and x["vix_z"] < 0,
    "US dollar not surging": lambda x: x.get("usd_20d_z") is not None and x["usd_20d_z"] <= 1.0,
    "broad market healthy (breadth > 50%)": lambda x: (x.get("breadth200") or 0) > 0.5,
    "earnings in the last 10 days": lambda x: x.get("dse") is not None and x["dse"] <= 10,
}


def lessons(rows: list[dict], reviews: dict[str, dict]) -> dict:
    """Per rule: closed trades, then for each condition the win rate / average gain when it held vs when it did not (only with enough trades on both sides)."""
    out = {}
    for rule in sorted({r["rule"] for r in rows if r.get("status") == "CLOSED"}):
        cl = [r for r in rows if r["rule"] == rule and r.get("status") == "CLOSED" and r.get("closed")]
        entry = dict(n=len(cl), enough=len(cl) >= MIN_LESSON, conditions=[])
        if len(cl) >= MIN_LESSON:
            for name, f in CONDITIONS.items():
                a = [r["closed"]["gross"] for r in cl if f(r.get("ctx") or {})]
                b = [r["closed"]["gross"] for r in cl if not f(r.get("ctx") or {})]
                if len(a) >= MIN_CELL and len(b) >= MIN_CELL:
                    entry["conditions"].append(dict(name=name, with_n=len(a), with_mean=round(float(np.mean(a)), 4), with_win=round(float(np.mean(np.array(a) > 0)), 3),
                                                    without_n=len(b), without_mean=round(float(np.mean(b)), 4), without_win=round(float(np.mean(np.array(b) > 0)), 3), edge=round(float(np.mean(a) - np.mean(b)), 4)))
        tg = {}
        for r in cl:
            for t in (reviews.get(r["id"]) or {}).get("tags", []):
                tg.setdefault(t, []).append(r["closed"]["gross"])
        entry["why"] = {t: dict(n=len(v), mean=round(float(np.mean(v)), 4), win=round(float(np.mean(np.array(v) > 0)), 3)) for t, v in tg.items()}
        out[rule] = entry
    return out


def build(rows: list[dict], panel: dict, events=None, out: Path = Path("docs/results/stocks_lessons.json")) -> dict:
    reviews = {}
    for r in rows:
        if r.get("status") == "CLOSED":
            try:
                e = explain(r, panel, events)
            except Exception:
                e = None
            if e:
                reviews[r["id"]] = e
    res = dict(reviews=reviews, lessons=lessons(rows, reviews), note=f"forward evidence only; per-rule lessons appear after {MIN_LESSON} closed trades; nothing here changes a rule or trade")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res))
    return res


if __name__ == "__main__":
    """Rebuild the explanations now from the ledger (the nightly scan does this automatically)."""
    from . import events as EV, scan
    rows = json.loads(Path("data/stocks/setups.json").read_text())
    r = build(rows, scan.load_panel(Path("data/stocks/prices.parquet")), EV.load())
    print(len(r["reviews"]), "closed trades explained;", sum(v["enough"] for v in r["lessons"].values()), "rules with enough trades to compare conditions")
