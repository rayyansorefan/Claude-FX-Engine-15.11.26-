"""Pre-registered experiments on H4 (see docs/EXPERIMENTS.md).
Usage: PYTHONPATH=src python -m fxengine.backtest.run2 E1   (or E2)"""
from __future__ import annotations
import json, sys
from pathlib import Path
import pandas as pd
from ..data import store
from ..features.indicators import prepare
from ..research import split, trials
from ..setups import v2
from . import run as bt


def main(exp: str, root="data/candles"):
    bt.TF, bt.TFNAME = pd.Timedelta(hours=4), "H4"
    frames = {}
    for sym in bt.PAIRS:
        d = store.load(sym, "H4", Path(root))
        if d.empty:
            sys.exit(f"missing H4 data for {sym}: run  python -m fxengine.data.build")
        frames[sym] = prepare(split.research_view(d))
    name = {"E1": "E1_strength", "E2": "E2_donchian"}[exp]
    seen = {json.loads(l)["name"] for l in Path("docs/trials.jsonl").open()} if Path("docs/trials.jsonl").exists() else set()
    if f"{name}@H4" not in seen:
        trials.log_trial(f"{name}@H4", {"exp": exp}, "pre-registered in docs/EXPERIMENTS.md")
    n_trials = trials.count_trials()
    sigs = v2.strength_signals(frames) if exp == "E1" else {s: v2.donchian_trend(d) for s, d in frames.items()}
    rows = []
    for sym, d in frames.items():
        rows += bt.run_signals(sym, d, name, sigs[sym])
        print(f"{sym}: {len(rows)} setups so far", flush=True)
    df = pd.DataFrame(rows)
    res = dict(version=f"{exp}-H4", n_trials=n_trials, period=[str(min(f.index.min() for f in frames.values())),
               str(max(f.index.max() for f in frames.values()))], summary=bt.summarise(df, n_trials), spreads={})
    Path("docs/results").mkdir(parents=True, exist_ok=True)
    json.dump(res, open(f"docs/results/{exp}_H4.json", "w"), indent=1, default=str)
    print(bt.render(res))


if __name__ == "__main__":
    main(sys.argv[1])
