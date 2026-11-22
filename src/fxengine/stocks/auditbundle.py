"""One plain-text file with everything an auditor (or the owner) needs to judge how both engines have actually run: counts, results, failures, gaps, alert duplicates, sizing, job health.
No secrets are ever written (no tokens, no IDs, no IP addresses). Read-only. Run on the VM:  PYTHONPATH=src .venv/bin/python -m fxengine.stocks.auditbundle  -> docs/results/audit_bundle.md"""
from __future__ import annotations
import collections
import json
import shutil
import sqlite3
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _git(root: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%h %cs %s"], capture_output=True, text=True, timeout=10).stdout.strip()[:100]
    except Exception:
        return "n/a"


def _tail(p: Path, n: int) -> list[str]:
    try:
        return p.read_text().splitlines()[-n:]
    except OSError:
        return ["(missing)"]


def fx_section(db: Path) -> list[str]:
    L = ["## FX engine (ledger)"]
    if not db.exists():
        return L + ["- ledger not found"]
    c = sqlite3.connect(str(db)); c.row_factory = sqlite3.Row
    n = c.execute("SELECT COUNT(*) FROM setups").fetchone()[0]
    first, last = c.execute("SELECT MIN(created_at), MAX(created_at) FROM setups").fetchone()
    L.append(f"- setups published: {n} ({first} -> {last})")
    outs = c.execute("SELECT reason, net_r FROM outcomes").fetchall()
    by = collections.Counter(r["reason"] for r in outs)
    L.append(f"- outcomes: {dict(by)}")
    rs = [r["net_r"] for r in outs if r["reason"] in ("TARGET", "STOP", "TIMEOUT") and r["net_r"] is not None]
    if rs:
        L.append(f"- resolved trades {len(rs)}: win rate {sum(x > 0 for x in rs) / len(rs):.0%}, mean {statistics.mean(rs):+.3f}R, total {sum(rs):+.2f}R (R = planned stop distance; before commission)")
    day = c.execute("SELECT day, COUNT(*) n FROM setups GROUP BY day ORDER BY day DESC LIMIT 14").fetchall()
    L.append("- setups per day (latest 14): " + ", ".join(f"{r['day']}:{r['n']}" for r in day))
    recs = [json.loads(r[0]) for r in c.execute("SELECT record FROM setups")]
    la = [x for x in recs if x.get("lots_account") is not None]
    L.append(f"- no-leverage sizing recorded on {len(la)} of {n} setups; not affordable (0 lots): {sum(1 for x in la if x['lots_account'] == 0)}; "
             f"max position value £{max([x['lots_account'] * (x.get('per_lot_gbp') or 0) for x in la] or [0]):,.0f} (must never exceed the account)")
    cy = c.execute("SELECT status, COUNT(*) n FROM cycles GROUP BY status").fetchall()
    L.append("- loop cycles by status: " + ", ".join(f"{r['status']}:{r['n']}" for r in cy))
    errs = c.execute("SELECT ts, note FROM cycles WHERE ok=0 ORDER BY ts DESC LIMIT 5").fetchall()
    L.append("- latest failed cycles: " + ("; ".join(f"{r['ts'][:16]} {str(r['note'])[:80]}" for r in errs) or "none"))
    al = c.execute("SELECT kind, COUNT(*) n, SUM(late) late, SUM(1-ok) failed FROM alerts GROUP BY kind").fetchall()
    L.append("- alerts by kind (count / late / failed to send): " + ", ".join(f"{r['kind']}:{r['n']}/{r['late']}/{r['failed']}" for r in al))
    dup = c.execute("SELECT COUNT(*) FROM (SELECT run_id, kind, COUNT(*) k FROM alerts GROUP BY run_id, kind HAVING k > 1 AND kind IN ('NEW','TRIGGERED'))").fetchone()[0]
    L.append(f"- duplicate NEW/TRIGGERED alerts for one setup: {dup} (must be 0)")
    return L


def stocks_section(root: Path) -> list[str]:
    L = ["## Stocks engine"]
    res = root / "docs/results"
    hist = root / "data/stocks/history.jsonl"
    if hist.exists():
        ev = [json.loads(x) for x in hist.read_text().splitlines() if x.strip().startswith("{")]
        cr = [e for e in ev if e["event"] == "created"]
        pub = [e for e in ev if e["event"] == "published"]
        cl = [e["closed"]["gross"] for e in ev if e["event"] == "closed"]
        L.append(f"- history log: {len(cr)} setups tracked, {len(pub)} published to the owner, {len(cl)} closed" + (f"; win rate {sum(g > 0 for g in cl) / len(cl):.0%}, mean {statistics.mean(cl):+.2%} (price only)" if cl else ""))
    sp = res / "stocks_setups.json"
    if sp.exists():
        d = json.loads(sp.read_text()); a = d.get("account") or {}
        t = a.get("tiles") or {}
        L.append(f"- scan as of {d.get('asof')}: paper balance £{t.get('balance')}, open {t.get('n_open')}, closed wins/losses {t.get('wins')}/{t.get('losses')}, skipped for cash {len(a.get('skipped') or [])}")
        pos = a.get("positions") or []
        L.append(f"- money in positions £{sum(p['cost'] for p in pos):,.0f} of the account (must never exceed it); largest position £{max([p['cost'] for p in pos] or [0]):,.0f} (cap £625)")
        L.append("- forward test per rule: " + "; ".join(f"{k}: n={v['n']} mean {v['mean']:+.2%} hit {v['hit_rate']:.0%}" for k, v in (d.get("forward") or {}).items()))
    lv = res / "stocks_live.json"
    if lv.exists():
        d = json.loads(lv.read_text()); p = d.get("plan") or {}
        L.append(f"- live job last wrote {d.get('asof')} UTC: {len(d.get('prices') or {})} prices, {len(d.get('failed') or [])} failed, bought today {len(p.get('entries') or [])}")
    sent = root / "data/stocks/alerts_sent.json"
    if sent.exists():
        keys = json.loads(sent.read_text())
        L.append("- Telegram events sent (by type): " + ", ".join(f"{k}:{v}" for k, v in collections.Counter(x.split("|")[0] for x in keys).items()))
    L.append(f"- health file: {(res / 'stocks_health.json').read_text()[:300] if (res / 'stocks_health.json').exists() else 'missing'}")
    L.append("- nightly log tail:"); L += ["    " + x[:150] for x in _tail(root / "data/stocks_nightly.log", 12)]
    L.append("- auto-update log tail:"); L += ["    " + x[:150] for x in _tail(root / "data/stocks_autoupdate.log", 8)]
    return L


def build(root: Path = Path("."), fx_root: Path | None = None) -> str:
    fx_root = fx_root if fx_root is not None else root.resolve().parent / "fx"
    du, now = shutil.disk_usage(root if root.exists() else Path(".")), datetime.now(timezone.utc)
    L = [f"# Audit bundle · generated {now:%Y-%m-%d %H:%M} UTC (no secrets included)", "",
         f"- code: stocks `{_git(root)}` · FX `{_git(fx_root)}`", f"- disk used {du.used / du.total:.0%}"]
    try:
        mem = [x for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable')][0].split()[1]
        L.append(f"- memory available {int(mem) // 1024} MB")
    except Exception:
        pass
    return "\n".join(L + [""] + fx_section(fx_root / "data/engine.db") + [""] + stocks_section(root)) + "\n"


def main(root: Path = Path("."), out: Path = Path("docs/results/audit_bundle.md")) -> str:
    text = build(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    return text


if __name__ == "__main__":
    print(main())
