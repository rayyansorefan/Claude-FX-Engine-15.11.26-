"""Live post-mortem: what do the LOSING trades have in common, what do the WINNING trades have in common, and which entry conditions separate them? Deterministic, zero Claude at runtime.
Runs every day after the learning job and writes docs/results/postmortem.md (+ a short Telegram note on Fridays, a dashboard card).
Method (pre-registered in docs/LEARNING.md, 2026-11-26):
  1. LOSS ANATOMY: every losing trade is classed from its own path: WRONG FROM THE START (never got more than +0.4R ahead), FADED (got +1R or better, then lost), TIME-OUT, or OTHER.
  2. SEPARATORS: every pre-registered entry condition (learn/filters.py ATOMS: volatility, trend strength, extension, higher-timeframe alignment, session hours, weekday) is compared on the trades that
     PASS it versus the trades that FAIL it: win rate and mean R of each side, difference, and a Bonferroni-corrected confidence range (alpha 0.05 over all conditions tested). Pooled and per strategy.
  3. A condition is called a HYPOTHESIS when both sides have 8+ trades and the corrected range excludes 0 in its favour; it is called SUPPORTED only with 30+ trades on each side.
Nothing in this file changes a trade or a rule. A supported separator is only a CANDIDATE: it still has to pass the offline validation on unseen history before it can become an entry filter (docs/LEARNING.md)."""
from __future__ import annotations
import json
import math
import statistics
from statistics import NormalDist
from pathlib import Path
import pandas as pd
from .filters import ATOMS

MIN_SIDE_HYP = 8
MIN_SIDE_SUPPORTED = 30
ALPHA = 0.05                                    # family-wise error for SUPPORTED (Bonferroni over EVERY comparison in the report)
FDR = 0.10                                      # false-discovery rate for HYPOTHESIS (Benjamini-Hochberg over the same family; display only, can never trigger anything)
WRONG_START_BELOW = 0.4
FADED_FROM = 1.0
_N = NormalDist()


def _p_two_sided(z: float) -> float:
    return 2 * (1 - _N.cdf(abs(z)))


def load_trades(conn) -> list[dict]:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(outcomes)")}
    extra = ", ".join(f"o.{c}" if c in cols else f"NULL AS {c}" for c in ("gross_r", "mfe_r", "mae_r"))
    out = []
    for r in conn.execute(f"SELECT s.run_id, s.pair, s.type, s.record, o.reason, o.net_r, {extra} FROM outcomes o JOIN setups s USING(run_id) "
                          "WHERE o.reason IN ('TARGET','STOP','TIMEOUT') AND o.net_r IS NOT NULL"):
        rec = json.loads(r["record"])
        out.append(dict(run_id=r["run_id"], pair=r["pair"], type=r["type"], direction=rec.get("direction"), net_r=float(r["net_r"]), reason=r["reason"],
                        mfe_r=None if r["mfe_r"] is None else float(r["mfe_r"]), mae_r=None if r["mae_r"] is None else float(r["mae_r"]), ctx=rec.get("ctx") or {}))
    return out


def loss_anatomy(trades: list[dict]) -> dict:
    losers = [t for t in trades if t["net_r"] <= 0]
    kinds = {"wrong_from_start": 0, "faded": 0, "timeout": 0, "other": 0, "unknown": 0}
    for t in losers:
        if t["reason"] == "TIMEOUT":
            kinds["timeout"] += 1
        elif t["mfe_r"] is None:
            kinds["unknown"] += 1
        elif t["mfe_r"] < WRONG_START_BELOW:
            kinds["wrong_from_start"] += 1
        elif t["mfe_r"] >= FADED_FROM:
            kinds["faded"] += 1
        else:
            kinds["other"] += 1
    n = len(losers)
    return dict(losers=n, winners=len(trades) - n, kinds=kinds, avg_loss=statistics.mean([t["net_r"] for t in losers]) if losers else 0.0,
                avg_win=statistics.mean([t["net_r"] for t in trades if t["net_r"] > 0]) if len(trades) > n else 0.0)


