"""One command: E1 + E2 (+ E3 filters if due), applies the pre-registered decision rule in docs/EXPERIMENTS.md.
PYTHONPATH=src python -m fxengine.backtest.run_all"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd
from ..data import store
from ..features.indicators import prepare
from ..research import split, trials
from ..setups import v2
from . import run as bt

H4 = pd.Timedelta(hours=4)


def verdict(df: pd.DataFrame, n_trials: int) -> dict:
    sc = df[df.triggered & (df.reason != "OPEN")]
    s = bt.summarise(df, n_trials)["ALL"] if len(sc) else {}
    yrs = sc.groupby(sc.created.dt.year).net_r.mean()
    best_pair = sc.groupby("symbol").net_r.sum().idxmax() if len(sc) else None
    ex_best = sc[sc.symbol != best_pair].net_r.mean() if len(sc) else float("nan")
    ok = dict(n=len(sc) >= 100, ci=bool(s) and s["ci_bonferroni_lo"] > 0,
              years=int((yrs > 0).sum()) >= min(3, len(yrs)) and len(yrs) >= 3,
              pairs=bool(ex_best > 0))
    return dict(n=int(len(sc)), exp=round(float(sc.net_r.mean()), 3) if len(sc) else None,
                lo=s.get("ci_bonferroni_lo"), years={int(k): round(v, 3) for k, v in yrs.items()},
                ex_best_pair=round(float(ex_best), 3) if len(sc) else None, checks=ok, PASS=all(ok.values()))


def e3_filter(sig: pd.DataFrame, d: pd.DataFrame, kind: str) -> pd.DataFrame:
    created = d.index[sig.pos] + H4
    if kind == "session":
        keep = (created.hour >= 7) & (created.hour <= 17)
    else:  # skip first Friday of the month
        keep = ~((created.dayofweek == 4) & (created.day <= 7))
    return sig[np.asarray(keep)].reset_index(drop=True)


def run_exp(frames, name, sigs):
    rows = []
    for sym, d in frames.items():
        rows += bt.run_signals(sym, d, name, sigs[sym])
    return pd.DataFrame(rows)


def fmt(label, v):
    return (f"{label}: n={v['n']} exp={v['exp']}R penalised-low={v['lo']} years={v['years']} "
            f"ex-best-pair={v['ex_best_pair']} -> {'PASS' if v['PASS'] else 'FAIL'} {v['checks']}")


def main(root="data/candles", reg=Path("docs/trials.jsonl"), out=Path("docs/results")):
    bt.TF, bt.TFNAME = H4, "H4"
    frames = {}
    for sym in bt.PAIRS:
        d = store.load(sym, "H4", Path(root))
        if d.empty:
            sys.exit(f"missing H4 data for {sym}: run  python -m fxengine.data.build")
        frames[sym] = prepare(split.research_view(d))
    seen = {json.loads(l)["name"] for l in reg.open()} if reg.exists() else set()

    def log(n):
        if n not in seen:
            trials.log_trial(n, {"exp": n}, "pre-registered in docs/EXPERIMENTS.md", reg=reg)
            seen.add(n)
    log("E1_strength@H4"); log("E2_donchian@H4")
    sig1 = v2.strength_signals(frames)
    sig2 = {s: v2.donchian_trend(d) for s, d in frames.items()}
    res, lines = {}, []
    for exp, name, sigs in (("E1", "E1_strength", sig1), ("E2", "E2_donchian", sig2)):
        df = run_exp(frames, name, sigs)
        res[exp] = verdict(df, trials.count_trials(reg))
        res[exp]["_df"] = df
        lines.append(fmt(exp, res[exp]))
        print(lines[-1], flush=True)
    best = max(("E1", "E2"), key=lambda e: res[e]["exp"] if res[e]["exp"] is not None else -9)
    promising = res[best]["lo"] is not None and res[best]["lo"] > -0.05
    if promising:
        sigs = sig1 if best == "E1" else sig2
        name = "E1_strength" if best == "E1" else "E2_donchian"
        for kind in ("session", "nfp"):
            log(f"E3_{best}_{kind}@H4")
            fs = {s: e3_filter(sigs[s], frames[s], kind) for s in frames}
            df = run_exp(frames, name + "+" + kind, fs)
            v = verdict(df, trials.count_trials(reg))
            res[f"E3_{kind}"] = v
            lines.append(fmt(f"E3 {best}+{kind} (setups {res[best]['n']}->{v['n']})", v))
            print(lines[-1], flush=True)
    passed = [k for k, v in res.items() if v["PASS"]]
    final = ("CANDIDATE(S) PASS research gate: " + ", ".join(passed) + " (holdout + forward test still required)"
             if passed else "NO EDGE FOUND: all pre-registered experiments failed (E3 " + ("run" if promising else "not due") + ").")
    lines.append(""); lines.append("VERDICT: " + final)
    print("\n" + lines[-1])
    out.mkdir(parents=True, exist_ok=True)
    (out / "experiments_summary.md").write_text("# Experiments E1-E3 result\n\n" + "\n".join(f"- {l}" for l in lines if l) + "\n")
    json.dump({k: {a: b for a, b in v.items() if a != "_df"} for k, v in res.items()},
              open(out / "experiments_summary.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
