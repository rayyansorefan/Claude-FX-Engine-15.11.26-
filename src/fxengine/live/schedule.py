"""Daily jobs inside the loop: pre-London brief (06:45 UTC), end-of-day review (21:05), one audit (07:00).
These are the only scheduled messages; everything else is a state change."""
import pandas as pd
from . import db as DB, telegram
from ..audit.run import audit_text
from ..data import store
from . import scan as SC


def _once(conn, key):
    if DB.kv_get(conn, key):
        return False
    DB.kv_set(conn, key, 1)
    return True


def brief(conn, root=store.ROOT):
    try:
        from ..dashboard.build import strength
        st = strength(root).iloc[-1].sort_values()
        return (f"☀️ PRE-LONDON · strongest {st.index[-1]}, {st.index[-2]} · weakest {st.index[0]}, {st.index[1]}\n"
                f"Setups only if a frozen rule fires on a closed bar. 'None' is a valid outcome.")
    except Exception:
        return "☀️ PRE-LONDON · no strength read available (data gap)"


def eod(conn, day):
    rows = conn.execute("SELECT o.reason, o.net_r FROM outcomes o JOIN setups s USING(run_id) WHERE s.day=?", (day,)).fetchall()
    pub = conn.execute("SELECT COUNT(*) FROM setups WHERE day=?", (day,)).fetchone()[0]
    net = sum(r["net_r"] for r in rows)
    from ..research.diagnose import live_line
    try:
        why_line = live_line(conn)
    except Exception:
        why_line = "Why trades lose: not available."
    return (f"📊 END OF DAY · {pub} published · {sum(r['reason'] == 'TARGET' for r in rows)} target · {sum(r['reason'] == 'STOP' for r in rows)} stop\n"
            f"Hypothetical net {net * 20:+.0f} GBP ({net:+.1f}R). Research only.\n{why_line}")


def daily_jobs(conn, env, now, send=telegram.send, root=store.ROOT):
    if now.day_of_week >= 5:
        return
    d, hm = str(now.date()), now.hour * 60 + now.minute
    if hm >= 6 * 60 + 45 and _once(conn, f"brief-{d}"):
        send(env, brief(conn))
    if hm >= 21 * 60 + 5 and _once(conn, f"eod-{d}"):
        send(env, eod(conn, d))
    if hm >= 21 * 60 + 20 and _once(conn, f"learn-{d}"):           # learning loop: shadow-replay today's finished trades under every exit rule
        try:
            from ..learn import review as LR
            LR.daily(conn, root, now)
            if now.day_of_week == 4:                                  # Friday = the scheduled weekly review (promotion / rollback decisions)
                for m in LR.decide(conn, now):
                    send(env, m)
                send(env, "\n".join(LR.summary_lines(conn)))
            LR.write_report(conn, now)
        except Exception as e:
            send(env, f"⚠️ LEARNING · review failed ({type(e).__name__}); the frozen exit stays in force.")
    if hm >= 7 * 60 and _once(conn, f"audit-{d}-7"):
        send(env, audit_text(conn, now))
