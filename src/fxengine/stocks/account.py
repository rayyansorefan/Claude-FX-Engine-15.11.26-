"""£2,500 PAPER account for the stock setups (hypothetical: nothing is ever ordered), run the way the FX engine runs its own.
Policy, fixed in advance (docs/STOCKS_PLAN.md): the account takes every new setup of a rule that has PASSED the research gate, best-evidenced rule first then strongest signal, ONE position per stock across rules, while cash allows;
risk per trade £20 (1R) sized from the setup's own invalid-below level (no level -> 10% below entry); no position bigger than 25% of the account; no leverage.
Entries and exits use the same dates and prices as the research (next open after the signal; exit at the open after the rule's exit). Deterministic: rebuilt from the
setup ledger every night, so it can never drift. Balances are BEFORE fees (like FX's 'before commission/swap'); the normal-cost estimate is shown separately.
Every market is converted into pounds at that currency's GBP rate of the day; London quotes pence, Johannesburg cents, Tel Aviv agorot."""
from __future__ import annotations
import csv
from pathlib import Path
import numpy as np
import pandas as pd
from . import costs
from .universe import kind as kind_of, currency

from .sizing import START, RISK, MAX_POS, NO_STOP_PCT, MIN_POSITION, stop_for, shares as size_shares
FALLBACK_RATE = 1.30                         # USD per GBP, used (and flagged) only if no rate file is available


def _read_rate_file(path: Path) -> pd.Series:
    if not path.exists():
        return pd.Series(dtype=float)
    r = list(csv.DictReader(path.open()))
    if not r or "Close" not in r[0]:
        return pd.Series(dtype=float)
    return pd.Series({pd.Timestamp(x["Date"]): float(x["Close"]) for x in r if x.get("Close") not in (None, "", "nan")}).sort_index()


def load_rates(raw: Path = Path("data/stocks/raw")) -> dict[str, pd.Series]:
    """Units of each currency per 1 GBP, by date (Yahoo GBP<CUR>=X): {'USD': Series, 'EUR': Series, ...}."""
    out = {"USD": _read_rate_file(raw / "gbpusd.csv")}
    for f in raw.glob("gbp_*.csv"):
        out[f.stem.split("_")[1].upper()] = _read_rate_file(f)
    return {k: v for k, v in out.items() if len(v)}


class Money:
    """Price (in the stock's own quoted units) -> pounds, using the market's currency and the day's GBP rate."""
    def __init__(self, rates):
        self.rates = rates if isinstance(rates, dict) else {"USD": rates}            # a bare Series means USD per GBP
        self.used_fallback = False

    def per_gbp(self, cur: str, d) -> float:
        s = self.rates.get(cur)
        if s is not None and len(s):
            i = s.index.searchsorted(pd.Timestamp(d), side="right") - 1
            if i >= 0:
                return float(s.iloc[i])
        self.used_fallback = True
        return FALLBACK_RATE if cur == "USD" else 1.0

    def gbp(self, sym: str, price: float, d) -> float:
        cur, div = currency(sym)
        major = price / div
        return major if cur == "GBP" else major / self.per_gbp(cur, d)


def _stop(row: dict, entry: float) -> tuple[float, bool]:
    return stop_for(row.get("invalidation"), entry)


