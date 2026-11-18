"""The shared layer: ONE combined picture of the FX engine and the Stocks engine, so they work in unison instead of as silos.
It only READS the FX engine's own ledger (SQLite opened read-only) or, if the FX engine provides it, its context file (docs/results/fx_context.json); it never writes
to or changes anything in the FX engine. Both engines keep their own £2,500 paper account (so each rule set is judged on its own); this layer adds what only a joint view can:
total paper equity, total open risk against one shared risk budget, and net exposure by currency across BOTH engines (a long USD stock and a short USDCAD FX trade are the same bet).
Research only: advisory numbers, never orders."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path

FX_START = 2500.0
FX_RISK = 20.0
RISK_BUDGET = 100.0                    # advisory: total open risk across BOTH engines (5 trades at £20)
CCY = {"us": "USD", "uk": "GBP"}


def _ro(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def _direction(rec: dict) -> str:
    d = str(rec.get("dir") or rec.get("direction") or "").lower()
    if d in ("long", "short"):
        return d
    try:
        return "long" if float(rec["entry"]) > float(rec["stop"]) else "short"      # a long's stop is below its entry
    except (KeyError, TypeError, ValueError):
        return "long"


def fx_snapshot(root: Path = Path.home() / "fx") -> dict | None:
    """FX engine state from its ledger. None if the ledger cannot be read (then the combined view says so honestly)."""
    ctx = root / "docs/results/fx_context.json"
    if ctx.exists():                                   # preferred: a contract file the FX engine writes itself
        try:
            return dict(json.loads(ctx.read_text()), source="fx_context.json")
        except (OSError, ValueError):
            pass
    db = root / "data/engine.db"
    if not db.exists():
        return None
    try:
        c = _ro(db)
        out = c.execute("SELECT COALESCE(SUM(net_r),0) s, COUNT(*) n, COALESCE(SUM(net_r>0),0) w FROM outcomes").fetchone()
        open_rows = c.execute("SELECT run_id, pair, record FROM setups WHERE run_id NOT IN (SELECT run_id FROM outcomes) ORDER BY created_at").fetchall()
        last = {r["run_id"]: r["to_state"] for r in c.execute("SELECT run_id, to_state FROM events e WHERE idx=(SELECT MAX(idx) FROM events WHERE run_id=e.run_id)")}
    except sqlite3.Error:
        return None
    pos, pend = [], []
    for r in open_rows:
        rec = json.loads(r["record"])
        st = str(last.get(r["run_id"], "PENDING")).upper()
        row = dict(pair=r["pair"], dir=_direction(rec), state=st, risk=FX_RISK, type=rec.get("type"))
        (pos if st == "OPEN" else pend if st == "PENDING" else []).append(row)
    realised = float(out["s"]) * FX_RISK
    return dict(source="engine.db", start=FX_START, balance=round(FX_START + realised, 2), realised=round(realised, 2), n_closed=int(out["n"]), wins=int(out["w"]),
                open=pos, pending=pend)


def exposure(fx: dict | None, st: dict | None) -> dict:
    """Risk-weighted net exposure by currency (£ of risk, + long / - short that currency) across both engines."""
    e: dict[str, float] = {}
    for t in (fx or {}).get("open", []):
        p = str(t["pair"]).upper()
        if len(p) == 6:
            sign = 1.0 if t["dir"] == "long" else -1.0
            e[p[:3]] = e.get(p[:3], 0.0) + sign * t.get("risk", FX_RISK)
            e[p[3:]] = e.get(p[3:], 0.0) - sign * t.get("risk", FX_RISK)
    for q in (st or {}).get("positions", []):
        c = CCY.get(q["symbol"].rsplit(".", 1)[-1], "USD")
        e[c] = e.get(c, 0.0) + q.get("risk", 20.0)
    return {k: round(v, 2) for k, v in sorted(e.items(), key=lambda kv: -abs(kv[1])) if abs(v) > 1e-9}


def stocks_snapshot(sp: dict | None) -> dict | None:
    a = (sp or {}).get("account")
    if not a or a.get("error"):
        return None
    return dict(start=a["start"], balance=a["balance"], realised=a["tiles"]["alltime"], floating=a["tiles"]["floating"], n_closed=a["tiles"]["wins"] + a["tiles"]["losses"], wins=a["tiles"]["wins"],
                positions=a.get("positions", []), pending=[s for s in (sp or {}).get("setups", []) if s.get("status") == "PENDING"])


def combine(fx: dict | None, st: dict | None) -> dict:
    n_fx, n_st = len((fx or {}).get("open", [])), len((st or {}).get("positions", []))
    open_risk = n_fx * FX_RISK + n_st * 20.0
    ex = exposure(fx, st)
    notes = []
    if open_risk > RISK_BUDGET:
        notes.append(f"Open risk £{open_risk:,.0f} is over the shared £{RISK_BUDGET:,.0f} budget: treat new setups as lower priority until something closes.")
    big = [(c, v) for c, v in ex.items() if abs(v) >= 40]
    for c, v in big:
        notes.append(f"Net {c} exposure is {'long' if v > 0 else 'short'} £{abs(v):,.0f} of risk across both engines: they are leaning the same way on {c}.")
    if fx is None:
        notes.append("The FX engine's ledger could not be read, so the combined view shows Stocks only.")
    if st is None:
        notes.append("The Stocks paper account has no data yet.")
    return dict(fx=fx, stocks=st, total_balance=round((fx or {}).get("balance", 0) + (st or {}).get("balance", 0), 2), total_start=round((fx or {}).get("start", 0) + (st or {}).get("start", 0), 2),
                open_risk=open_risk, risk_budget=RISK_BUDGET, n_fx=n_fx, n_st=n_st, exposure=ex, notes=notes)


def write(sp: dict | None, out: Path = Path("docs/results/shared_context.json"), fx_root: Path = Path.home() / "fx") -> dict:
    s = combine(fx_snapshot(fx_root), stocks_snapshot(sp))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(s, indent=1, default=str))
    return s