def _side(rs: list[float]) -> dict:
    n = len(rs)
    return dict(n=n, win=(sum(x > 0 for x in rs) / n) if n else None, mean=statistics.mean(rs) if n else None, var=statistics.variance(rs) if n > 1 else 0.0)


def separators(trades: list[dict]) -> list[dict]:
    """Every pre-registered condition: results of the trades that pass it versus those that fail it, with a Welch z statistic and two-sided p. Verdicts are assigned afterwards by classify()."""
    rows = [dict(net_r=t["net_r"], **{k: v for k, v in t["ctx"].items() if isinstance(v, (int, float))}) for t in trades]
    df = pd.DataFrame(rows)
    out = []
    for name, fn in ATOMS.items():
        try:
            mask = fn(df)
        except Exception:
            mask = None                                                # a column was never recorded for these trades
        if mask is None:
            out.append(dict(name=name, status="not recorded", passes=_side([]), fails=_side([]), diff=None, se=None, p=None))
            continue
        mask = mask.fillna(False)
        a, b = _side(df.net_r[mask].tolist()), _side(df.net_r[~mask].tolist())
        if a["n"] < MIN_SIDE_HYP or b["n"] < MIN_SIDE_HYP:
            out.append(dict(name=name, status="too few", passes=a, fails=b, diff=None, se=None, p=None))
            continue
        diff = a["mean"] - b["mean"]
        se = math.sqrt(a["var"] / a["n"] + b["var"] / b["n"]) or 1e-9
        out.append(dict(name=name, status="", passes=a, fails=b, diff=diff, se=se, p=_p_two_sided(diff / se)))
    return out


def classify(groups: list[list[dict]], m: int) -> None:
    """Assigns verdicts in place across ALL comparisons of the report (m = every comparison attempted, including those with too few trades, so the correction is never flattered).
    SUPPORTED   : 30+ trades on each side AND p <= ALPHA/m (Bonferroni, family-wise error 5% over the whole report) -> the only level that can ever lead to a filter.
    HYPOTHESIS  : 8+ trades on each side AND Benjamini-Hochberg false-discovery rate 10% over the whole report. Shown to the owner; never triggers anything.
    Each comparison also gets its Bonferroni-corrected range for the difference in mean R."""
    z = _N.inv_cdf(1 - ALPHA / (2 * m))
    every = [s for g in groups for s in g if s["p"] is not None]
    ranked = sorted(every, key=lambda s: s["p"])
    bh_cut = 0.0
    for i, s in enumerate(ranked, 1):
        if s["p"] <= FDR * i / m:
            bh_cut = s["p"]
    for s in every:
        s["lo"], s["hi"] = s["diff"] - z * s["se"], s["diff"] + z * s["se"]
        better = s["diff"] > 0
        word = "do better" if better else "do WORSE"
        if min(s["passes"]["n"], s["fails"]["n"]) >= MIN_SIDE_SUPPORTED and s["p"] <= ALPHA / m:
            s["status"] = f"SUPPORTED: trades that pass it {word}"
        elif s["p"] <= bh_cut and bh_cut > 0:
            s["status"] = f"HYPOTHESIS: trades that pass it {word}"
        else:
            s["status"] = "no separation"
    for g in groups:
        for s in g:
            s.setdefault("lo", None); s.setdefault("hi", None)


def analyse(conn) -> dict:
    trades = load_trades(conn)
    res = dict(n=len(trades), anatomy=loss_anatomy(trades), pooled=[], by_type={}, m=0, alpha_per_test=None)
    groups = []
    if len(trades) >= 2 * MIN_SIDE_HYP:
        res["pooled"] = separators(trades)
        groups.append(res["pooled"])
    for typ in sorted({t["type"] for t in trades}):
        sub = [t for t in trades if t["type"] == typ]
        if len(sub) >= 2 * MIN_SIDE_HYP:
            res["by_type"][typ] = dict(n=len(sub), seps=separators(sub), anatomy=loss_anatomy(sub))
            groups.append(res["by_type"][typ]["seps"])
    m = max(1, sum(len(g) for g in groups))
    classify(groups, m)
    res["m"], res["alpha_per_test"] = m, ALPHA / m
    return res


