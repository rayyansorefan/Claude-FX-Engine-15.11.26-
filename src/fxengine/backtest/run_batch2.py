"""Batch 2 (E4, E5): trailing exits. PYTHONPATH=src python -m fxengine.backtest.run_batch2"""
from __future__ import annotations
import json, sys
from pathlib import Path
import pandas as pd
from ..data import store
from ..features.indicators import prepare
from ..research import split, trials
from ..setups import v2
from . import run as bt
from .run_all import verdict, fmt, H4

TRAIL = 20


def main(root="data/candles", reg=Path("docs/trials.jsonl"), out=Path("docs/results")):
    bt.TF, bt.TFNAME = H4, "H4"
    frames = {}
    for sym in bt.PAIRS:
        d = store.load(sym, "H4", Path(root))
        if d.empty:
            sys.exit(f"missing H4 data for {sym}: run  python -m fxengine.data.build")
        frames[sym] = prepare(split.research_view(d))
    seen = {json.loads(l)["name"] for l in reg.open()} if reg.exists() else set()
    for n in ("E4_donchian_trail@H4", "E5_strength_trail@H4"):
        if n not in seen:
            trials.log_trial(n, {"trail": TRAIL}, "pre-registered batch 2 in docs/EXPERIMENTS.md", reg=reg)
    sig5 = v2.strength_signals(frames)
    cfg = {"E4": ("E4_donchian_trail", {s: v2.with_trailing(v2.donchian_trend(d), 5, 120) for s, d in frames.items()}),
           "E5": ("E5_strength_trail", {s: v2.with_trailing(sig5[s], 5, 60) for s in frames})}
    lines, res = [], {}
    for exp, (name, sigs) in cfg.items():
        rows = []
        for sym, d in frames.items():
            rows += bt.run_signals(sym, d, name, sigs[sym], trail=TRAIL)
        df = pd.DataFrame(rows)
        res[exp] = verdict(df, trials.count_trials(reg))
        sc = df[df.triggered]
        extra = f" win={round((sc.net_r > 0).mean() * 100)}% avgWin={round(sc.net_r[sc.net_r > 0].mean(), 2)}R avgLoss={round(sc.net_r[sc.net_r <= 0].mean(), 2)}R"
        lines.append(fmt(exp, res[exp]) + extra)
        print(lines[-1], flush=True)
    passed = [k for k, v in res.items() if v["PASS"]]
    final = ("CANDIDATE(S) PASS research gate: " + ", ".join(passed) + " (holdout + forward test still required)"
             if passed else "NO EDGE FOUND in batch 2 either. Search ends here unless you propose an idea.")
    print("\nVERDICT: " + final)
    out.mkdir(parents=True, exist_ok=True)
    (out / "batch2_summary.md").write_text("# Batch 2 (E4, E5)\n\n" + "\n".join(f"- {l}" for l in lines) + f"\n\nVERDICT: {final}\n")


if __name__ == "__main__":
    main()
