"""Your-trades analytics (paper account). Input: data/journal.csv, one row per closed trade you took.
Columns: opened,closed,pair,direction,lots,entry,exit,pnl_gbp,run_id,note   (run_id = the engine setup you followed; blank = off-plan)
Evidence from the research: the only thing with even suggestive support is behavioural feedback (plan adherence, overtrading,
cost awareness), not predictions. So that is what this measures. Deterministic; no Claude."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from ..research import stats

RISK = 20.0
CAP_PER_DAY = 5


def load(path="data/journal.csv"):
    p = Path(path)
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["opened", "closed"])
    return df if len(df) else None


def analyse(df: pd.DataFrame) -> dict:
    pnl = df.pnl_gbp.astype(float)
    r = pnl / RISK
    win, loss = pnl[pnl > 0], pnl[pnl <= 0]
    on = df.run_id.fillna("").astype(str).str.len() > 0
    cum = pnl.cumsum()
    dd = float((cum.cummax() - cum).max())
    streak = best = 0
    for v in pnl:
        streak = streak + 1 if v <= 0 else 0
        best = max(best, streak)
    lo, hi = stats.bootstrap_ci(r.values, n=2000) if len(r) > 2 else (float("nan"), float("nan"))
    per_day = df.groupby(df.opened.dt.date).size()
    hrs = df.opened.dt.hour
    sess = {"Asia 00-07": pnl[hrs < 7].sum(), "London 07-12": pnl[(hrs >= 7) & (hrs < 12)].sum(),
            "Overlap/NY 12-21": pnl[(hrs >= 12) & (hrs < 21)].sum(), "Late 21-24": pnl[hrs >= 21].sum()}
    return dict(n=len(df), win_rate=float((pnl > 0).mean()), total=float(pnl.sum()), exp_gbp=float(pnl.mean()), exp_r=float(r.mean()),
                ci_r=(float(lo), float(hi)), avg_win=float(win.mean()) if len(win) else 0.0, avg_loss=float(loss.mean()) if len(loss) else 0.0,
                profit_factor=float(win.sum() / abs(loss.sum())) if loss.sum() < 0 else float("inf"),
                on_plan=float(on.mean()), pnl_on=float(pnl[on].sum()), pnl_off=float(pnl[~on].sum()), n_off=int((~on).sum()),
                days_over_cap=int((per_day > CAP_PER_DAY).sum()), max_per_day=int(per_day.max()), max_dd=dd, worst_streak=best, sessions=sess,
                needed=max(0, 100 - len(df)))


def panel(df) -> str:
    if df is None:
        return ("<p class='muted'><b style='color:var(--ink)'>No trades logged yet.</b> Add each paper trade you take to "
                "<span class='mono'>data/journal.csv</span> (template: docs/journal_template.csv). This panel then shows plan adherence, "
                "overtrading, costs of going off-plan, and when you lose money. It measures you, not the market.</p>")
    a = analyse(df)
    up = lambda v: "up" if v > 0 else "dn"
    k = [("Trades", f"{a['n']}", f"{a['needed']} more for a fair read"), ("Net P&L", f"£{a['total']:+.0f}", f"avg £{a['exp_gbp']:+.1f} / trade"),
         ("Win rate", f"{a['win_rate'] * 100:.0f}%", f"avg win £{a['avg_win']:.0f} · loss £{a['avg_loss']:.0f}"),
         ("Plan adherence", f"{a['on_plan'] * 100:.0f}%", f"off-plan P&L £{a['pnl_off']:+.0f} ({a['n_off']} trades)"),
         ("Overtrading", f"{a['days_over_cap']} days", f"over the {CAP_PER_DAY}/day cap · max {a['max_per_day']}"),
         ("Max drawdown", f"£{a['max_dd']:.0f}", f"worst losing streak {a['worst_streak']}")]
    tiles = "".join(f"<div class='kpi'><small>{x}</small><b>{y}</b><span>{z}</span></div>" for x, y, z in k)
    mx = max(abs(v) for v in a["sessions"].values()) or 1
    bars = "".join(f"<div class='frow'><span>{n}</span><div class='fbar'><b style='width:{abs(v) / mx * 100:.0f}%;background:{'var(--good)' if v > 0 else 'var(--crit)'}'></b></div><em class='{up(v)}'>£{v:+.0f}</em></div>"
                   for n, v in a["sessions"].items())
    lo, hi = a["ci_r"]
    return (f"<div class='kpis' style='margin:0 0 10px'>{tiles}</div><div class='grid'><div class='c6'><small class='muted'>P&L by time of day (UTC)</small>{bars}</div>"
            f"<div class='c6'><small class='muted'>Expectancy per trade</small><p class='mono' style='font-size:20px;margin:6px 0'>"
            f"<span class='{up(a['exp_r'])}'>{a['exp_r']:+.2f}R</span></p><small class='muted'>95% range {lo:+.2f}R to {hi:+.2f}R. "
            f"{'Too few trades to tell skill from luck.' if a['n'] < 100 else 'Enough trades for a first read.'}</small></div></div>")
