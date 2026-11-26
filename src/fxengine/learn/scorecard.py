"""Strategy scorecard: which FX strategies are winning or losing on LIVE trades, and what the engine does about it. Deterministic, zero Claude at runtime. Pre-registered in docs/LEARNING.md (2026-11-26).
Per strategy (setup type), from finished live trades (TARGET / STOP / TIMEOUT, result in R after costs):
  LEARNING   fewer than 15 trades: no judgement.
  NEUTRAL    15+ trades, nothing clear.
  WEAK       15+ trades and the shrunk mean (n/(n+30) x mean) is below -0.25R: shown with a warning, still taken.
  CONFIRMED  30+ trades and the 95% range of the mean R is entirely above 0: REINFORCED (marked, announced; first call on cash if cash is short is a later step, see docs).
  SUSPENDED  30+ trades and the 95% range is entirely below 0: PROBATION. New setups of this strategy are still PUBLISHED and SCORED (the research and forward test are untouched) but are NOT TAKEN in the GBP 2,500 account.
Reversible: the status is recomputed from all live trades every time; a suspended strategy whose range returns to include 0 is taken again. Nothing changes any rule, gate or parameter of a strategy.
The bars are deliberately strict (30 trades, 95% range): a handful of trades can only ever change the label to LEARNING/NEUTRAL/WEAK, never switch a strategy off."""
from __future__ import annotations
import math
import statistics

MIN_JUDGE = 15
MIN_DECIDE = 30
SHRINK_K = 30
WEAK_BELOW = -0.25


def collect(conn) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for r in conn.execute("SELECT s.type, o.net_r FROM outcomes o JOIN setups s USING(run_id) WHERE o.reason IN ('TARGET','STOP','TIMEOUT') AND o.net_r IS NOT NULL"):
        out.setdefault(r[0], []).append(float(r[1]))
    return out


def judge(rs: list[float]) -> dict:
    n = len(rs)
    mean = statistics.mean(rs) if n else 0.0
    sd = statistics.stdev(rs) if n > 1 else 0.0
    half = 1.96 * sd / math.sqrt(n) if n > 1 else float("inf")
    lo, hi = mean - half, mean + half
    shrunk = n * mean / (n + SHRINK_K)
    if n < MIN_JUDGE:
        status = "LEARNING"
    elif n >= MIN_DECIDE and lo > 0:
        status = "CONFIRMED"
    elif n >= MIN_DECIDE and hi < 0:
        status = "SUSPENDED"
    elif shrunk < WEAK_BELOW:
        status = "WEAK"
    else:
        status = "NEUTRAL"
    return dict(n=n, wins=sum(x > 0 for x in rs), mean=mean, lo=lo, hi=hi, shrunk=shrunk, status=status)


def scorecard(conn) -> dict[str, dict]:
    return {k: judge(v) for k, v in collect(conn).items()}


def suspended(conn) -> set[str]:
    try:
        return {k for k, v in scorecard(conn).items() if v["status"] == "SUSPENDED"}
    except Exception:
        return set()                                      # never block publishing because the scorecard failed


def summary_lines(conn) -> list[str]:
    """Three lines for Telegram."""
    sc = scorecard(conn)
    n = sum(v["n"] for v in sc.values())
    if not sc:
        return ["📊 SCORECARD · no finished live trades yet.", "Judging starts at 15 trades per strategy; changes only at 30.", "Nothing is switched off or favoured before that."]
    order = sorted(sc.items(), key=lambda kv: -kv[1]["mean"])
    best, worst = order[0], order[-1]
    icon = {"CONFIRMED": "✅", "SUSPENDED": "⛔", "WEAK": "⚠️", "NEUTRAL": "➖", "LEARNING": "⏳"}
    counts = {s: sum(1 for v in sc.values() if v["status"] == s) for s in icon}
    return [f"📊 SCORECARD · {n} finished trades across {len(sc)} strategies.",
            f"Best {best[0]} {best[1]['mean']:+.2f}R (n={best[1]['n']}) {icon[best[1]['status']]} · worst {worst[0]} {worst[1]['mean']:+.2f}R (n={worst[1]['n']}) {icon[worst[1]['status']]}",
            f"✅ {counts['CONFIRMED']} confirmed · ⛔ {counts['SUSPENDED']} suspended · ⚠️ {counts['WEAK']} weak · ⏳ {counts['LEARNING']} still learning (needs 15; decisions at 30)."]
