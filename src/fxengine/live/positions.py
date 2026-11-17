"""Plain-text snapshot of every setup that is not finished, written each cycle to docs/results/live_positions.md (the ops runner pushes it
back to the vm-results branch). Lets anyone verify, from the ledger itself, whether open positions are approaching target / stop / time limit."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

OUT = Path("docs/results/live_positions.md")


def describe(c: dict, t, last_px: float | None, now) -> str:
    s = t.s
    risk = s.risk
    sign = 1 if c["direction"] == "long" else -1
    head = f"{c['pair']} {c['direction'].upper()} {c['type']} [{t.state}] created {str(c['created'])[:16]}"
    lv = f"entry {s.entry:.5f} stop {t.stop:.5f} target {t.target:.5f}"
    if t.fill is None:
        left = (pd.Timestamp(c["expires"]) - now).total_seconds() / 3600
        d = None if last_px is None else sign * (s.entry - last_px) / risk
        return f"- {head}\n  not filled yet. {lv}. Expires in {left:.1f}h." + ("" if d is None else f" Price is {d:+.2f}R from entry (positive = entry still ahead).")
    unreal = None if last_px is None else sign * (last_px - t.fill) / risk
    to_t = None if last_px is None else sign * (t.target - last_px) / risk
    return (f"- {head}\n  FILLED at {t.fill:.5f}. {lv}. Unrealised {'n/a' if unreal is None else format(unreal, '+.2f')}R, best so far {t.mfe:+.2f}R, worst {-t.mae:+.2f}R. "
            f"Target is {'n/a' if to_t is None else format(to_t, '.2f')}R away. Held {t.bars_held} of {s.max_hold_bars} five-minute bars "
            f"({max(0, s.max_hold_bars - t.bars_held) * 5 / 60:.0f}h until the time limit).")


def backfill_outcomes(conn, root) -> int:
    """Finished trades that were recorded before diagnostics existed get their best/worst point by replaying the stored prices
    (deterministic: the same tracker the live loop uses). Idempotent."""
    from .loop import replay
    rows = conn.execute("""SELECT o.run_id, s.record FROM outcomes o JOIN setups s USING(run_id)
                           WHERE o.fill IS NOT NULL AND o.mfe_r IS NULL""").fetchall()
    n = 0
    for r in rows:
        try:
            t, _ = replay(dict(json.loads(r["record"]), run_id=r["run_id"]), root)
            if t.outcome is not None:
                conn.execute("UPDATE outcomes SET gross_r=?, mfe_r=?, mae_r=? WHERE run_id=?", (t.outcome.gross_r, t.outcome.mfe_r, t.outcome.mae_r, r["run_id"]))
                n += 1
        except Exception:
            continue
    conn.commit()
    return n


def snapshot(conn, root, now, out: Path = OUT) -> str:
    backfill_outcomes(conn, root)
    from .loop import replay
    from ..data import store
    rows = conn.execute("SELECT record FROM setups WHERE run_id NOT IN (SELECT run_id FROM outcomes) ORDER BY created_at").fetchall()
    lines = [f"# Live positions (written {now:%Y-%m-%d %H:%M} UTC)", "", f"Unfinished setups: {len(rows)}", ""]
    for r in rows:
        c = json.loads(r["record"])
        try:
            t, m5 = replay(c, root)
            last = float(store.load(c["pair"], "M5", root, tail=1).bid_c.iloc[-1])
            lines.append(describe(c, t, last, now))
        except Exception as e:                                       # one bad setup never hides the others
            lines.append(f"- {c.get('pair')} {c.get('run_id')}: could not describe ({type(e).__name__})")
    done = conn.execute("""SELECT s.pair, s.type, o.reason, o.net_r, o.fill, o.gross_r, o.mfe_r, o.mae_r, o.resolved_at FROM outcomes o
                           JOIN setups s USING(run_id) ORDER BY o.resolved_at DESC LIMIT 15""").fetchall()
    lines += ["", f"Last {len(done)} finished: reason, net R, best point reached (MFE), worst (MAE), why it lost (when it lost)", ""]
    from ..research.diagnose import classify
    for d in done:
        mfe, mae = d["mfe_r"], d["mae_r"]
        why = ""
        if d["fill"] is not None and d["net_r"] is not None and d["net_r"] <= 0 and mfe is not None and d["gross_r"] is not None:
            why = " · " + classify(dict(triggered=True, net_r=d["net_r"], gross_r=d["gross_r"], mfe_r=mfe))
        extra = "" if mfe is None else f" · best {mfe:+.2f}R, worst {-mae:+.2f}R{why}"
        lines.append(f"- {d['pair']} {d['type']}: {d['reason']} {d['net_r']:+.2f}R at {str(d['resolved_at'])[:16]}{extra}")
    text = "\n".join(lines) + "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    return text
