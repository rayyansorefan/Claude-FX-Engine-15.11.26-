"""The learning loop (deterministic, zero Claude at runtime). Pre-registered in docs/LEARNING.md.
 1. SHADOW: every finished live trade is replayed under the frozen exit and under each candidate exit rule (same prices, same tracker).
 2. REINFORCE: each rule keeps a scoreboard of paired gains/losses (R) versus the frozen exit on NEW trades only.
 3. PROMOTE (weekly, scheduled): a rule becomes the exit for NEW setups only if it clears every evidence bar below. Announced. Never silently.
 4. ROLL BACK: if the champion underperforms the frozen exit on its own forward trades, it is removed. Announced.
Only exit rules that TIGHTEN a stop are eligible, so a promoted rule can never make a single trade lose more than its original stop."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from ..backtest.run_exits import RULES, exit_hook
from ..engine.costs import CostModel
from ..engine.tracker import bar_arrays, track_arrays
from ..live import db as DB
from ..live.loop import load_m5, to_setup, FIVE
from ..research import stats

MIN_FORWARD = 60            # closed live trades with a fill before any promotion is even considered
ROLLBACK_MIN = 40           # forward trades under the champion before rollback can trigger
MIN_DAYS_BETWEEN = 14       # at most one promotion per fortnight
ALPHA = 0.05
FROZEN = "FROZEN"
EXITS_JSON = Path("docs/results/exits.json")


def shadow_one(c: dict, root, cost=CostModel(True)) -> dict:
    """{rule: net_r or None} for one finished live trade, FROZEN first. Loads prices once."""
    m5 = load_m5(c, root)
    arr = bar_arrays(m5)
    out = {}
    for rule in [FROZEN, *RULES]:
        s = to_setup(dict(c, exit_rule=None))
        hook = None if rule == FROZEN else exit_hook(rule, arr)
        t = track_arrays(s, arr, FIVE, cost, after_bar=hook)
        out[rule] = float(t.outcome.net_r) if t.outcome is not None and t.fill is not None else None
    return out


def fill_shadow(conn, root) -> int:
    """Idempotent: shadow rows for finished, filled live trades that do not have them yet."""
    rows = conn.execute("""SELECT o.run_id, s.record FROM outcomes o JOIN setups s USING(run_id)
        WHERE o.fill IS NOT NULL AND o.run_id NOT IN (SELECT run_id FROM shadow WHERE rule='FROZEN')""").fetchall()
    n = 0
    for r in rows:
        try:
            res = shadow_one(dict(json.loads(r["record"]), run_id=r["run_id"]), root)
        except Exception:
            continue
        if res[FROZEN] is None:
            continue
        conn.executemany("INSERT OR REPLACE INTO shadow VALUES(?,?,?)", [(r["run_id"], k, v) for k, v in res.items() if v is not None])
        n += 1
    conn.commit()
    return n


def scoreboard(conn, only_champion_era=None) -> dict:
    """{rule: dict(n, cum_delta_r, mean_delta, ci_lo, ci_hi)} of paired (rule minus frozen) results over finished live trades."""
    q = conn.execute("""SELECT f.run_id, s.created_at, s.pair, f.net_r AS base, r.rule, r.net_r AS alt FROM shadow f JOIN shadow r ON r.run_id=f.run_id AND r.rule!='FROZEN'
        JOIN setups s ON s.run_id=f.run_id WHERE f.rule='FROZEN' ORDER BY s.created_at""").fetchall()
    df = pd.DataFrame([dict(r) for r in q])
    out = {}
    if df.empty:
        return out
    if only_champion_era is not None:
        df = df[df.created_at >= only_champion_era]
    for rule, g in df.groupby("rule"):
        d = (g.alt - g.base).values
        cl = (g.pair + "-" + g.created_at.str[:10]).values
        lo = hi = None
        if len(d) >= 5 and len(np.unique(cl)) >= 3:
            lo, hi = stats.cluster_bootstrap_ci(d, cl, ALPHA * 2 / len(RULES))
        out[rule] = dict(n=int(len(d)), cum_delta_r=round(float(d.sum()), 3), mean_delta=round(float(d.mean()), 4),
                         ci_lo=None if lo is None else round(float(lo), 4), ci_hi=None if hi is None else round(float(hi), 4))
    return out


def history_agrees(rule: str, path: Path = EXITS_JSON) -> bool:
    """The offline walk-forward exit test must ALSO have chosen this rule and passed on unseen history, under both cost models."""
    try:
        sm = json.load(open(path))["summary"]
        return bool(sm["passes"]) and sm["best_on_first_half"] == rule
    except Exception:
        return False


def log(conn, now, kind, detail):
    conn.execute("INSERT INTO learning_log VALUES(?,?,?)", (str(now), kind, detail))
    conn.commit()


MAX_FILTER_SHARE = 0.5      # if filters remove more than half of the candidates over a week, they are switched off (the old engine starved itself of trades)
MIN_CANDIDATES = 6


def throughput(conn, now, days=7) -> dict:
    """Published setups vs candidates removed by entry filters over the last `days` days."""
    pub = conn.execute("SELECT COUNT(*) FROM setups WHERE created_at >= ?", (str(pd.Timestamp(now) - pd.Timedelta(days=days)),)).fetchone()[0]
    filt = sum(int(DB.kv_get(conn, f"filtered-{(pd.Timestamp(now) - pd.Timedelta(days=i)).date()}", 0)) for i in range(days))
    share = filt / (pub + filt) if (pub + filt) else 0.0
    return dict(published=int(pub), filtered=int(filt), share=share)


def throughput_guard(conn, now) -> list[str]:
    """Stops filters from becoming a bottleneck: too many vetoes -> filters off, announced."""
    from . import filters as FL
    t = throughput(conn, now)
    if FL.load() and not DB.kv_get(conn, "filters_disabled") and t["published"] + t["filtered"] >= MIN_CANDIDATES and t["share"] > MAX_FILTER_SHARE:
        DB.kv_set(conn, "filters_disabled", 1)
        log(conn, now, "FILTERS_OFF", str(t))
        return [f"🔻 LEARNING · entry filters switched OFF: they removed {t['filtered']} of {t['published'] + t['filtered']} setups this week ({t['share']:.0%}). Too many vetoes starve the engine of trades. Frozen rules are back."]
    return []


def decide(conn, now, exits_json: Path = EXITS_JSON) -> list[str]:
    """Weekly scheduled review. Returns plain-English announcement lines (empty = nothing changed)."""
    msgs = throughput_guard(conn, now)
    champ = DB.kv_get(conn, "champion_exit")
    since = DB.kv_get(conn, "champion_since")
    if champ:                                                     # --- rollback check on the champion's own forward trades
        board = scoreboard(conn, only_champion_era=since)
        b = board.get(champ)
        if b and b["n"] >= ROLLBACK_MIN and b["ci_hi"] is not None and b["ci_hi"] < 0:
            conn.execute("DELETE FROM kv WHERE k IN ('champion_exit','champion_since')")
            conn.commit()
            log(conn, now, "ROLLBACK", f"{champ}: {b}")
            msgs.append(f"🔻 LEARNING · exit rule {champ} rolled back to the frozen exit: it did worse than the frozen exit on {b['n']} of its own trades ({b['mean_delta']:+.2f}R each). New setups use the frozen exit again.")
        return msgs
    board = scoreboard(conn)
    last = conn.execute("SELECT ts FROM learning_log WHERE kind IN ('PROMOTE','ROLLBACK') ORDER BY ts DESC LIMIT 1").fetchone()
    if last and (pd.Timestamp(now) - pd.Timestamp(last["ts"])).days < MIN_DAYS_BETWEEN:
        return msgs
    for rule, b in sorted(board.items(), key=lambda kv: -(kv[1]["mean_delta"])):
        ok = (b["n"] >= MIN_FORWARD and b["ci_lo"] is not None and b["ci_lo"] > 0 and history_agrees(rule, exits_json))
        if ok:
            DB.kv_set(conn, "champion_exit", rule)
            DB.kv_set(conn, "champion_since", str(now))
            log(conn, now, "PROMOTE", f"{rule}: {b}")
            msgs.append(f"🟢 LEARNING · exit rule {rule} promoted for NEW setups: beat the frozen exit by {b['mean_delta']:+.2f}R per trade on {b['n']} live trades AND on unseen history. It only tightens stops. UNPROVEN. Auto-rollback is on.")
            break
    return msgs


def summary_lines(conn) -> list[str]:
    """Three lines for the weekly Telegram note."""
    n = conn.execute("SELECT COUNT(*) FROM shadow WHERE rule='FROZEN'").fetchone()[0]
    champ = DB.kv_get(conn, "champion_exit") or "frozen exit"
    board = scoreboard(conn)
    if not board:
        return [f"🧠 LEARNING · {n} finished trades studied so far. Exit in force: {champ}.", f"Needs {MIN_FORWARD} before any change can be considered."]
    best = max(board.items(), key=lambda kv: kv[1]["mean_delta"])
    return [f"🧠 LEARNING · {n} finished trades studied. Exit in force: {champ}.",
            f"Best candidate so far: {best[0]} ({best[1]['mean_delta']:+.2f}R per trade vs frozen, n={best[1]['n']}).",
            f"No change until {MIN_FORWARD}+ trades, a proven gain and a matching history test."]


def daily(conn, root, now) -> int:
    return fill_shadow(conn, root)


def write_report(conn, now, out=Path("docs/results/learning.md")) -> str:
    board = scoreboard(conn)
    champ = DB.kv_get(conn, "champion_exit") or "none (frozen exit)"
    L = [f"# Learning loop (written {pd.Timestamp(now):%Y-%m-%d %H:%M} UTC)", "", f"Exit in force for new setups: **{champ}**",
         f"Bars before any promotion: {MIN_FORWARD}+ live trades, CI lower bound > 0 (alpha 0.05/{len(RULES)}), offline walk-forward test agrees, max one change per {MIN_DAYS_BETWEEN} days, auto-rollback after {ROLLBACK_MIN} trades.", "",
         "| rule | trades | cumulative gain vs frozen (R) | per trade | 95% range |", "|---|---|---|---|---|"]
    for rule in RULES:
        b = board.get(rule)
        if b:
            L.append(f"| {rule} | {b['n']} | {b['cum_delta_r']:+.2f} | {b['mean_delta']:+.3f} | " + ("n/a (too few)" if b["ci_lo"] is None else f"[{b['ci_lo']:+.3f}, {b['ci_hi']:+.3f}]") + " |")
    L += ["", "Log:"] + [f"- {r['ts'][:16]} {r['kind']}: {r['detail'][:160]}" for r in conn.execute("SELECT * FROM learning_log ORDER BY ts DESC LIMIT 10")]
    text = "\n".join(L) + "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    return text