def _hits(seps: list[dict]) -> list[dict]:
    return [s for s in seps if s["status"].startswith(("SUPPORTED", "HYPOTHESIS"))]


def labeled_hits(res: dict) -> list[tuple[str, dict]]:
    """[(group, comparison)] for everything flagged, SUPPORTED first, then by size of the difference."""
    out = [("all strategies", h) for h in _hits(res["pooled"])] + [(typ, h) for typ, v in res["by_type"].items() for h in _hits(v["seps"])]
    return sorted(out, key=lambda gh: (not gh[1]["status"].startswith("SUPPORTED"), -abs(gh[1]["diff"])))


def summary_lines(res: dict) -> list[str]:
    a = res["anatomy"]
    if res["n"] < 10 or a["losers"] == 0:
        return [f"🔎 POST-MORTEM · {res['n']} finished trades so far.", "Too few to say what separates winners from losers (needs 16+ for a first look, 30+ per side to rely on it).", "Nothing is changed by this note."]
    k = a["kinds"]
    pct = lambda x: f"{x / a['losers'] * 100:.0f}%"
    hits = labeled_hits(res)
    grp, top = hits[0] if hits else (None, None)
    l3 = (f"Best separator: {top['name']} in {grp} ({top['status'].split(':')[0].lower()}, {top['diff']:+.2f}R). Candidate only: it must pass history validation first." if top
          else "No entry condition separates winners from losers yet (corrected for testing many). Nothing is changed.")
    return [f"🔎 POST-MORTEM · {a['losers']} losses, {a['winners']} wins. Losses: {pct(k['wrong_from_start'])} wrong from the start, {pct(k['faded'])} faded after +1R, {pct(k['timeout'])} timed out.",
            f"Average win {a['avg_win']:+.2f}R, average loss {a['avg_loss']:+.2f}R.", l3]


def write_report(conn, out: Path = Path("docs/results/postmortem.md")) -> dict:
    res = analyse(conn)
    a = res["anatomy"]
    L = ["# Live post-mortem (written by code; nothing here changes a trade)", "",
         f"Finished live trades: {res['n']} ({a['winners']} won, {a['losers']} lost). Average win {a['avg_win']:+.2f}R, average loss {a['avg_loss']:+.2f}R.", "",
         "## What the losses have in common", f"- wrong from the start (never more than +{WRONG_START_BELOW}R ahead): {a['kinds']['wrong_from_start']}", f"- faded (was +{FADED_FROM}R or better, then lost): {a['kinds']['faded']}",
         f"- timed out: {a['kinds']['timeout']}", f"- other: {a['kinds']['other']}; path unknown: {a['kinds']['unknown']}", ""]

    def table(seps):
        t = ["| condition | pass: n / win / mean | fail: n / win / mean | difference (range) | verdict |", "|---|---|---|---|---|"]
        for s in seps:
            f = lambda x: "n/a" if x["n"] == 0 else f"{x['n']} / {x['win']:.0%} / {x['mean']:+.2f}R"
            t.append(f"| {s['name']} | {f(s['passes'])} | {f(s['fails'])} | " + ("n/a" if s["diff"] is None else f"{s['diff']:+.2f}R [{s['lo']:+.2f}, {s['hi']:+.2f}]") + f" | {s['status']} |")
        return t
    if res["pooled"]:
        L += ["## Conditions compared, all strategies pooled", ""] + table(res["pooled"]) + [""]
    for typ, v in res["by_type"].items():
        L += [f"## {typ}: {v['n']} trades", ""] + table(v["seps"]) + [""]
    if not res["pooled"]:
        L.append("Too few finished trades to compare conditions yet (needs 16+).")
    L += ["", f"Correction: {res['m']} comparisons were made in this report. SUPPORTED = 30+ trades on each side and p <= 0.05/{res['m']} (Bonferroni, so the chance of ANY false finding in the whole report is at most 5%). HYPOTHESIS = 8+ trades each side and Benjamini-Hochberg false-discovery rate 10%: shown for interest only, never acted on. The range shown is Bonferroni-corrected. Even a SUPPORTED condition is only a candidate: it must also pass the offline validation on unseen history before it can become an entry filter."]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n")
    res["text"] = "\n".join(L)
    return res
