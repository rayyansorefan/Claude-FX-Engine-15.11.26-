"""After-close scanner + setup tracker (research only: it never places or suggests an order; the owner decides and trades himself).
For each pre-registered swing rule it lists the setups that fired on the LAST bar (to be entered at the NEXT open), ranks them, and re-checks every earlier
setup against the newest prices: VALID / WEAKENING / INVALIDATED / EXIT SIGNAL / TIME STOP. Every setup is labelled UNPROVEN until its rule has passed the research gate.
Usage: PYTHONPATH=src python -m fxengine.stocks.scan   ->  data/stocks/setups.json (+ docs/results/stocks_setups.json for the dashboard)"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from . import indicators as I, strategies as S
from .run import load_panel
from .universe import market as market_of
from . import crossctx as CX, events as EV, filters as FL, universe as U

MAX_PER_RULE = 5
WEAK_AT = -0.02                    # unrealised -2% (price only) while the rule has not invalidated it: flagged WEAKENING


def _levels(rule: str, d: pd.DataFrame, i: int) -> dict:
    """Numbers shown for a setup fired on bar i: strength (for ranking), the invalidation level, the exit level (where the rule says take it), the plain-English why."""
    c = d["close"]
    if rule == "RSI2_PULLBACK":
        rs, s5, s200 = float(I.rsi(c, 2).iloc[i]), float(I.sma(c, 5).iloc[i]), float(I.sma(c, 200).iloc[i])
        return dict(strength=100 - rs, invalidation=s200, exit_level=s5, exit_text=f"sell the open after a close above its 5-day average ({s5:.2f}); give up after 10 days",
                    why=[f"RSI(2) is {rs:.1f}, below the 10 line: a sharp short-term dip.", f"Price {float(c.iloc[i]):.2f} is still above its 200-day average ({s200:.2f}), so the long-term trend is up."])
    if rule == "BREAKOUT_20":
        hh, ll, s50 = float(I.prior_high(d["high"], 20).iloc[i]), float(I.prior_low(d["low"], 10).iloc[i]), float(I.sma(c, 50).iloc[i])
        return dict(strength=float(c.iloc[i] / hh - 1), invalidation=ll, exit_level=None, exit_text="sell the open after a close below the 10-day low; give up after 60 days",
                    why=[f"Closed at a new 20-day high ({hh:.2f} was the old one), {float(c.iloc[i] / hh - 1) * 100:.1f}% above it.", f"Price is above its 50-day average ({s50:.2f})."])
    if rule == "TREND_50_200":
        s50, s200 = float(I.sma(c, 50).iloc[i]), float(I.sma(c, 200).iloc[i])
        return dict(strength=float(s50 / s200 - 1), invalidation=s50, exit_level=None, exit_text="sell the open after a close below the 50-day average; give up after 250 days",
                    why=[f"The 50-day average ({s50:.2f}) just crossed above the 200-day ({s200:.2f}).", "Price is above both: a fresh long-term uptrend."])
    if rule == "MOM_12_1":
        return dict(strength=0.0, invalidation=float("nan"), exit_level=None, exit_text="hold about a month, then sell the open",
                    why=["Top 20% of the universe by 12-month return (skipping the most recent month).", "Month-end momentum: buy the winners, review in a month."])
    from .strategies import INFO, MAX_HOLD
    ll = float(I.prior_low(d["low"], 10).iloc[i]) if i >= 10 else float("nan")
    s50 = float(I.sma(c, 50).iloc[i]) if i >= 50 else float("nan")
    inv = ll if ll == ll and ll < float(c.iloc[i]) else s50 if s50 == s50 and s50 < float(c.iloc[i]) else float("nan")
    name, desc = INFO.get(rule, (rule, ""))
    return dict(strength=0.0, invalidation=inv, exit_level=None, exit_text=f"exit per the rule ({desc}); give up after {MAX_HOLD.get(rule, 20)} days",
                why=[f"{name}: {desc}.", f"Price {float(c.iloc[i]):.2f}; the rule's own exit decides when to sell."])


def _month_end(last: pd.Timestamp) -> bool:
    return (last + pd.offsets.BDay(1)).month != last.month


def _already_in_position(d: pd.DataFrame, sig) -> bool:
    """The research holds ONE position per stock per rule: a signal while that stock's earlier trade is still open is ignored. Mirror that exactly."""
    from . import backtest as B
    c = d["close"].to_numpy(float)
    bad = np.r_[False, np.abs(c[1:] / c[:-1] - 1.0) > B.BAD_MOVE]
    _, open_i = B.swing_trades(d["open"].to_numpy(float), sig, np.r_[0, np.cumsum(bad)], return_open=True)
    return open_i is not None and open_i < len(d) - 1


