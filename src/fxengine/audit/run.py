"""Deterministic audit (never edits parameters). Five lines: freshness, cycles, lifecycle, reconciliation, alert latency."""
import pandas as pd


def audit_text(conn, now) -> str:
    since = str(now - pd.Timedelta(hours=12))
    cyc = conn.execute("SELECT ok, status FROM cycles WHERE ts>=? AND status!='CLOSED'", (since,)).fetchall()
    n, good = len(cyc), sum(r["ok"] for r in cyc)
    last = conn.execute("SELECT data_age_min FROM cycles WHERE data_age_min IS NOT NULL ORDER BY ts DESC LIMIT 1").fetchone()
    setups = conn.execute("SELECT run_id FROM setups").fetchall()
    resolved = {r["run_id"] for r in conn.execute("SELECT run_id FROM outcomes")}
    no_events = [s["run_id"] for s in setups if conn.execute("SELECT COUNT(*) FROM events WHERE run_id=?", (s["run_id"],)).fetchone()[0] == 0]
    bad_res = [r for r in resolved if conn.execute("SELECT COUNT(*) FROM events WHERE run_id=? AND to_state='RESOLVED'", (r,)).fetchone()[0] != 1]
    unsent = conn.execute("SELECT COUNT(*) FROM alerts WHERE ok=0").fetchone()[0]
    late = conn.execute("SELECT COUNT(*) FROM alerts WHERE late=1").fetchone()[0]
    mx = conn.execute("SELECT MAX(latency_s) FROM alerts").fetchone()[0]
    ev = conn.execute("SELECT COUNT(*) FROM events WHERE idx>0").fetchone()[0]
    al = conn.execute("SELECT COUNT(*) FROM alerts WHERE idx>0").fetchone()[0]
    return ("🔎 AUDIT\n"
            f"Cycles 12h: {good}/{n} ok · data age {'n/a' if not last else f'{last[0]:.0f} min'}\n"
            f"Setups {len(setups)} · resolved {len(resolved)} · lifecycle gaps {len(no_events) + len(bad_res)}\n"
            f"Events {ev} vs alerts {al} · unsent {unsent}\n"
            f"Late alerts {late} · worst latency {'n/a' if mx is None else f'{mx:.0f}s'}")
