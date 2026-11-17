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

RULES = {                                  # name -> (kind, trigger R, parameter). Only ever TIGHTENS a stop; never closes at market.
    "A1_breakeven_at_0.75R": ("fixed", 0.75, 0.0), "A2_breakeven_at_1R": ("fixed", 1.0, 0.0), "A3_breakeven_at_1.5R": ("fixed", 1.5, 0.0),
    "B1_trail_0.5R_behind_peak": ("behind", 1.0, 0.5), "B2_trail_1R_behind_peak": ("behind", 1.0, 1.0), "B3_trail_1.5R_behind_peak": ("behind", 1.0, 1.5),
    "C1_keep_40pc_of_peak": ("share", 1.0, 0.4), "C2_keep_50pc_of_peak": ("share", 1.0, 0.5), "C3_keep_60pc_of_peak": ("share", 1.0, 0.6),
}
BUFFER_R = 0.15                            # the protective stop is always at least this far behind the current price: no instant exits
FIVE = M.FIVE
MODES = ("stressed", "measured")


def exit_hook(rule, arr):
    kind, trigger, x = RULES[rule]
    ot, o, h, l, c, sp = arr

    def hook(t, j):
        if t.fill is None or not t.active or t.mfe < trigger:
            return
        sign = 1 if t.s.direction == "long" else -1
        lvl = x if kind == "fixed" else (t.mfe - x if kind == "behind" else x * t.mfe)
        new = t.fill + sign * lvl * t.s.risk
        new = min(new, c[j] - BUFFER_R * t.s.risk) if sign == 1 else max(new, c[j] + BUFFER_R * t.s.risk)   # leave the trade room to run
        if (sign == 1 and new <= t.stop) or (sign == -1 and new >= t.stop):
            return                                              # never loosens a stop
        t.adjust(ot[j] + FIVE, stop=float(new), detail=f"rule {rule}")
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
    """Walk-forward selection: pick the best rule on the EARLIER half (stressed costs), then test ONLY that rule on the LATER half it never saw."""
    df = df.sort_values("created").reset_index(drop=True)
    cut = df.created.iloc[len(df) // 2]
    disc, val = df[df.created < cut], df[df.created >= cut]
    def delta(d, rule, k):
        ok = d[f"base_{k}"].notna() & d[f"{rule}_{k}"].notna()
        return d[ok], (d[ok][f"{rule}_{k}"] - d[ok][f"base_{k}"]).values
    table = {}
    for rule in RULES:
        row = {}
        for k in MODES:
            dd, dl = delta(disc, rule, k)
            vd, vl = delta(val, rule, k)
            row[k] = dict(n_disc=int(len(dl)), delta_disc=round(float(dl.mean()), 4) if len(dl) else None,
                          n_val=int(len(vl)), delta_val=round(float(vl.mean()), 4) if len(vl) else None)
        table[rule] = row
    best = max(RULES, key=lambda r: table[r]["stressed"]["delta_disc"] if table[r]["stressed"]["delta_disc"] is not None else -9)
    out = dict(cut=str(cut), best_on_first_half=best, table=table, validation={})
    for k in MODES:
        vd, vl = delta(val, best, k)
        if len(vl) < 100:
            out["validation"][k] = dict(n=int(len(vl)), verdict="too few trades"); continue
        lo, hi = stats.cluster_bootstrap_ci(vl, vd.day.values, 0.05 * 2)           # ONE pre-selected rule, one test: alpha 0.05 one-sided
        out["validation"][k] = dict(n=int(len(vl)), base_mean=round(float(vd[f"base_{k}"].mean()), 4), rule_mean=round(float(vd[f"{best}_{k}"].mean()), 4),
                                    delta=round(float(vl.mean()), 4), ci_lo=round(float(lo), 4), ci_hi=round(float(hi), 4),
                                    winners_cut_short=round(float(((vd[f"{best}_{k}"] < vd[f"base_{k}"] - 0.3) & (vd[f"base_{k}"] > 0)).mean()), 4),
                                    losers_saved=round(float(((vd[f"{best}_{k}"] > vd[f"base_{k}"] + 0.3) & (vd[f"base_{k}"] < 0)).mean()), 4),
                                    candidate=bool(lo > 0))
    out["passes"] = all(v.get("candidate") for v in out["validation"].values())
    return out


def render(res) -> str:
    sm = res["summary"]
    L = ["# Exit-rule test (pre-registered): does protecting profit after a good run beat the frozen exits?", "",
         f"{len(RULES)} rules, none closes at market (each only places a protective stop at least {BUFFER_R}R behind price). Live H1 rules at M5 resolution, research window only. "
         f"Trials counted: {res['n_trials']}.", f"Method: choose the best rule on the earlier half of history (before {sm['cut'][:10]}), then test ONLY that rule on the later half.",
         "", "Every rule, change in average result per trade (R, positive = better than the frozen exit), earlier half | later half, stressed costs:", "",
         "| rule | earlier half | later half | trades (later) |", "|---|---|---|---|"]
    for rule, row in sm["table"].items():
        s_ = row["stressed"]
        L.append(f"| {rule}{' **(chosen)**' if rule == sm['best_on_first_half'] else ''} | {s_['delta_disc']:+.3f} | {s_['delta_val']:+.3f} | {s_['n_val']} |")
    L += ["", f"Chosen on the earlier half: **{sm['best_on_first_half']}**. Test on the later half it never saw:", "",
          "| cost | trades | frozen exit | with rule | delta | 95% CI (clustered) | winners cut short | losers saved | candidate |", "|---|---|---|---|---|---|---|---|---|"]
    for k in MODES:
        v = sm["validation"][k]
        if "delta" not in v:
            L.append(f"| {k} | {v['n']} | {v['verdict']} |||||||"); continue
        L.append(f"| {k} | {v['n']} | {v['base_mean']:+.3f} | {v['rule_mean']:+.3f} | {v['delta']:+.3f} | [{v['ci_lo']:+.3f}, {v['ci_hi']:+.3f}] | {v['winners_cut_short']:.1%} | {v['losers_saved']:.1%} | {'YES' if v['candidate'] else 'no'} |")
    L += ["", "Verdict: " + (f"{sm['best_on_first_half']} is a CANDIDATE (beats the frozen exit on unseen data under both cost models); it still needs a forward test before any live change."
                            if sm["passes"] else "the best rule does not beat the frozen exit on unseen data under both cost models. Live rules stay unchanged."), ""]
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
        trials.log_trial(r, {"grid": 9}, "exit-rule test, pre-registered in docs/EXPERIMENTS.md", reg=reg)
    Path("data").mkdir(exist_ok=True)
    df.to_parquet("data/exits_h1.parquet")
    out.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(out / "exits.json", "w"), indent=1, default=str)
    (out / "exits.md").write_text(render(res))
    print(render(res))
    return res


if __name__ == "__main__":
    main()
