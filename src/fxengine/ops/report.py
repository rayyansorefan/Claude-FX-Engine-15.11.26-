"""Compact VM health/data report (no secrets). Runs as the `report` ops job -> data/ops_report.txt is pushed to vm-results.
PYTHONPATH=src python -m fxengine.ops.report"""
from __future__ import annotations
import json, sqlite3, subprocess
from pathlib import Path
import pandas as pd
from ..data import store
from ..live.scan import PAIRS


def lines():
    out = [f"report generated {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC"]
    for s in PAIRS:
        try:
            d = store.load(s, "M5")
            out.append(f"{s} M5: {len(d):,} rows {d.index.min():%Y-%m-%d} -> {d.index.max():%Y-%m-%d %H:%M}" if len(d) else f"{s} M5: EMPTY")
        except Exception as e:
            out.append(f"{s} M5: ERROR {type(e).__name__}")
    p = Path("data/engine.db")
    if p.exists():
        c = sqlite3.connect(p)
        q = lambda sql: c.execute(sql).fetchone()[0]
        out.append(f"cycles total {q('select count(*) from cycles')} ok {q('select coalesce(sum(ok),0) from cycles')} "
                   f"| setups {q('select count(*) from setups')} resolved {q('select count(*) from outcomes')} | alerts {q('select count(*) from alerts')} "
                   f"unsent {q('select count(*) from alerts where ok=0')}")
        last = c.execute("select ts,status,data_age_min,note from cycles order by ts desc limit 3").fetchall()
        out += [f"last cycle: {r}" for r in last]
    for f in ("docs/results/m5_rerun.md", "docs/results/batch3.md"):
        out.append(f"{f}: {'present' if Path(f).exists() else 'missing'}")
    try:
        mi = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
        out.append(f"memory: {mi['MemAvailable'] // 1024} MB available of {mi['MemTotal'] // 1024} MB; swap used {(mi['SwapTotal'] - mi['SwapFree']) // 1024} MB")
        out.append("uptime: " + open("/proc/uptime").read().split()[0] + " s; load: " + open("/proc/loadavg").read().split()[0])
    except Exception:
        pass
    svc = subprocess.run(["systemctl", "is-active", "fxengine", "fxdash"], capture_output=True, text=True).stdout.split()
    out.append(f"services fxengine/fxdash: {svc}")
    return out


if __name__ == "__main__":
    txt = "\n".join(lines())
    Path("data").mkdir(exist_ok=True)
    Path("data/ops_report.txt").write_text(txt + "\n")
    print(txt)
