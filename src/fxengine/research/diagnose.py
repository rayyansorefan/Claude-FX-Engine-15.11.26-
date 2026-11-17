"""Automatic trade post-mortem: WHY do trades lose, and is any difference between winners and losers real?
Deterministic code, zero Claude at runtime. It NEVER changes a parameter. It writes findings and, when a pattern survives
strict checks, logs a CANDIDATE hypothesis that must go through a pre-registered forward test before any rule changes.

Usage: PYTHONPATH=src python -m fxengine.research.diagnose   -> docs/results/diagnosis.{md,json}, docs/hypotheses.jsonl
Inputs: data/*.parquet from the research runners (need mfe_r / mae_r / gross_r columns) and the live ledger (data/engine.db).
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from statistics import NormalDist
import numpy as np
import pandas as pd

MIN_CLASS_N = 30          # below this many scored trades a pattern is "too few trades", never a finding
MIN_BUCKET_N = 30
ALPHA = 0.05
SESSIONS = [(0, 7, "Asia"), (7, 12, "London AM"), (12, 16, "London/NY overlap"), (16, 21, "NY PM"), (21, 24, "Late")]


def session_of(hour: int) -> str:
    for a, b, n in SESSIONS:
        if a <= hour < b:
            return n
    return "Late"


def trade_fields(outcome, direction: str, created) -> dict:
    """Per-trade diagnostics stored beside every backtest/live trade (stressed costs for the backtest)."""
    c = pd.Timestamp(created)
    return dict(direction=direction, gross_r=outcome.gross_r if outcome else 0.0, mfe_r=outcome.mfe_r if outcome else 0.0,
                mae_r=outcome.mae_r if outcome else 0.0, hour=int(c.hour), dow=int(c.dayofweek))


def classify(row) -> str:
    """One label per trade. Order matters: first match wins."""
    if not row["triggered"]:
        return "NO_FILL"
    if row["net_r"] > 0:
        return "WIN"
    if row["gross_r"] > 0:
        return "COST_DRAG"            # right direction, costs ate it
    if row["mfe_r"] < 0.5:
        return "WRONG_WAY"            # never showed a real profit: the signal was wrong
    if row["mfe_r"] >= 1.0:
        return "GAVE_BACK"            # was 1R+ ahead and still lost: exit/management problem
    return "STALLED"                  # 0.5-1R ahead, then failed


def review(reason, net_r, fill, gross_r, mfe_r, mae_r, rr=None) -> str:
    """Plain-English post-mortem of ONE finished trade, derived only from stored numbers (so it is reproducible). Improvements are
    HYPOTHESES to be replayed on history, never live changes."""
    if fill is None:
        return f"Never filled ({str(reason).lower()}): no trade was taken, so there is no price path to learn from."
    if mfe_r is None or mae_r is None or gross_r is None:
        return "Detailed price path was not recorded for this trade (it closed before diagnostics were added)."
    if reason == "TIMEOUT":
        return (f"Time limit reached: neither stop nor target hit. Best point {mfe_r:+.2f}R, worst {-mae_r:+.2f}R, closed {net_r:+.2f}R. "
                "Hypothesis: shorter hold limit or a nearer target for this rule (test on history).")
    if net_r > 0:
        left = mfe_r - gross_r
        t = f"Win: best point {mfe_r:+.2f}R, closed {net_r:+.2f}R net" + (f"; left {left:.2f}R of the peak on the table." if left > 0.3 else "; exited close to the peak.")
        t += (f" It dipped {mae_r:.2f}R against you first, close to the stop: entry timing may be improvable (hypothesis)." if mae_r >= 0.6
              else f" Clean entry: never more than {mae_r:.2f}R against.")
        return t
    k = classify(dict(triggered=True, net_r=net_r, gross_r=gross_r, mfe_r=mfe_r))
    pct = f" ({mfe_r / rr:.0%} of the way to the target)" if rr else ""
    if k == "WRONG_WAY":
        return (f"Loss, wrong way: never more than {mfe_r:.2f}R ahead. The signal or entry was wrong from the start, so no exit rule could have saved it. "
                "Hypothesis: a stricter entry filter for this rule (test on history).")
    if k == "STALLED":
        return (f"Loss, stalled: reached {mfe_r:.2f}R{pct}, then reversed to the stop. Profit was available. "
                "Hypothesis: an earlier break-even stop (exit test A1/A2) would have protected it.")
    if k == "GAVE_BACK":
        return (f"Loss, gave back: was {mfe_r:.2f}R ahead{pct} and still hit the stop. Profit was clearly available. "
                "Hypothesis: a trailing or keep-a-share exit (exit tests B and C) would have protected it.")
    return "Loss, cost drag: the direction was right but spread and costs ate the gain. Hypothesis: avoid thin hours or wide-spread moments (test on history)."


def tally(items, need=MIN_CLASS_N) -> list[str]:
    """Roll the per-trade reviews up per rule: how often each cause repeats. Plain lines for the History tab.
    items: dicts with type, reason, net_r, fill, gross_r, mfe_r, mae_r (finished trades only)."""
    by = {}
    for it in items:
        if it.get("fill") is None or it.get("net_r") is None:
            continue
        if it["net_r"] > 0:
            k = "WIN"
        elif it.get("mfe_r") is None or it.get("gross_r") is None:
            k = "UNRECORDED"
        else:
            k = classify(dict(triggered=True, net_r=it["net_r"], gross_r=it["gross_r"], mfe_r=it["mfe_r"]))
        by.setdefault(it["type"], {}).setdefault(k, 0)
        by[it["type"]][k] += 1
    names = {"WIN": "won", "WRONG_WAY": "wrong way", "STALLED": "stalled (was 0.5-1R ahead)", "GAVE_BACK": "gave back (was 1R+ ahead)",
             "COST_DRAG": "cost drag", "UNRECORDED": "path not recorded"}
    out = []
    for typ, c in sorted(by.items()):
        n = sum(c.values())
        parts = ", ".join(f"{v} {names[k]}" for k, v in sorted(c.items(), key=lambda kv: -kv[1]))
        left = max(0, need - n)
        out.append(f"{typ}: {n} closed · {parts}. " + (f"{left} more closed trades before this rule's pattern can be judged." if left else "Enough trades to test: see the exit and entry tests."))
    return out


def prepare(df: pd.DataFrame, cost: str = "stressed") -> pd.DataFrame:
    """Normalise a research frame to: net_r, triggered, gross_r, mfe_r, mae_r, symbol, direction, hour, dow, created."""
    need = {"mfe_r", "mae_r", "gross_r"}
    if not need.issubset(df.columns):
        return pd.DataFrame()
    d = df.copy()
    d["net_r"] = d[f"net_r_{cost}"] if f"net_r_{cost}" in d else d.get("net_r", 0.0)
    d["triggered"] = d[f"trig_{cost}"] if f"trig_{cost}" in d else d.get("triggered", True)
    d = d[d.triggered & (d.get("reason", "") != "OPEN")] if len(d) else d
    d["created"] = pd.to_datetime(d["created"], utc=True)
    d["klass"] = d.apply(classify, axis=1) if len(d) else []
    d["session"] = d["hour"].map(session_of) if len(d) else []
    return d


def class_table(d: pd.DataFrame) -> list[dict]:
    out = []
    for k, g in d.groupby("klass"):
        out.append(dict(klass=k, n=int(len(g)), share=round(len(g) / len(d), 3), mean_net_r=round(float(g.net_r.mean()), 3),
                        mean_mfe_r=round(float(g.mfe_r.mean()), 2), mean_mae_r=round(float(g.mae_r.mean()), 2)))
    return sorted(out, key=lambda r: -r["n"])


def winners_vs_losers(d: pd.DataFrame) -> dict:
    w, l = d[d.net_r > 0], d[d.net_r <= 0]
    f = lambda g, c: round(float(g[c].mean()), 3) if len(g) else None
    return dict(n_win=int(len(w)), n_loss=int(len(l)), win_mfe=f(w, "mfe_r"), loss_mfe=f(l, "mfe_r"), win_mae=f(w, "mae_r"),
                loss_mae=f(l, "mae_r"), win_bars=f(w, "bars") if "bars" in d else None, loss_bars=f(l, "bars") if "bars" in d else None)


def feature_scan(d: pd.DataFrame, features=("symbol", "direction", "session", "dow")) -> dict:
    """Pre-set, small feature list (no free-form mining). A bucket is SUPPORTED only if: n >= 30, its mean differs from the
    rest of the trades at a Bonferroni-corrected level over every bucket tested, AND the earlier and later half of the sample
    agree on the sign. Everything else is reported as noise."""
    d = d.sort_values("created")
    half = d.created.iloc[len(d) // 2] if len(d) else None
    buckets = [(f, v) for f in features if f in d for v in sorted(d[f].unique(), key=str)]
    m = max(len(buckets), 1)
    z_need = NormalDist().inv_cdf(1 - ALPHA / (2 * m))
    rows = []
    for f, v in buckets:
        g, rest = d[d[f] == v], d[d[f] != v]
        if len(g) < MIN_BUCKET_N or len(rest) < MIN_BUCKET_N:
            rows.append(dict(feature=f, bucket=str(v), n=int(len(g)), status="too few trades"))
            continue
        se = float(np.sqrt(g.net_r.var(ddof=1) / len(g) + rest.net_r.var(ddof=1) / len(rest)))
        diff = float(g.net_r.mean() - rest.net_r.mean())
        z = diff / se if se > 0 else 0.0
        a, b = g[g.created < half].net_r, g[g.created >= half].net_r
        ra, rb = rest[rest.created < half].net_r, rest[rest.created >= half].net_r
        stable = len(a) >= 10 and len(b) >= 10 and np.sign(a.mean() - ra.mean()) == np.sign(b.mean() - rb.mean()) == np.sign(diff)
        ok = abs(z) >= z_need and bool(stable)
        rows.append(dict(feature=f, bucket=str(v), n=int(len(g)), mean_net_r=round(float(g.net_r.mean()), 3), diff_vs_rest=round(diff, 3),
                         z=round(z, 2), z_needed=round(z_need, 2), stable_halves=bool(stable), status="SUPPORTED" if ok else "noise"))
    return dict(tests=m, z_needed=round(z_need, 2), rows=rows, supported=[r for r in rows if r["status"] == "SUPPORTED"])


def management_flag(d: pd.DataFrame) -> dict | None:
    """If many LOSERS were 1R+ ahead first, exits (not signals) are the weak point. Only a flag; it needs a pre-registered test."""
    los = d[d.net_r <= 0]
    if len(los) < MIN_CLASS_N:
        return None
    gb = float((los.klass == "GAVE_BACK").mean())
    return dict(share_of_losers_gave_back=round(gb, 3), flag=bool(gb >= 0.30))


def diagnose(df: pd.DataFrame, name: str) -> dict:
    d = prepare(df)
    if d.empty or len(d) < MIN_CLASS_N:
        return dict(name=name, n=int(len(d)), verdict="too few scored trades with diagnostics to say anything")
    classes = class_table(d)
    losers = d[d.net_r <= 0]
    top = max((c for c in classes if c["klass"] not in ("WIN", "NO_FILL")), key=lambda c: c["n"], default=None)
    scan = feature_scan(d)
    mg = management_flag(d)
    if scan["supported"]:
        verdict = f"{len(scan['supported'])} pattern(s) survived strict checks: CANDIDATE hypotheses logged, not applied."
    else:
        verdict = "No winner-vs-loser pattern survives the multiple-testing and half-sample checks (treat differences as noise)."
    return dict(name=name, n=int(len(d)), win_rate=round(float((d.net_r > 0).mean()), 3), mean_net_r=round(float(d.net_r.mean()), 3),
                losers=int(len(losers)), main_loss_cause=top, classes=classes, winners_vs_losers=winners_vs_losers(d),
                management=mg, scan=scan, verdict=verdict)


def log_hypotheses(res: dict, reg: Path = Path("docs/hypotheses.jsonl")) -> int:
    n = 0
    reg.parent.mkdir(parents=True, exist_ok=True)
    seen = set(reg.read_text().splitlines()) if reg.exists() else set()
    with reg.open("a") as fh:
        for r in res.get("scan", {}).get("supported", []):
            rec = dict(source=res["name"], feature=r["feature"], bucket=r["bucket"], n=r["n"], diff_vs_rest=r["diff_vs_rest"], z=r["z"],
                       status="CANDIDATE: needs a pre-registered forward test before any rule changes")
            line = json.dumps(rec, sort_keys=True)
            if line not in seen:
                fh.write(line + "\n"); n += 1
        if res.get("management", {}) and res["management"].get("flag"):
            line = json.dumps(dict(source=res["name"], feature="management", bucket="gave_back_share", n=res["losers"],
                                   diff_vs_rest=res["management"]["share_of_losers_gave_back"], z=None,
                                   status="CANDIDATE: exits may be the weak point; needs a pre-registered forward test"), sort_keys=True)
            if line not in seen:
                fh.write(line + "\n"); n += 1
    return n


def live_frame(conn) -> pd.DataFrame:
    """Resolved live trades from the ledger -> the same columns as a research frame."""
    rows = conn.execute("""SELECT s.created_at, s.pair, s.record, o.reason, o.net_r, o.gross_r, o.mfe_r, o.mae_r FROM outcomes o
                           JOIN setups s USING(run_id) WHERE o.fill IS NOT NULL AND o.gross_r IS NOT NULL""").fetchall()
    out = []
    for r in rows:
        rec = json.loads(r["record"]); c = pd.Timestamp(r["created_at"])
        out.append(dict(symbol=r["pair"], created=c, reason=r["reason"], net_r_stressed=r["net_r"], trig_stressed=True, gross_r=r["gross_r"],
                        mfe_r=r["mfe_r"], mae_r=r["mae_r"], direction=rec.get("direction", "?"), hour=int(c.hour), dow=int(c.dayofweek)))
    return pd.DataFrame(out)


def live_line(conn) -> str:
    """One line for the end-of-day message."""
    d = prepare(live_frame(conn))
    if d.empty:
        return "Why trades lose: no resolved live trades with diagnostics yet."
    los = d[d.net_r <= 0]
    if los.empty:
        return f"Why trades lose: no losses yet ({len(d)} resolved)."
    cnt = los.klass.value_counts()
    txt = ", ".join(f"{n} {k.lower().replace('_', ' ')}" for k, n in cnt.items())
    return f"Why trades lose ({len(los)} of {len(d)}): {txt}. Too few for conclusions." if len(d) < MIN_CLASS_N else f"Why trades lose ({len(los)} of {len(d)}): {txt}."


def render(results: list[dict]) -> str:
    L = ["# Trade post-mortem (automatic, deterministic)", "",
         "Classes: WRONG_WAY = never 0.5R ahead (signal wrong) · GAVE_BACK = was 1R+ ahead then lost (exit problem) · "
         "STALLED = 0.5-1R ahead then failed · COST_DRAG = right direction, costs ate it.",
         f"A pattern counts only with >= {MIN_BUCKET_N} trades, a Bonferroni-corrected test over every bucket checked, and the same sign in both halves of the sample.", ""]
    for r in results:
        L += [f"## {r['name']}  (n={r['n']})", ""]
        if "classes" not in r:
            L += [r["verdict"], ""]; continue
        L += [f"Win rate {r['win_rate']:.0%} · mean {r['mean_net_r']:+.3f}R · **{r['verdict']}**", "",
              "| class | n | share | mean net R | mean best (MFE) | mean worst (MAE) |", "|---|---|---|---|---|---|"]
        L += [f"| {c['klass']} | {c['n']} | {c['share']:.0%} | {c['mean_net_r']:+.3f} | {c['mean_mfe_r']:.2f} | {c['mean_mae_r']:.2f} |" for c in r["classes"]]
        w = r["winners_vs_losers"]
        L += ["", f"Winners vs losers: best excursion {w['win_mfe']} vs {w['loss_mfe']} R, worst excursion {w['win_mae']} vs {w['loss_mae']} R.", ""]
        if r["management"]:
            L += [f"Exits: {r['management']['share_of_losers_gave_back']:.0%} of losers had been 1R+ ahead" + (" (FLAG)" if r["management"]["flag"] else ""), ""]
        sup = r["scan"]["supported"]
        L += [f"Buckets tested {r['scan']['tests']} (needs |z| >= {r['scan']['z_needed']}): " + (", ".join(f"{s['feature']}={s['bucket']} ({s['diff_vs_rest']:+.2f}R)" for s in sup) if sup else "none survive"), ""]
    return "\n".join(L)


def main(data=Path("data"), out=Path("docs/results"), reg=Path("docs/hypotheses.jsonl"), db_path="data/engine.db"):
    results = []
    for p in sorted(Path(data).glob("m5_rerun_*.parquet")) + sorted(Path(data).glob("batch3_*.parquet")):
        results.append(diagnose(pd.read_parquet(p), p.stem))
    if Path(db_path).exists():
        from ..live import db as DB
        results.append(diagnose(live_frame(DB.connect(db_path)), "live_ledger"))
    n_new = sum(log_hypotheses(r, reg) for r in results if "classes" in r)
    out.mkdir(parents=True, exist_ok=True)
    json.dump(results, open(out / "diagnosis.json", "w"), indent=1, default=str)
    (out / "diagnosis.md").write_text(render(results))
    print(render(results)); print(f"new candidate hypotheses logged: {n_new}")
    return results


if __name__ == "__main__":
    main()
