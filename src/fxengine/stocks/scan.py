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

MAX_PER_RULE = 5
WEAK_AT = -0.02                    # unrealised -2% (price only) while the rule has not invalidated it: flagged WEAKENING


def _levels(rule: str, d: pd.DataFrame, i: int) -> dict:
    """Numbers shown for a setup fired on bar i: strength (for ranking), the invalidation level, and the rule's exit text."""
    c = d["close"]
    if rule == "RSI2_PULLBACK":
        return dict(strength=float(100 - I.rsi(c, 2).iloc[i]), invalidation=float(I.sma(c, 200).iloc[i]), exit_text=f"sell the open after a close above its 5-day average ({I.sma(c, 5).iloc[i]:.2f}); give up after 10 days")
    if rule == "BREAKOUT_20":
        return dict(strength=float(c.iloc[i] / I.prior_high(d["high"], 20).iloc[i] - 1), invalidation=float(I.prior_low(d["low"], 10).iloc[i]), exit_text="sell the open after a close below the 10-day low; give up after 60 days")
    if rule == "TREND_50_200":
        s50, s200 = I.sma(c, 50), I.sma(c, 200)
        return dict(strength=float(s50.iloc[i] / s200.iloc[i] - 1), invalidation=float(s50.iloc[i]), exit_text="sell the open after a close below the 50-day average; give up after 250 days")
    return dict(strength=0.0, invalidation=float("nan"), exit_text="hold about a month, then sell the open")


def _month_end(last: pd.Timestamp) -> bool:
    return (last + pd.offsets.BDay(1)).month != last.month


def todays_setups(panel, passed: set[str]) -> list[dict]:
    mom = S.momentum_entries(panel) if _month_end(max(d.index.max() for d in panel.values())) else {}
    out = []
    for rule in ("RSI2_PULLBACK", "BREAKOUT_20", "TREND_50_200", "MOM_12_1"):
        rows = []
        for s, d in panel.items():
            i = len(d) - 1
            if rule == "MOM_12_1":
                fired = bool(mom.get(s, np.zeros(1, bool))[-1]) if s in mom else False
            else:
                sg = S.BAR_RULES[rule](d)
                fired = bool(sg.entry[i])
            if fired and d.index[i] >= max(x.index.max() for x in panel.values()) - pd.Timedelta(days=4):
                lv = _levels(rule, d, i)
                rows.append(dict(id=f"{rule}|{s}|{d.index[i]:%Y-%m-%d}", rule=rule, symbol=s, market=market_of(s), signal_date=f"{d.index[i]:%Y-%m-%d}", close=round(float(d['close'].iloc[i]), 4),
                                 invalidation=None if np.isnan(lv["invalidation"]) else round(lv["invalidation"], 4), strength=round(lv["strength"], 4), exit_text=lv["exit_text"],
                                 proven=rule in passed, status="PENDING"))
        rows.sort(key=lambda r: -r["strength"])
        out += rows[:MAX_PER_RULE]
    return out


def recheck(setup: dict, panel) -> dict:
    """Re-evaluate one stored setup against the newest prices (price-only). Returns the updated setup."""
    d = panel.get(setup["symbol"])
    if d is None:
        return setup
    s = dict(setup)
    sd = pd.Timestamp(s["signal_date"])
    later = d.index[d.index > sd]
    if len(later) == 0:
        s["status"], s["detail"] = "PENDING", "waiting for the next open"
        return s
    e = d.index.get_loc(later[0])
    o, c, last = float(d["open"].iloc[e]), d["close"], len(d) - 1
    held, ret = last - e + 1, float(c.iloc[last] / o - 1)
    s.update(entry_price=round(o, 4), held=held, unrealised=round(ret, 4), last_close=round(float(c.iloc[last]), 4))
    rule = s["rule"]
    exit_now = bool(S.BAR_RULES[rule](d).exit[last]) if rule in S.BAR_RULES else False
    inv = s.get("invalidation")
    max_hold = {"RSI2_PULLBACK": 10, "BREAKOUT_20": 60, "TREND_50_200": 250, "MOM_12_1": 21}[rule]
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


def run(panel, passed: set[str], ledger: list[dict]) -> list[dict]:
    """Update the ledger: re-check all known setups, then add today's new ones (never duplicated)."""
    have = {x["id"] for x in ledger}
    new = [s for s in todays_setups(panel, passed) if s["id"] not in have]
    rows = [recheck(x, panel) for x in ledger] + new
    return rows


def main(path=Path("data/stocks/prices.parquet"), led=Path("data/stocks/setups.json"), res=Path("docs/results/stocks.json"), out=Path("docs/results/stocks_setups.json")):
    panel = load_panel(path)
    passed = {r["rule"] for r in json.loads(res.read_text())["rules"] if r.get("passes")} if res.exists() else set()
    ledger = json.loads(led.read_text()) if led.exists() else []
    rows = run(panel, passed, ledger)
    rows = [r for r in rows if r["status"] in ("PENDING", "VALID", "WEAKENING", "EXIT SIGNAL") or r["signal_date"] >= (pd.Timestamp.today() - pd.Timedelta(days=14)).strftime("%Y-%m-%d")]
    led.parent.mkdir(parents=True, exist_ok=True)
    led.write_text(json.dumps(rows, indent=1))
    out.parent.mkdir(parents=True, exist_ok=True)
    asof = max(d.index.max() for d in panel.values())
    out.write_text(json.dumps(dict(asof=f"{asof:%Y-%m-%d}", setups=rows), indent=1))
    try:
        from . import dashboard, tab
        dashboard.write(res, out.with_name("stocks.html"), out)
        tab.write(res, out)
    except Exception as e:                      # the dashboard is a convenience: never let it fail the scan
        print("dashboard not refreshed:", type(e).__name__)
    print(f"as of {asof:%Y-%m-%d}: {sum(r['status'] == 'PENDING' for r in rows)} new, {sum(r['status'] in ('VALID', 'WEAKENING') for r in rows)} open, "
          f"{sum(r['status'] in ('INVALIDATED', 'EXIT SIGNAL', 'TIME STOP') for r in rows)} need attention")
    return rows


if __name__ == "__main__":
    main()
