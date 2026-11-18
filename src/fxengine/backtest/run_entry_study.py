"""Pre-registered ENTRY-FILTER study (docs/EXPERIMENTS.md): do conditions recorded at signal time (volatility, trend strength, stretch, 4h trend,
session, weekday) separate better setups from worse ones, per rule, on data the filter was NOT chosen on?
Inputs: the R0 result files (data/m5_rerun_*.parquet: per-trade net R under each cost model) + the same signals recomputed for their context.
Method per rule: earlier 60% of trades = DISCOVERY (pick the best of the fixed family of 12 single + 66 paired conditions, keeping >= 40% of trades);
later 40% = VALIDATION (one pre-selected filter, one test, both cost models). Pass = lower bound of (kept mean - all mean) > 0 under both costs
AND the kept mean beats the 95th percentile of random subsets of the same size. A pass is a CANDIDATE for ops/filters.json, never auto-applied.
Usage: PYTHONPATH=src python -m fxengine.backtest.run_entry_study -> docs/results/entries.{json,md}"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd
from ..data import store
from ..data.resample import resample
from ..data.timeframes import tf_delta
from ..features import context as CTX
from ..features.indicators import prepare
from ..learn import filters as FL
from ..research import split, trials
from . import run_m5 as M

VARIANTS = [("v1_H1", "H1"), ("E1_strength", "H4"), ("E2_donchian", "H4")]
MODES = ("stressed", "measured")
KEEP_MIN, N_MIN, DISC_FRAC = 0.40, 150, 0.60
H4 = pd.Timedelta(hours=4)


def context_table(variant, tfname, frames_tf, h4_frames):
    tf = tf_delta(tfname)
    rows = []
    for (sym, stype), sig in M.signals_for(variant, frames_tf).items():
        d, h4 = frames_tf[sym], h4_frames[sym]
        for r in sig.itertuples():
            created = d.index[r.pos] + tf
            h = h4[h4.index + H4 <= created].iloc[-1:]
            rows.append(dict(symbol=sym, type=stype, created=created, direction=r.direction, **CTX.snapshot(d, int(r.pos), r.direction, None, h)))
    return pd.DataFrame(rows)


def join(trades: pd.DataFrame, ctx: pd.DataFrame) -> pd.DataFrame:
    t = trades.copy()
    t["created"] = pd.to_datetime(t["created"], utc=True)
    ctx = ctx.copy(); ctx["created"] = pd.to_datetime(ctx["created"], utc=True)
    return t.merge(ctx.drop_duplicates(["symbol", "type", "created"]), on=["symbol", "type", "created"], how="inner")


def _r(df, k):
    ok = df[f"trig_{k}"] & (df.reason != "OPEN")
    return df[ok]


def choose(disc: pd.DataFrame):
    d = _r(disc, "stressed")
    best = None
    for atoms in FL.candidates():
        m = FL.mask(d, atoms)
        if m.mean() < KEEP_MIN or m.sum() < N_MIN:
            continue
        mean = float(d.loc[m, "net_r_stressed"].mean())
        if best is None or mean > best[0]:
            best = (mean, atoms, float(m.mean()))
    return best


def _clustered_diff(r_all, keep, clusters, n=2000, seed=7, alpha=0.05):
    """Cluster bootstrap CI of (mean of kept) - (mean of all)."""
    keys, inv = np.unique(clusters, return_inverse=True)
    k = len(keys)
    s_all, n_all = np.bincount(inv, weights=r_all, minlength=k), np.bincount(inv, minlength=k).astype(float)
    s_kp, n_kp = np.bincount(inv, weights=r_all * keep, minlength=k), np.bincount(inv, weights=keep.astype(float), minlength=k)
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n // 100):
        idx = rng.integers(0, k, size=(100, k))
        a = s_all[idx].sum(1) / np.maximum(n_all[idx].sum(1), 1)
        b = s_kp[idx].sum(1) / np.maximum(n_kp[idx].sum(1), 1)
        out.append(b - a)
    diff = np.concatenate(out)
    return float(np.quantile(diff, alpha)), float(np.quantile(diff, 1 - alpha))


def evaluate(df: pd.DataFrame, n_tests: int) -> dict:
    df = df.sort_values("created").reset_index(drop=True)
    cut = df.created.iloc[int(len(df) * DISC_FRAC)]
    disc, val = df[df.created < cut], df[df.created >= cut]
    best = choose(disc)
    base = {k: float(_r(df, k)[f"net_r_{k}"].mean()) for k in MODES if len(_r(df, k))}
    if best is None:
        return dict(n=int(len(df)), cut=str(cut), base_all=base, verdict="no filter keeps enough trades to test")
    mean_d, atoms, frac = best
    out = dict(n=int(len(df)), cut=str(cut), base_all=base, filter=list(atoms), discovery_mean=round(mean_d, 4), discovery_keep=round(frac, 3), validation={})
    rng = np.random.default_rng(3)
    for k in MODES:
        v = _r(val, k)
        if len(v) < 100:
            out["validation"][k] = dict(n=int(len(v)), verdict="too few trades"); continue
        keep = FL.mask(v, atoms).values
        r = v[f"net_r_{k}"].values
        lo, hi = _clustered_diff(r, keep, v.day.values, alpha=0.05 / max(n_tests, 1))
        kept_mean = float(r[keep].mean()) if keep.any() else float("nan")
        draws = [r[rng.choice(len(r), size=int(keep.sum()), replace=False)].mean() for _ in range(2000)]
        out["validation"][k] = dict(n=int(len(r)), kept=int(keep.sum()), all_mean=round(float(r.mean()), 4), kept_mean=round(kept_mean, 4), delta=round(kept_mean - float(r.mean()), 4),
                                    ci_lo=round(lo, 4), ci_hi=round(hi, 4), random_p95=round(float(np.quantile(draws, 0.95)), 4), beats_random=bool(kept_mean > np.quantile(draws, 0.95)),
                                    profitable=bool(kept_mean > 0), candidate=bool(lo > 0 and kept_mean > np.quantile(draws, 0.95)))
    out["passes"] = all(v.get("candidate") for v in out["validation"].values()) and len(out["validation"]) == len(MODES)
    return out


def render(res) -> str:
    L = ["# Entry-filter study (pre-registered): do conditions at signal time separate better setups from worse ones?", "",
         f"Fixed family: 12 single + 66 paired conditions (learn/filters.py). Chosen on the earlier {int(DISC_FRAC * 100)}% of each rule's trades, tested ONCE on the later {int((1 - DISC_FRAC) * 100)}%. "
         f"Tests counted for the penalty: {res['n_tests']}.", "",
         "| rule | trades | all trades (stressed / measured) | chosen filter | kept in validation | kept result | delta vs all | 95% range | beats random? | profitable? | candidate |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for rule, r in res["rules"].items():
        b = r.get("base_all", {})
        base = " / ".join(f"{b.get(k, float('nan')):+.3f}" for k in MODES)
        if "filter" not in r:
            L.append(f"| {rule} | {r['n']} | {base} | {r.get('verdict', '')} ||||||| |"); continue
        for k in MODES:
            v = r["validation"][k]
            if "delta" not in v:
                L.append(f"| {rule} ({k}) | {v['n']} | {base} | {' + '.join(r['filter'])} | {v['verdict']} |||||| |"); continue
            L.append(f"| {rule} ({k}) | {v['n']} | {base} | {' + '.join(r['filter'])} | {v['kept']} | {v['kept_mean']:+.3f} | {v['delta']:+.3f} | [{v['ci_lo']:+.3f}, {v['ci_hi']:+.3f}] | "
                     f"{'yes' if v['beats_random'] else 'no'} | {'yes' if v['profitable'] else 'no'} | {'YES' if v['candidate'] else 'no'} |")
    passing = [k for k, v in res["rules"].items() if v.get("passes")]
    L += ["", "Verdict: " + (f"candidate filters for {', '.join(passing)}: they beat the unfiltered rule and random skipping on unseen data under both cost models. A candidate still has to be applied deliberately (ops/filters.json) and then tracked live."
                            if passing else "no filter beats the unfiltered rule on unseen data under both cost models. Live rules stay unchanged."),
          "Note: 'profitable? no' with 'candidate YES' means the filter makes a losing rule LESS bad, not profitable.", ""]
    return "\n".join(L)


def main(root="data/candles", data=Path("data"), reg=Path("docs/trials.jsonl"), out=Path("docs/results")):
    def load_m5(sym):
        d = store.load(sym, "M5", Path(root))
        if d.empty:
            sys.exit(f"missing M5 data for {sym}")
        return split.research_view(d)
    m5s = M.PairCache(M.PAIRS, load_m5)
    h4 = {s: prepare(resample(m5s[s], "H4", base="M5")) for s in M.PAIRS}
    frames = {"H1": M.PairCache(M.PAIRS, lambda s: prepare(resample(m5s[s], "H1", base="M5"))), "H4": h4}
    n_tests = len(VARIANTS) - 1 + 3                       # v1_H1 splits into its 3 rules; E1, E2 one each
    res = dict(n_tests=n_tests, rules={})
    for variant, tfname in VARIANTS:
        f = Path(data) / f"m5_rerun_{variant}.parquet"
        if not f.exists():
            print("skip", variant, "(no result file)"); continue
        trades = pd.read_parquet(f)
        if variant == "v1_H1":
            ctxs = []
            for sym in M.PAIRS:
                ctxs.append(context_table(variant, tfname, {sym: frames[tfname][sym]}, h4))
            ctx = pd.concat(ctxs, ignore_index=True)
        else:
            ctx = context_table(variant, tfname, frames[tfname], h4)
        joined = join(trades, ctx)
        for stype, g in joined.groupby("type"):
            res["rules"][stype] = evaluate(g, n_tests)
            print(stype, res["rules"][stype].get("filter"), res["rules"][stype].get("passes"), flush=True)
    seen = {json.loads(l)["name"] for l in reg.open()} if reg.exists() else set()
    for stype in res["rules"]:
        name = f"entry_filter_{stype}"
        if name not in seen:
            trials.log_trial(name, {"family": "12 single + 66 pairs", "split": DISC_FRAC}, "entry-filter study, pre-registered in docs/EXPERIMENTS.md", reg=reg)
    out.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(out / "entries.json", "w"), indent=1, default=str)
    (out / "entries.md").write_text(render(res)); print(render(res))
    return res


if __name__ == "__main__":
    main()
