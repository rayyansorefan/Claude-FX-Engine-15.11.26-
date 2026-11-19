"""Permanent record of EVERY setup the engine ever flagged (like the FX engine's history): one immutable 'created' line when a setup is first seen, then a line each time its status changes, and the finished trade when it closes.
Append-only file data/stocks/history.jsonl (never rewritten, never trimmed: the nightly working ledger drops old open setups, this does not). The merged view is published to docs/results/stocks_history.json for the dashboard's History tab.
Every number is the hypothetical, price-only trade the rules define; the paper-account P&L (GBP, £20 risk = 1R) is joined in when the account actually held that setup."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

LOG = Path("data/stocks/history.jsonl")
OUT = Path("docs/results/stocks_history.json")
CREATED_KEYS = ("id", "rule", "symbol", "market", "home", "signal_date", "close", "invalidation", "exit_text", "why", "proven", "strength", "ctx", "cand_filter", "cand_ok")


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for ln in path.read_text().splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass                                    # a half-written last line must never break the record
    return out


def update(rows: list[dict], log: Path = LOG, now: datetime | None = None) -> int:
    """Append what is new since last time. Idempotent. Returns the number of lines written."""
    now = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M")
    seen: dict[str, dict] = {}
    for e in _read(log):
        s = seen.setdefault(e["id"], dict(created=False, status=None, closed=False, shown=False))
        if e["event"] == "created":
            s["created"] = True
        elif e["event"] == "published":
            s["shown"] = True
        elif e["event"] == "status":
            s["status"] = e["status"]
        elif e["event"] == "closed":
            s["closed"] = True
    new = []
    for r in rows:
        s = seen.get(r["id"], dict(created=False, status=None, closed=False, shown=False))
        if r.get("shown") and not s["shown"]:                       # the strongest few per rule are the ones PUBLISHED to the owner (like the FX engine's <=5 a day); the rest are only tracked
            new.append(dict(event="published", at=now, id=r["id"]))
        if not s["created"]:
            new.append(dict(event="created", at=now, **{k: r.get(k) for k in CREATED_KEYS}))
            s["status"] = "PENDING"
        if r["status"] != s["status"] and r["status"] != "PENDING":
            new.append(dict(event="status", at=now, id=r["id"], status=r["status"], detail=r.get("detail"), unrealised=r.get("unrealised")))
        if r["status"] == "CLOSED" and r.get("closed") and not s["closed"]:
            new.append(dict(event="closed", at=now, id=r["id"], closed=r["closed"]))
    if new:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as f:
            for e in new:
                f.write(json.dumps(e, default=str) + "\n")
    return len(new)


def merged(log: Path = LOG, paper_closed: list[dict] | None = None, paper_open: list[dict] | None = None, limit: int = 3000) -> list[dict]:
    recs: dict[str, dict] = {}
    for e in _read(log):
        if e["event"] == "created":
            recs[e["id"]] = dict({k: e.get(k) for k in CREATED_KEYS if k not in ("ctx", "cand_filter")}, created_at=e["at"], status="PENDING", cand_ok=e.get("cand_ok"))
        elif e["event"] == "published" and e["id"] in recs:
            recs[e["id"]]["shown"] = True
        elif e["id"] in recs:
            if e["event"] == "status":
                recs[e["id"]].update(status=e["status"], detail=e.get("detail"), unrealised=e.get("unrealised"))
            elif e["event"] == "closed":
                recs[e["id"]].update(status="CLOSED", closed=e["closed"])
    pc = {c["id"]: c for c in (paper_closed or [])}
    po = {c["id"]: c for c in (paper_open or [])}
    for i, r in recs.items():
        if i in pc:
            r["paper"] = dict(state="closed", pnl=pc[i]["pnl"], r=pc[i]["r"], cost=pc[i]["cost"], entry_date=pc[i]["entry_date"], exit_date=pc[i]["exit_date"],
                              shares=pc[i].get("shares"), cost_usd=pc[i].get("cost_usd"), entry_px=pc[i].get("entry_px"), exit_px=pc[i].get("exit_px"), stop=pc[i].get("stop"))
        elif i in po:
            r["paper"] = dict(state="open", pnl=po[i]["floating"], cost=po[i]["cost"], entry_date=po[i]["entry_date"], shares=po[i].get("shares"), cost_usd=po[i].get("cost_usd"), entry_px=po[i].get("entry_px"), stop=po[i].get("stop"))
    return sorted(recs.values(), key=lambda r: (r["signal_date"], r["created_at"]), reverse=True)[:limit]


def publish(log: Path = LOG, out: Path = OUT, paper_closed=None, paper_open=None) -> int:
    rows = merged(log, paper_closed, paper_open)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(count=len(rows), setups=rows), default=str))
    return len(rows)


if __name__ == "__main__":
    """Backfill now from the working ledger and the last published account (the nightly scan does this automatically)."""
    led, sp = Path("data/stocks/setups.json"), Path("docs/results/stocks_setups.json")
    rows = json.loads(led.read_text()) if led.exists() else []
    acct = (json.loads(sp.read_text()).get("account") or {}) if sp.exists() else {}
    print("new lines:", update(rows), "| records published:", publish(paper_closed=acct.get("closed"), paper_open=acct.get("positions")))
