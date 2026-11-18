"""Company scorecard from the official SEC filings (XBRL company facts already cached on the VM by stocks.events). Deterministic, no model, point-in-time first-reported values.
For each US-reporting company: is revenue growing and speeding up, are earnings and margins improving, is the business making cash, is debt under control, is the share count falling.
Eight yes/no checks -> STRONG / MIXED / WEAK. INFORMATION ONLY: this score has NOT been tested as a predictor yet (it is a pre-registered study for later); it never changes a setup's status or a paper trade.
Usage: PYTHONPATH=src python -m fxengine.stocks.fundamentals  -> docs/results/stocks_fundamentals.json"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from .events import _first_reported, _facts, earnings_8ks, REV_TAGS, EDGAR

EPS_TAGS = ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic")
GP_TAGS = ("GrossProfit",)
OP_TAGS = ("OperatingIncomeLoss",)
NI_TAGS = ("NetIncomeLoss", "ProfitLoss")
CFO_TAGS = ("NetCashProvidedByUsedInOperatingActivities",)
DEBT_TAGS = ("LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations")
CASH_TAGS = ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsAndShortTermInvestments")
SHARES_TAGS = ("WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic")


def _yoy(q: pd.DataFrame, i: int) -> float | None:
    """Value of quarter i vs the same quarter a year earlier."""
    if q.empty or i >= len(q):
        return None
    r = q.iloc[len(q) - 1 - i]
    p = q[(q["end"] - (r["end"] - pd.DateOffset(years=1))).abs() <= pd.Timedelta(days=20)]
    p = p[p["end"] < r["end"]]
    if p.empty:
        return None
    prev = float(p.iloc[-1]["val"])
    return float(r["val"]) / prev - 1 if prev > 0 else None


def _ratio(a: pd.DataFrame, b: pd.DataFrame, i: int = 0) -> float | None:
    """a/b for quarter i back (matched on period end)."""
    if a.empty or b.empty or i >= len(a):
        return None
    r = a.iloc[len(a) - 1 - i]
    m = b[(b["end"] - r["end"]).abs() <= pd.Timedelta(days=5)]
    if m.empty or float(m.iloc[-1]["val"]) == 0:
        return None
    return float(r["val"]) / float(m.iloc[-1]["val"])


def _annual_latest(facts: dict, tags) -> float | None:
    g = (facts.get("facts") or {}).get("us-gaap", {})
    for t in tags:
        if t in g:
            for k in ("USD", "shares"):
                u = [x for x in g[t].get("units", {}).get(k, []) if x.get("form") == "10-K" and x.get("start") and x.get("end") and 330 <= (pd.Timestamp(x["end"]) - pd.Timestamp(x["start"])).days <= 380]
                if u:
                    return float(sorted(u, key=lambda x: x["end"])[-1]["val"])
    return None


def _instant_latest(facts: dict, tags) -> float | None:
    g = (facts.get("facts") or {}).get("us-gaap", {})
    for t in tags:
        if t in g:
            u = [x for x in g[t].get("units", {}).get("USD", []) if x.get("form") in ("10-Q", "10-K") and x.get("end")]
            if u:
                return float(sorted(u, key=lambda x: (x["end"], x.get("filed", "")))[-1]["val"])
    return None


def next_earnings(sub: dict, today=None) -> dict:
    """Expected next earnings date from the company's own filing rhythm: the release a year after the same quarter's last release, else last release + ~91 days. An ESTIMATE (companies confirm dates shortly before)."""
    ds = [pd.Timestamp(e["date"]) for e in earnings_8ks(sub)]
    if not ds:
        return {}
    today = pd.Timestamp(today) if today is not None else pd.Timestamp.today().normalize()
    last = ds[-1]
    cands = [d + pd.Timedelta(days=364) for d in ds if d + pd.Timedelta(days=364) > today]
    nxt = min(cands) if cands else last + pd.Timedelta(days=91)
    while nxt <= today:
        nxt += pd.Timedelta(days=91)
    return dict(last_earnings=f"{last:%Y-%m-%d}", next_earnings=f"{nxt:%Y-%m-%d}", days_to_next=int((nxt - today).days), estimated=True)


def scorecard(symbol: str, facts: dict) -> dict | None:
    rev, eps = _first_reported(_facts(facts, REV_TAGS)), _first_reported(_facts(facts, EPS_TAGS))
    if rev.empty or len(rev) < 5:
        return None
    gp, op, ni = (_first_reported(_facts(facts, t)) for t in (GP_TAGS, OP_TAGS, NI_TAGS))
    sh = _first_reported(_facts(facts, SHARES_TAGS))
    g0, g1 = _yoy(rev, 0), _yoy(rev, 1)
    checks, notes = [], []

    def chk(name, ok, detail):
        checks.append(dict(name=name, ok=ok, detail=detail))

    chk("Revenue growing year on year", None if g0 is None else g0 > 0.02, "n/a" if g0 is None else f"{g0:+.1%} latest quarter")
    chk("Revenue growth speeding up", None if g0 is None or g1 is None else g0 > g1, "n/a" if g0 is None or g1 is None else f"{g0:+.1%} vs {g1:+.1%} the quarter before")
    e0 = _yoy(eps, 0) if not eps.empty else None
    last_eps_pos = (not eps.empty) and float(eps.iloc[-1]["val"]) > 0
    chk("Earnings per share up and positive", None if eps.empty else (last_eps_pos and (e0 is None or e0 > 0)), "n/a" if eps.empty else f"EPS {float(eps.iloc[-1]['val']):.2f}" + ("" if e0 is None else f", {e0:+.0%} year on year"))
    m0, m1 = _ratio(gp, rev, 0), _ratio(gp, rev, 4)
    chk("Gross margin not shrinking", None if m0 is None or m1 is None else m0 >= m1 - 0.005, "n/a" if m0 is None or m1 is None else f"{m0:.1%} now vs {m1:.1%} a year ago")
    o0, o1 = _ratio(op, rev, 0), _ratio(op, rev, 4)
    chk("Operating margin not shrinking", None if o0 is None or o1 is None else o0 >= o1 - 0.005, "n/a" if o0 is None or o1 is None else f"{o0:.1%} now vs {o1:.1%} a year ago")
    cfo, ni_a = _annual_latest(facts, CFO_TAGS), _annual_latest(facts, NI_TAGS)
    chk("Makes cash from operations", None if cfo is None else cfo > 0, "n/a" if cfo is None else f"operating cash flow {cfo / 1e6:,.0f}m (last full year)")
    debt, cash = _instant_latest(facts, DEBT_TAGS), _instant_latest(facts, CASH_TAGS)
    chk("Debt covered by cash flow (under 4 years)", None if debt is None or cfo is None or cfo <= 0 else debt <= 4 * cfo,
        "n/a" if debt is None or cfo is None else f"debt {debt / 1e6:,.0f}m, cash {0 if cash is None else cash / 1e6:,.0f}m")
    s0 = _yoy(sh, 0) if not sh.empty else None
    chk("Share count not rising more than 3%", None if s0 is None else s0 <= 0.03, "n/a" if s0 is None else f"{s0:+.1%} year on year")
    known = [c for c in checks if c["ok"] is not None]
    good = sum(1 for c in known if c["ok"])
    verdict = "NOT ENOUGH DATA" if len(known) < 5 else "STRONG" if good >= len(known) - 1 else "WEAK" if good <= len(known) // 2 - 1 else "MIXED"
    return dict(symbol=symbol, verdict=verdict, passed=good, of=len(known), checks=checks, last_quarter=f"{rev.iloc[-1]['end']:%Y-%m-%d}")


def build(root: Path = Path(".")) -> dict:
    out = {}
    for f in sorted((root / EDGAR).glob("*_facts.json")):
        sym = f.name[:-len("_facts.json")]
        try:
            s = scorecard(sym, json.loads(f.read_text()))
            sf = f.with_name(sym + "_sub.json")
            if s and sf.exists():
                s.update(next_earnings(json.loads(sf.read_text())))
        except Exception:
            s = None
        if s:
            out[sym] = s
    return out


def main(root: Path = Path("."), out: Path = Path("docs/results/stocks_fundamentals.json")):
    res = build(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(note="information only; not yet tested as a predictor", companies=res)))
    from collections import Counter
    print(len(res), "companies", dict(Counter(v["verdict"] for v in res.values())))


if __name__ == "__main__":
    main()