def todays_setups(panel, passed: set[str], top: int = MAX_PER_RULE, ctx=None, events=None, cands: dict | None = None) -> list[dict]:
    me = _month_end(max(d.index.max() for d in panel.values()))
    cands = FL.load_candidates() if cands is None else cands
    allowed = U.allowed_countries()
    allowed_h = U.allowed_home()
    sfeat: dict = {}
    out = []
    for rule in S.SWING_RULES:
        if rule in S.MONTHLY_RULES and not me:
            continue
        rows = []
        sigs = S.rule_sigs(rule, panel, events)
        for s, d in panel.items():
            if allowed is not None and U.country_code(s) not in allowed:
                continue                                   # a market the owner cannot trade: researched, but never shown or traded
            if allowed_h is not None and U.home_country(s) not in allowed_h:
                continue                                   # company from a country missing from Revolut's own filter (e.g. Japan, China, India)
            i = len(d) - 1
            sg = sigs.get(s)
            fired = bool(sg is not None and sg.entry[i] and not _already_in_position(d, sg))
            if fired and d.index[i] >= max(x.index.max() for x in panel.values()) - pd.Timedelta(days=4):
                lv = _levels(rule, d, i)
                if s not in sfeat:
                    sfeat[s] = FL.stock_features({s: d, **({"spy.us": panel["spy.us"]} if "spy.us" in panel and s != "spy.us" else {})})[s].iloc[-1].to_dict()
                cx = dict(CX.at(ctx, d.index[i]) if ctx is not None else {}, days_since_earnings=EV.days_since_earnings(events, s, d.index[i]))
                fx_ = dict(cx, dse=cx.get("days_since_earnings"), **{k: (None if v != v else round(float(v), 4)) for k, v in sfeat[s].items()})
                cand = cands.get(rule)
                rows.append(dict(id=f"{rule}|{s}|{d.index[i]:%Y-%m-%d}", rule=rule, symbol=s, market=market_of(s), home=U.home_country(s), signal_date=f"{d.index[i]:%Y-%m-%d}", close=round(float(d['close'].iloc[i]), 4),
                                 invalidation=None if np.isnan(lv["invalidation"]) else round(lv["invalidation"], 4), strength=round(lv["strength"], 4), exit_text=lv["exit_text"],
                                 exit_level=None if lv["exit_level"] is None else round(lv["exit_level"], 4), why=lv["why"],
                                 proven=rule in passed, status="PENDING", ctx=fx_, cand_filter=cand, cand_ok=(FL.passes(cand, fx_) if cand else None)))
        rows.sort(key=lambda r: -r["strength"])
        for k, r in enumerate(rows):              # EVERY signal is tracked (the research traded every signal); only the strongest few are shown to the owner
            r["shown"] = k < top
        out += rows
    return out


def closed_trade(setup: dict, panel, sigs=None) -> dict | None:
    """The finished trade for a tracked setup, produced by the SAME backtest code the research used; None while it is still open."""
    from . import backtest as B
    d = panel.get(setup["symbol"])
    if d is None:
        return None
    rule = setup["rule"]
    sig = (sigs or {}).get(rule, {}).get(setup["symbol"]) if sigs and rule in sigs else (S.BAR_RULES[rule](d) if rule in S.BAR_RULES else S.rule_sigs(rule, panel).get(setup["symbol"]))
    if sig is None:
        return None
    sd = pd.Timestamp(setup["signal_date"])
    later = d.index[d.index > sd]
    if len(later) == 0:
        return None
    tr = B.trades_for(setup["symbol"], d, sig)
    m = tr[tr["entry_date"] == later[0]]
    if m.empty:
        return None
    r = m.iloc[0]
    return dict(gross=round(float(r["gross"]), 5), entry_date=f"{pd.Timestamp(r['entry_date']):%Y-%m-%d}", exit_date=f"{pd.Timestamp(r['exit_date']):%Y-%m-%d}", bars=int(r["bars"]))


