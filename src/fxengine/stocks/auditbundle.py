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
    # day by day: is today better or worse than the days before? (all published setups at 20 GBP risk per R, by the day each trade FINISHED; one day is noise, so the comparison is shown with the spread)
    drows = c.execute("SELECT substr(resolved_at,1,10) d, COUNT(*) n, SUM(net_r > 0) w, SUM(net_r) r FROM outcomes WHERE reason IN ('TARGET','STOP','TIMEOUT') AND net_r IS NOT NULL AND resolved_at IS NOT NULL GROUP BY d ORDER BY d").fetchall()
    if drows:
        L.append("- results by the day each trade finished (trades, won, total R, GBP at 20 risk per R):")
        for r in drows[-14:]:
            L.append(f"    {r['d']}: {r['n']} trades, {int(r['w'] or 0)} won, {r['r']:+.2f}R, {r['r'] * 20:+.0f} GBP")
        if len(drows) >= 3:
            last, prior = drows[-1], drows[:-1]
            pr = [x["r"] for x in prior]
            sd = statistics.stdev(pr) if len(pr) > 1 else 0.0
            L.append(f"  latest day {last['d']}: {last['r']:+.2f}R; the {len(prior)} days before: average {statistics.mean(pr):+.2f}R per day (typical swing +/-{sd:.2f}R), best {max(pr):+.2f}R, worst {min(pr):+.2f}R. "
                     + ("Inside the normal day-to-day swing: not a real change." if abs(last["r"] - statistics.mean(pr)) <= 2 * sd else "Outside the usual swing, but still one day."))
    # where are the wins and losses coming from? per strategy and per pair, with a plain verdict (needs enough trades before anything is concluded)
    import math
    rows = c.execute("SELECT s.type, s.pair, o.net_r FROM outcomes o JOIN setups s USING(run_id) WHERE o.reason IN ('TARGET','STOP','TIMEOUT') AND o.net_r IS NOT NULL").fetchall()

    def verdict(rs):
        n = len(rs)
        if n < 10:
            return "too few to judge"
        m = statistics.mean(rs); se = statistics.stdev(rs) / math.sqrt(n)
        return "EDGE (range above 0)" if m - 1.96 * se > 0 else "LOSING (range below 0)" if m + 1.96 * se < 0 else "no verdict (range spans 0)"
    for label, key in (("strategy", 0), ("pair", 1)):
        groups = collections.defaultdict(list)
        for r in rows:
            groups[r[key]].append(float(r[2]))
        L.append(f"- by {label} (trades, win rate, mean R, verdict; 60 trades are needed before the engine may change anything):")
        for k, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            L.append(f"    {k}: n={len(rs)}, win {sum(x > 0 for x in rs) / len(rs):.0%}, mean {statistics.mean(rs):+.2f}R, total {sum(rs):+.1f}R, {verdict(rs)}")
    cy = c.execute("SELECT status, COUNT(*) n FROM cycles GROUP BY status").fetchall()
    L.append("- loop cycles by status: " + ", ".join(f"{r['status']}:{r['n']}" for r in cy))
    # failure timeline: scattered or consecutive? recovered or not?
    cyc = c.execute("SELECT ts, ok, status, note FROM cycles ORDER BY ts").fetchall()
    fails = [r for r in cyc if r["ok"] == 0]
    if fails:
        perday = collections.Counter(r["ts"][:10] for r in fails)
        streak = best = 0
        for r in cyc:
            streak = streak + 1 if r["ok"] == 0 else 0
            best = max(best, streak)
        last_ok = max((r["ts"] for r in cyc if r["ok"] == 1), default=None)
        causes = collections.Counter(("401 (login rejected)" if "401" in str(r["note"]) else str(r["note"])[:50]) for r in fails)
        L.append(f"- failed cycles: {len(fails)} of {len(cyc)}; per day: {dict(perday)}; longest consecutive run: {best}; last successful cycle: {last_ok}; causes: {dict(causes)}")
        L.append("  (an owner alert is sent at the FIRST 401, otherwise after 3 failures in a row)")
    else:
        L.append(f"- failed cycles: 0 of {len(cyc)}")
    al = c.execute("SELECT kind, COUNT(*) n, SUM(late) late, SUM(1-ok) failed FROM alerts GROUP BY kind").fetchall()
    L.append("- alerts by kind (count / late / failed to send): " + ", ".join(f"{r['kind']}:{r['n']}/{r['late']}/{r['failed']}" for r in al))
    dup = c.execute("SELECT run_id, kind, COUNT(*) k, GROUP_CONCAT(idx) idxs, GROUP_CONCAT(substr(sent_at,1,16), ' | ') times FROM alerts WHERE kind IN ('NEW','TRIGGERED') GROUP BY run_id, kind HAVING k > 1").fetchall()
    L.append(f"- (setup, kind) pairs alerted more than once, NEW/TRIGGERED: {len(dup)} (must be 0; before the fix of 22 Nov history can contain some)")
    for r in dup[:10]:
        L.append(f"    {r['run_id']} {r['kind']} x{r['k']} event numbers [{r['idxs']}] sent at {r['times']}")
        ev = c.execute("SELECT idx, ts, frm, to_state FROM events WHERE run_id=? ORDER BY idx", (r["run_id"],)).fetchall()
        L.append("      events: " + "; ".join(f"{e['idx']}:{e['frm']}->{e['to_state']}@{str(e['ts'])[:16]}" for e in ev[:12]))
    sup = c.execute("SELECT COUNT(*) FROM alerts WHERE kind LIKE 'SUPPRESSED-%'").fetchone()[0]
    L.append(f"- duplicates suppressed by the one-alert-per-kind rule since it was deployed: {sup} (any value above 0 means a replay shifted event numbers: investigate)")
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
        cost, value = sum(p["cost"] for p in pos), sum(p["value"] for p in pos)
        bal = float(t.get("balance") or 0)
        L.append(f"- positions: cost £{cost:,.0f}, current value £{value:,.0f}; balance £{bal:,.0f} => cash £{bal - value:,.0f} (NO LEVERAGE means cash >= 0; cost above balance is just an unrealised loss); largest position cost £{max([p['cost'] for p in pos] or [0]):,.0f} (cap £625)")
        L.append("- cash check: " + ("OK" if bal - value >= -0.5 else "VIOLATION: cash below zero"))
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
    try:
        j = subprocess.run("journalctl -u stocksnightly -u stockslive --since '14 days ago' --no-pager -q 2>/dev/null | grep -ciE 'oom|killed|memory cgroup'", shell=True, capture_output=True, text=True, timeout=30).stdout.strip()
        L.append(f"- memory kills / OOM lines in the Stocks job journals (14 days): {j or 'n/a'} (the nightly job is limited to 350 MB)")
    except Exception:
        L.append("- memory kills: n/a (journal not readable)")
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