def simulate(rows: list[dict], panel: dict, rates, passed: set[str], start: float = START, today=None, rank: dict | None = None) -> dict:
    """Run the paper account over the ledger. `rows`: all tracked setups (open and closed). Returns balance, curve, positions, trades, skips and FX-style tiles."""
    money = Money(rates)
    cand = []
    for r in rows:
        if r["rule"] not in passed or r["symbol"] not in panel:
            continue
        d = panel[r["symbol"]]
        later = d.index[d.index > pd.Timestamp(r["signal_date"])]
        if len(later) == 0:
            continue
        e = later[0]
        ex = None
        if r.get("status") == "CLOSED" and r.get("closed"):
            ex = (pd.Timestamp(r["closed"]["exit_date"]), float(d.loc[e, "open"]) * (1 + r["closed"]["gross"]))
        cand.append(dict(row=r, sym=r["symbol"], entry_date=e, entry_px=float(d.loc[e, "open"]), exit=ex, strength=r.get("strength", 0.0)))
    if not cand:
        return dict(balance=start, start=start, curve=[], positions=[], closed=[], skipped=[], tiles=_tiles([], [], start, start, today), fallback_rate=False)
    rank = rank or {}
    cand.sort(key=lambda c: (c["entry_date"], -rank.get(c["row"]["rule"], 0.0), -c["strength"]))        # same day: the rule with the best research record first, then the strongest signal
    days = sorted({c["entry_date"] for c in cand} | {c["exit"][0] for c in cand if c["exit"]} | set().union(*[set(panel[c["sym"]].index[panel[c["sym"]].index >= cand[0]["entry_date"]]) for c in cand]))
    cash, pos, closed, skipped, curve = start, {}, [], [], []
    by_entry: dict = {}
    for c in cand:
        by_entry.setdefault(c["entry_date"], []).append(c)
    for day in days:
        for pid, p in list(pos.items()):                       # exits at the open
            if p["exit"] and p["exit"][0] == day:
                val = p["shares"] * money.gbp(p["sym"], p["exit"][1], day)
                cash += val
                pnl = val - p["cost"]
                closed.append(dict(id=pid, symbol=p["sym"], rule=p["rule"], entry_date=f"{p['entry_date']:%Y-%m-%d}", exit_date=f"{day:%Y-%m-%d}", cost=round(p["cost"], 2), value=round(val, 2),
                                   pnl=round(pnl, 2), r=round(pnl / RISK, 2), pct=round(val / p["cost"] - 1, 4),
                                   shares=round(p["shares"], 4), entry_px=round(p["entry_px"], 4), exit_px=round(p["exit"][1], 4), stop=round(p["stop"], 4),
                                   cost_usd=round(p["cost"] * money.per_gbp("USD", p["entry_date"]), 2)))
                del pos[pid]
        equity_open = cash + sum(q["shares"] * money.gbp(q["sym"], float(panel[q["sym"]]["close"].asof(day)) if day in panel[q["sym"]].index else q["last"], day) for q in pos.values())
        for c in by_entry.get(day, []):                        # entries at the open, strongest first
            if any(q["sym"] == c["sym"] for q in pos.values()):          # one position per stock, however many rules flag it (no hidden double exposure)
                skipped.append(dict(id=c["row"]["id"], symbol=c["sym"], why="already held through another setup"))
                continue
            ep = c["entry_px"]
            ep_gbp = money.gbp(c["sym"], ep, day)
            stop, nostop = _stop(c["row"], ep)
            sh, why_skip = size_shares(ep_gbp, money.gbp(c["sym"], stop, day), equity_open, cash)
            if why_skip:
                skipped.append(dict(id=c["row"]["id"], symbol=c["sym"], why=why_skip))
                continue
            cost = sh * ep_gbp
            cash -= cost
            pos[c["row"]["id"]] = dict(sym=c["sym"], rule=c["row"]["rule"], shares=sh, cost=cost, entry_date=day, entry_px=ep, exit=c["exit"], stop=stop, nostop=nostop, last=ep)
        mv = 0.0
        for q in pos.values():
            d = panel[q["sym"]]
            if day in d.index:
                q["last"] = float(d.loc[day, "close"])
            mv += q["shares"] * money.gbp(q["sym"], q["last"], day)
        curve.append((f"{day:%Y-%m-%d}", round(cash + mv, 2)))
    last_day = days[-1]
    openp = []
    for pid, q in pos.items():
        v = q["shares"] * money.gbp(q["sym"], q["last"], last_day)
        openp.append(dict(id=pid, symbol=q["sym"], rule=q["rule"], entry_date=f"{q['entry_date']:%Y-%m-%d}", shares=round(q["shares"], 4), cost=round(q["cost"], 2), value=round(v, 2), floating=round(v - q["cost"], 2),
                          stop=round(q["stop"], 4), entry_px=round(q["entry_px"], 4), cost_usd=round(q["cost"] * money.per_gbp("USD", q["entry_date"]), 2), risk=RISK))
    balance = curve[-1][1]
    return dict(balance=balance, start=start, curve=curve, positions=openp, closed=closed, skipped=skipped, tiles=_tiles(closed, openp, balance, start, today or last_day), fallback_rate=money.used_fallback)


def _tiles(closed: list[dict], openp: list[dict], balance: float, start: float, today) -> dict:
    """FX-style tiles: today / this week / this month / all time (realised), open floating, wins-losses."""
    t = pd.Timestamp(today) if today is not None else pd.Timestamp.today()
    sm = t - pd.Timedelta(days=t.weekday())
    mo = t.replace(day=1)
    cd = lambda c: pd.Timestamp(c["exit_date"])
    s = lambda sel: round(sum(c["pnl"] for c in closed if sel(cd(c))), 2)
    w = sum(c["pnl"] > 0 for c in closed)
    return dict(balance=round(balance, 2), today=s(lambda d: d.normalize() == t.normalize()), week=s(lambda d: d >= sm.normalize()), month=s(lambda d: d >= mo.normalize()), alltime=round(sum(c["pnl"] for c in closed), 2),
                floating=round(sum(p["floating"] for p in openp), 2), n_open=len(openp), wins=w, losses=len(closed) - w, start=start)
