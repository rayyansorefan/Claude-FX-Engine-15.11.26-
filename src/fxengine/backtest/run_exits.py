"""Pre-registered EXIT-RULE test (docs/EXPERIMENTS.md): would taking profit earlier after a trade has been well in profit beat the frozen exits?
Same signals, same fills, same costs as the live H1 rules (v1_H1 at M5 resolution); only the exit changes after the trade is >= +1R at its best.
Statistic: per-trade paired difference (variant minus baseline), cluster-bootstrapped by pair-day, multiple-testing penalised.
Nothing here changes live behaviour: a passing rule is only a CANDIDATE for a new frozen version.
Usage: PYTHONPATH=src python -m fxengine.backtest.run_exits  -> docs/results/exits.{json,md}"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd
from ..data import store
from ..data.resample import resample
from ..data.timeframes import tf_delta
from ..engine.tracker import bar_arrays, track_arrays
from ..features.indicators import prepare
from ..research import split, stats, trials
from . import run_m5 as M

RULES = {                                  # name -> stop level in R above/below the fill once peak >= TRIGGER_R (None = trails with peak)
    "X1_breakeven_after_1R": ("fixed", 0.0),
    "X2_lock_half_after_1R": ("fixed", 0.5),
    "X3_trail_1R_behind_peak": ("behind", 1.0),
    "X4_keep_half_of_peak": ("share", 0.5),
}
TRIGGER_R = 1.0
FIVE = M.FIVE
MODES = ("stressed", "measured")


def exit_hook(rule, arr):
    kind, x = RULES[rule]
    ot, o, h, l, c, sp = arr

    def hook(t, j):
        if t.fill is None or not t.active or t.mfe < TRIGGER_R:
            return
        sign = 1 if t.s.direction == "long" else -1
        lvl = x if kind == "fixed" else (t.mfe - x if kind == "behind" else x * t.mfe)
        new = t.fill + sign * lvl * t.s.risk
        close = c[j]
        if (sign == 1 and new <= t.stop) or (sign == -1 and new >= t.stop):
            return                                              # never loosens a stop
        if (sign == 1 and new < close) or (sign == -1 and new > close):
            t.adjust(ot[j] + FIVE, stop=float(new), detail=f"rule {rule}")
        else:                                                   # price already beyond the protective level: leave at the close
            spread = t.cost.spread(t.s.symbol, ot[j], sp[j] if sp is not None else None)
            t.exit_at_close(ot[j] + FIVE, float(close), spread, reason="RULE_EXIT")
    return hook


def run(frames, m5s, sigs, tf):
    rows = []
    cur, arr = None, None
    for (sym, stype), sig in sigs.items():
        d, m5 = frames[sym], m5s[sym]
        if sym != cur:
            cur, arr = sym, bar_arrays(m5)
        free_until = pd.Timestamp.min.tz_localize("UTC")
        for row in sig.itertuples():
            created = d.index[row.pos] + tf
            if created < free_until:
                continue
            j0 = int(m5.index.searchsorted(created))
            if j0 >= len(m5):
                continue
            s = M._setup(row, sym, stype, d, tf, True)
            base = {k: M.track_m5(s, arr, j0, M.COSTS[k]) for k in MODES}
            tb = base["stressed"]
            free_until = tb.events[-1]["ts"]
            if tb.fill is None or tb.outcome is None:
                continue
            rec = dict(symbol=sym, type=stype, created=created, day=f"{sym}-{created:%Y%m%d}", peak_r=tb.outcome.mfe_r,
                       **{f"base_{k}": (base[k].outcome.net_r if base[k].outcome and base[k].fill is not None else np.nan) for k in MODES})
            for rule in RULES:
                for k in MODES:
                    t = M.track_m5(s, arr, j0, M.COSTS[k], exit_hook(rule, arr))
                    rec[f"{rule}_{k}"] = t.outcome.net_r if t.outcome and t.fill is not None else np.nan
            rows.append(rec)
    return pd.DataFrame(rows)


def summarise(df, n_trials):
    out = {}
    half = df.created.sort_values().iloc[len(df) // 2] if len(df) else None
    for rule in RULES:
        res = {}
        for k in MODES:
            ok = df[f"base_{k}"].notna() & df[f"{rule}_{k}"].notna()
            d = df[ok]
            delta = (d[f"{rule}_{k}"] - d[f"base_{k}"]).values
            if len(d) < 100:
                res[k] = dict(n=int(len(d)), verdict="too few trades"); continue
            a = stats.adjusted_alpha(n_trials)
            lo, hi = stats.cluster_bootstrap_ci(delta, d.day.values, a * 2)
            early, late = delta[(d.created < half).values], delta[(d.created >= half).values]
            reach = d.peak_r >= TRIGGER_R
            res[k] = dict(n=int(len(d)), reached_1R=int(reach.sum()), base_mean=round(float(d[f"base_{k}"].mean()), 4),
                          rule_mean=round(float(d[f"{rule}_{k}"].mean()), 4), delta=round(float(delta.mean()), 4),
                          ci_lo=round(float(lo), 4), ci_hi=round(float(hi), 4),
                          delta_first_half=round(float(early.mean()), 4), delta_second_half=round(float(late.mean()), 4),
                          winners_cut_short=round(float(((d[f"{rule}_{k}"] < d[f"base_{k}"] - 0.3) & (d[f"base_{k}"] > 0)).mean()), 4),
                          losers_saved=round(float(((d[f"{rule}_{k}"] > d[f"base_{k}"] + 0.3) & (d[f"base_{k}"] < 0)).mean()), 4),
                          candidate=bool(lo > 0 and early.mean() > 0 and late.mean() > 0))
        out[rule] = res
    for rule, res in out.items():
        res["passes"] = all(res[k].get("candidate") for k in MODES)
    return out


def render(res) -> str:
    L = ["# Exit-rule test (pre-registered): take profit earlier once a trade has been >= +1R?", "",
         f"Rules tested: {', '.join(RULES)}. Trades: live H1 rules at M5 resolution, research window only. Trials counted: {res['n_trials']} (alpha = 0.05/{res['n_trials']}).",
         "Delta = rule result minus the frozen exit, per trade (R). A rule is a CANDIDATE only if the penalised lower bound is > 0 under stressed AND measured costs and both halves are positive.",
         "", "| rule | cost | trades | reached +1R | frozen exit | with rule | delta | 95% CI (clustered) | 1st / 2nd half | winners cut short | losers saved | candidate |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for rule, r in res["summary"].items():
        for k in MODES:
            s = r[k]
            if "delta" not in s:
                L.append(f"| {rule} | {k} | {s['n']} | {s['verdict']} ||||||||"); continue
            L.append(f"| {rule} | {k} | {s['n']} | {s['reached_1R']} | {s['base_mean']:+.3f} | {s['rule_mean']:+.3f} | {s['delta']:+.3f} | [{s['ci_lo']:+.3f}, {s['ci_hi']:+.3f}] | "
                     f"{s['delta_first_half']:+.3f} / {s['delta_second_half']:+.3f} | {s['winners_cut_short']:.1%} | {s['losers_saved']:.1%} | {'YES' if s['candidate'] else 'no'} |")
    L += ["", "Verdict: " + ("; ".join(f"{k} passes" for k, v in res["summary"].items() if v["passes"]) or "no exit rule beats the frozen exit under both cost models. Live rules stay unchanged."), ""]
    return "\n".join(L)


def main(root="data/candles", reg=Path("docs/trials.jsonl"), out=Path("docs/results")):
    def load_m5(sym):
        d = store.load(sym, "M5", Path(root))
        if d.empty:
            sys.exit(f"missing M5 data for {sym}")
        return split.research_view(d)
    m5s = M.PairCache(M.PAIRS, load_m5)
    if all(len(m5s[s]) == 0 for s in M.PAIRS):
        sys.exit("research window empty: run the history job first")
    tf = tf_delta("H1")
    frames = M.PairCache(M.PAIRS, lambda s: prepare(resample(m5s[s], "H1", base="M5")))
    df_parts = []
    for sym in M.PAIRS:
        one = {sym: frames[sym]}
        df_parts.append(run(one, {sym: m5s[sym]}, M.signals_for("v1_H1", one), tf))
    df = pd.concat([p for p in df_parts if len(p)], ignore_index=True) if any(len(p) for p in df_parts) else pd.DataFrame()
    if df.empty:
        sys.exit("no scored trades")
    seen = {json.loads(l)["name"] for l in reg.open()} if reg.exists() else set()
    new = [r for r in RULES if r not in seen]
    n_trials = trials.count_trials(reg) + len(new)
    res = dict(n_trials=n_trials, trades=int(len(df)), summary=summarise(df, n_trials))
    for r in new:
        trials.log_trial(r, {"trigger_r": TRIGGER_R}, "exit-rule test, pre-registered in docs/EXPERIMENTS.md", reg=reg)
    Path("data").mkdir(exist_ok=True)
    df.to_parquet("data/exits_h1.parquet")
    out.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(out / "exits.json", "w"), indent=1, default=str)
    (out / "exits.md").write_text(render(res))
    print(render(res))
    return res


if __name__ == "__main__":
    main()
