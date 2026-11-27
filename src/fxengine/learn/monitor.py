"""Learning pipeline progress monitor: track when each strategy hits decision thresholds.
Run after scorecard() to see how close each strategy is to the next decision point.
Not run-time critical; information-only for dashboards and weekly reports."""
from __future__ import annotations
from . import scorecard as SCORE


def progress(conn) -> dict[str, dict]:
    """Return progress dict per strategy: trades to next decision, current status, timeline estimate."""
    live = SCORE.collect(conn)
    out = {}
    for strategy, results in sorted(live.items()):
        n = len(results)
        out[strategy] = dict(
            n=n,
            to_judge=(SCORE.MIN_JUDGE - n) if n < SCORE.MIN_JUDGE else 0,
            to_decide=(SCORE.MIN_DECIDE - n) if n < SCORE.MIN_DECIDE else 0,
            to_exit_promote=(60 - n) if n < 60 else 0,
            to_rollback=(40 - n) if n < 40 else 0,
            current_status=SCORE.judge(results)["status"],
            mean=SCORE.judge(results)["mean"],
            lo=SCORE.judge(results)["lo"],
            hi=SCORE.judge(results)["hi"],
        )
    return out


def summary_text(conn) -> str:
    """Human-readable progress summary: when is each strategy hitting decision points?"""
    prog = progress(conn)
    if not prog:
        return "No live trades yet. Learning begins at 15 trades per strategy; decisions at 30."

    lines = ["🧪 LEARNING PIPELINE PROGRESS:"]
    for strat, info in sorted(prog.items()):
        status = info["current_status"]
        n = info["n"]

        if n < SCORE.MIN_JUDGE:
            lines.append(f"  {strat}: {n} trades (need {info['to_judge']} more for JUDGMENT)")
        elif n < SCORE.MIN_DECIDE:
            lines.append(f"  {strat}: {n} trades [{status}] (need {info['to_decide']} more for DECISION)")
        elif n < 60:
            lines.append(f"  {strat}: {n} trades [{status}] · exit promotion in {info['to_exit_promote']} trades")
        else:
            lines.append(f"  {strat}: {n} trades [{status}] · exits eligible · rollback eligible at {info['to_rollback']} trades")

    total = sum(info["n"] for info in prog.values())
    if total >= 60:
        lines.append(f"\n✅ Post-mortem: 60+ pooled trades ready. Supported conditions (Bonferroni 5%) can be identified.")
    elif total >= 30:
        lines.append(f"\n⏳ Post-mortem: {total} pooled trades. Hypotheses visible (Benjamini-Hochberg 10%); SUPPORTED needs 60.")
    else:
        lines.append(f"\n🔄 Post-mortem: {total} trades. HYPOTHESIS stage; nothing's decided yet.")

    return "\n".join(lines)


def alert_on_threshold(conn, prev_state: dict | None = None) -> list[str]:
    """Alert lines if any strategy crossed a decision threshold since last check.
    Call this daily to announce which strategies are ready for the next decision."""
    alerts = []
    prog = progress(conn)
    prev_state = prev_state or {}

    for strat, info in prog.items():
        prev_n = prev_state.get(strat, {}).get("n", 0)
        n = info["n"]

        # Threshold crossings
        if prev_n < SCORE.MIN_JUDGE <= n:
            alerts.append(f"🎯 {strat} hit {SCORE.MIN_JUDGE} trades: SCORECARD can now judge.")
        if prev_n < SCORE.MIN_DECIDE <= n:
            status = info["current_status"]
            icon = {"CONFIRMED": "✅", "SUSPENDED": "⛔", "WEAK": "⚠️", "NEUTRAL": "➖"}[status]
            alerts.append(f"🎯 {strat} hit {SCORE.MIN_DECIDE} trades: {status} {icon}")
        if prev_n < 60 <= n:
            alerts.append(f"🎯 {strat} hit 60 pooled trades: EXIT PROMOTION eligible (if Bonferroni SUPPORTED).")
        if prev_n < 40 <= n:
            alerts.append(f"🎯 {strat} hit 40 trades: rollback eligibility starts (if live exit underperforms).")

    return alerts