def recheck(setup: dict, panel, sigs=None) -> dict:
    """Re-evaluate one stored setup against the newest prices (price-only). Returns the updated setup."""
    d = panel.get(setup["symbol"])
    if d is None:
        return setup
    s = dict(setup)
    if s.get("status") == "CLOSED":
        return s
    sd = pd.Timestamp(s["signal_date"])
    later = d.index[d.index > sd]
    if len(later) == 0:
        s["status"], s["detail"] = "PENDING", "waiting for the next open"
        return s
    e = d.index.get_loc(later[0])
    o, c, last = float(d["open"].iloc[e]), d["close"], len(d) - 1
    held, ret = last - e + 1, float(c.iloc[last] / o - 1)
    s.update(entry_price=round(o, 4), held=held, unrealised=round(ret, 4), last_close=round(float(c.iloc[last]), 4))
    ct = closed_trade(s, panel, sigs)
    if ct:
        s.update(status="CLOSED", detail=f"closed {ct['gross']:+.1%} in {ct['bars']} days", closed=ct)
        return s
    rule = s["rule"]
    sg = ((sigs or {}).get(rule) or {}).get(s["symbol"]) or (S.BAR_RULES[rule](d) if rule in S.BAR_RULES else None)
    exit_now = bool(sg.exit[last]) if sg is not None else False
    inv = s.get("invalidation")
    max_hold = S.MAX_HOLD[rule]
    if inv is not None and rule != "RSI2_PULLBACK" and c.iloc[last] < inv:
        s["status"], s["detail"] = "INVALIDATED", f"closed below {inv:.2f}"
    elif inv is not None and rule == "RSI2_PULLBACK" and c.iloc[last] < inv:
        s["status"], s["detail"] = "INVALIDATED", f"closed below its 200-day average ({inv:.2f}): the uptrend filter failed"
    elif exit_now:
        s["status"], s["detail"] = "EXIT SIGNAL", "the rule's exit condition is met: sell at the next open"
    elif held >= max_hold:
        s["status"], s["detail"] = "TIME STOP", f"held {held} days, the rule's limit"
    elif ret < WEAK_AT:
        s["status"], s["detail"] = "WEAKENING", f"{ret:+.1%} since entry but not yet invalidated"
    else:
        s["status"], s["detail"] = "VALID", f"{ret:+.1%} since entry, day {held}"
    return s


def run(panel, passed: set[str], ledger: list[dict], ctx=None, events=None, cands: dict | None = None) -> list[dict]:
    """Update the ledger: re-check all known setups, then add today's new ones (never duplicated)."""
    ca, ch = U.allowed_countries(), U.allowed_home()
    ok = lambda sym: (ca is None or U.country_code(sym) in ca) and (ch is None or U.home_country(sym) in ch)
    ledger = [x for x in ledger if x.get("status") == "CLOSED" or ok(x["symbol"])]        # setups tracked before a market was excluded are dropped (closed trades stay in the record)
    have = {x["id"] for x in ledger}
    new = [s for s in todays_setups(panel, passed, ctx=ctx, events=events, cands=cands) if s["id"] not in have]
    need = {x["rule"] for x in ledger if x.get("status") != "CLOSED"}
    sigs = {r: S.rule_sigs(r, panel, events) for r in need}
    rows = [recheck(x, panel, sigs) for x in ledger] + new
    return rows


def forward_summary(rows: list[dict], expected: dict[str, float]) -> dict:
    """Live out-of-sample scoreboard per rule from CLOSED tracked trades: count, mean price-only gain, hit rate, and a 95% range once there are 30+."""
    out = {}
    for rule in S.SWING_RULES:
        g = [x["closed"]["gross"] for x in rows if x["rule"] == rule and x.get("status") == "CLOSED"]
        if not g:
            continue
        n, m = len(g), float(np.mean(g))
        lo = hi = None
        if n >= 30:
            sd = float(np.std(g, ddof=1))
            lo, hi = m - 1.96 * sd / n ** 0.5, m + 1.96 * sd / n ** 0.5
        wf = {}
        for tag, sel in (("with", True), ("without", False)):
            gg = [x["closed"]["gross"] for x in rows if x["rule"] == rule and x.get("status") == "CLOSED" and x.get("cand_ok") is sel]
            if gg:
                wf[tag] = dict(n=len(gg), mean=round(float(np.mean(gg)), 5))
        out[rule] = dict(by_filter=wf or None, n=n, mean=round(m, 5), hit_rate=round(float(np.mean(np.array(g) > 0)), 4), lo=None if lo is None else round(lo, 5), hi=None if hi is None else round(hi, 5), expected=expected.get(rule))
    return out


def account_payload(rows: list[dict], panel, passed: set[str], rates, rank: dict | None = None) -> dict:
    """The £2,500 paper account as plain JSON for the dashboard (never raises: a problem here must not stop the scan)."""
    from . import account
    try:
        a = account.simulate(rows, panel, rates, passed, rank=rank)
    except Exception as e:
        return dict(error=type(e).__name__)
    a["curve"] = [list(x) for x in a["curve"]]
    a["closed"], a["skipped"] = a["closed"][-100:], a["skipped"][-60:]
    return a


def main(path=Path("data/stocks/prices.parquet"), led=Path("data/stocks/setups.json"), res=Path("docs/results/stocks.json"), out=Path("docs/results/stocks_setups.json")):
    panel = load_panel(path)
    passed = {r["rule"] for r in json.loads(res.read_text())["rules"] if r.get("passes")} if res.exists() else set()
    ledger = json.loads(led.read_text()) if led.exists() else []
    events = EV.load(Path(path).parent.parent.parent) if Path(path).name == "prices.parquet" else EV.load()
    ctx = CX.build(panel, CX.load_fx(), EV.load_fred())
    try:
        CX.publish(ctx, out.with_name("stocks_context_history.csv"), out.with_name("stocks_context.json"))          # what the FX engine can read
    except Exception as e:
        print("context not published:", type(e).__name__)
    rows = run(panel, passed, ledger, ctx, events)
    cut = (pd.Timestamp.today() - pd.Timedelta(days=45)).strftime("%Y-%m-%d")
    rows = [r for r in rows if r["status"] in ("PENDING", "VALID", "WEAKENING", "EXIT SIGNAL", "CLOSED") or r["signal_date"] >= cut]       # closed trades are kept: they are the forward test
    led.parent.mkdir(parents=True, exist_ok=True)
    led.write_text(json.dumps(rows, indent=1))
    from . import history as HI
    try:
        HI.update(rows, led.parent / "history.jsonl")
    except Exception as e:
        print("history not updated:", type(e).__name__)
    out.parent.mkdir(parents=True, exist_ok=True)
    asof = max(d.index.max() for d in panel.values())
    expected = {r["rule"]: r["roi"] for r in json.loads(res.read_text())["rules"] if "roi" in r} if res.exists() else {}
    shown = [r for r in rows if r.get("shown", True) or r["status"] == "CLOSED"]
    closed = [dict(rule=r["rule"], symbol=r["symbol"], market=r["market"], signal_date=r["signal_date"], **r["closed"]) for r in rows if r["status"] == "CLOSED"][-300:]
    from . import account
    acct = account_payload(rows, panel, passed, account.load_rates(), expected)
    try:
        from . import review as RV
        RV.build(rows, panel, events, out.with_name("stocks_lessons.json"))
    except Exception as e:
        print("review not built:", type(e).__name__)
    try:
        HI.publish(led.parent / "history.jsonl", out.with_name("stocks_history.json"), acct.get("closed"), acct.get("positions"))
    except Exception as e:
        print("history not published:", type(e).__name__)
    cov = {}
    for sym in panel:
        c = cov.setdefault(U.country_code(sym), dict(symbols=0, setups=0))
        c["symbols"] += 1
    for r in rows:
        if r["status"] == "PENDING":
            cov.setdefault(U.country_code(r["symbol"]), dict(symbols=0, setups=0))["setups"] += 1
    cov_home: dict = {}
    for sym in panel:
        cov_home.setdefault(U.home_country(sym), dict(symbols=0, setups=0))["symbols"] += 1
    for r in rows:
        if r["status"] == "PENDING":
            cov_home.setdefault(r.get("home") or U.country_code(r["symbol"]), dict(symbols=0, setups=0))["setups"] += 1
    allowed_now = sorted(U.allowed_countries() or [])
    out.write_text(json.dumps(dict(asof=f"{asof:%Y-%m-%d}", coverage=cov, coverage_home=cov_home, allowed=allowed_now, setups=[r for r in rows if r.get("shown", True) and r["status"] != "CLOSED"], forward=forward_summary(rows, expected), closed=closed, account=acct), indent=1))
    try:
        from . import dashboard, tab, market
        market.write(panel, [r for r in rows if r["status"] != "CLOSED"], out.with_name("stocks_market.json"))
        dashboard.write(res, out.with_name("stocks.html"), out)
        tab.write(res, out)
    except Exception as e:                      # the dashboard is a convenience: never let it fail the scan
        print("dashboard not refreshed:", type(e).__name__)
    print(f"as of {asof:%Y-%m-%d}: {sum(r['status'] == 'PENDING' for r in rows)} new, {sum(r['status'] in ('VALID', 'WEAKENING') for r in rows)} open, "
          f"{sum(r['status'] in ('INVALIDATED', 'EXIT SIGNAL', 'TIME STOP') for r in rows)} need attention, {sum(r['status'] == 'CLOSED' for r in rows)} closed (forward test)")
    return rows


if __name__ == "__main__":
    main()
