"""Phase 3 research backtest. Uses research_view (holdout hidden). One open setup per (pair,type).
Same Tracker as live. Stressed costs = headline; unstressed shown for reference.
Usage:  PYTHONPATH=src python -m fxengine.backtest.run   -> prints summary, writes docs/results/phase3_v1.{json,md}"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .. import data as _  # noqa
from ..data import store
from ..engine.costs import CostModel, BASE_SPREAD_PIPS, pip
from ..engine.tracker import Setup, Bar, Tracker
from ..features.indicators import prepare
from ..research import split, stats, trials
from ..setups import v1

TF = pd.Timedelta(minutes=15)
TFNAME = "M15"
PAIRS = list(BASE_SPREAD_PIPS)
STRESSED, FREE = CostModel(True), CostModel(False)


def make_setup(d, row, symbol, stype) -> Setup:
    ot = d.index[row.pos]
    created = ot + TF
    return Setup(run_id=f"{v1.VERSION}{TFNAME}-{symbol}-{stype}-{created:%Y%m%d%H%M}", symbol=symbol,
                 direction=row.direction, setup_type=stype, version=f"{v1.VERSION}-{TFNAME}", created_at=created,
                 entry=float(row.entry), entry_kind=row.kind, stop=float(row.stop), target=float(row.target),
                 expires_at=created + row.expiry_bars * TF, max_hold_bars=int(row.max_hold),
                 invalidation=None, score=float(row.score), reason=stype)


def track(setup, arr, pos0, cost):
    """Feed closed bars after the signal bar through the shared Tracker."""
    t = Tracker(setup, cost)
    ot, o, h, l, c = arr
    end = min(len(ot), pos0 + 1 + (setup.expires_at - setup.created_at) // TF + setup.max_hold_bars + 3)
    for j in range(pos0 + 1, end):
        t.on_bar(Bar(ot[j], ot[j] + TF, o[j], h[j], l[j], c[j]))
        if not t.active:
            break
    return t


def run_signals(symbol, d, stype, sig, arr=None):
    """Track a precomputed signal frame for one pair/type (cooldown: one open setup at a time)."""
    arr = arr or (d.index, d.bid_o.values, d.bid_h.values, d.bid_l.values, d.bid_c.values)
    rows = []
    free_until = pd.Timestamp.min.tz_localize("UTC")
    for row in sig.itertuples():
        created = d.index[row.pos] + TF
        if created < free_until:
            continue
        s = make_setup(d, row, symbol, stype)
        ts, tf_ = track(s, arr, row.pos, STRESSED), track(s, arr, row.pos, FREE)
        free_until = ts.events[-1]["ts"]
        o, of = ts.outcome, tf_.outcome
        rows.append(dict(symbol=symbol, type=stype, created=created, reason=o.reason if o else "OPEN",
                         net_r=o.net_r if o else 0.0, net_r_free=of.net_r if of else 0.0,
                         gross_r=o.gross_r if o else 0.0, bars=o.bars_held if o else 0,
                         halfway=any("HALFWAY" in e["detail"] for e in ts.events),
                         triggered=ts.fill is not None))
    return rows


def run_pair(symbol, d, types=v1.TYPES):
    arr = (d.index, d.bid_o.values, d.bid_h.values, d.bid_l.values, d.bid_c.values)
    rows = []
    for stype in types:
        rows += run_signals(symbol, d, stype, v1.GENERATORS[stype](d), arr)
    return rows


def summarise(df: pd.DataFrame, n_trials: int):
    out = {}
    for stype, g in list(df.groupby("type")) + [("ALL", df)]:
        sc = g[g.triggered & (g.reason != "OPEN")]
        r = sc.net_r.values
        gb = stats.gate_b(r, 100, n_trials) if len(r) else {}
        out[stype] = dict(
            signals=int(len(g)), triggered=int(g.triggered.sum()), scored=int(len(sc)),
            not_triggered=int((~g.triggered).sum()),
            win_rate=float((r > 0).mean()) if len(r) else None,
            exp_r_stressed=float(r.mean()) if len(r) else None,
            exp_r_unstressed=float(sc.net_r_free.mean()) if len(r) else None,
            ci95=[round(x, 3) for x in stats.bootstrap_ci(r)] if len(r) > 1 else None,
            ci_bonferroni_lo=round(gb.get("ci_lo", float("nan")), 3) if gb else None,
            passes_gate_b_math=bool(gb.get("pass")) if gb else False,
            exits=sc.reason.value_counts().to_dict(),
            by_year={str(k): round(v, 3) for k, v in sc.groupby(sc.created.dt.year).net_r.mean().items()},
            by_pair={k: round(v, 3) for k, v in sc.groupby("symbol").net_r.mean().items()},
            halfway_share=float(sc.halfway.mean()) if len(sc) else None,
            mc_drawdown_p95=round(stats.monte_carlo_drawdown(r, 1000)[1], 1) if len(r) > 5 else None)
    return out


def spread_report(frames):
    rep = {}
    for sym, d in frames.items():
        s = ((d.ask_c - d.bid_c) / pip(sym)).median()
        rep[sym] = dict(measured_median_pips=round(float(s), 2), assumed_base_pips=BASE_SPREAD_PIPS[sym])
    return rep


def main(root="data/candles", tf="M15"):
    global TF, TFNAME
    TFNAME = tf
    TF = pd.Timedelta(minutes={"M15": 15, "H1": 60}[tf])
    frames = {}
    for sym in PAIRS:
        d = store.load(sym, tf, Path(root))
        if d.empty:
            print("missing data for", sym)
            continue
        frames[sym] = split.research_view(d)
    seen = {json.loads(l)["name"] for l in Path("docs/trials.jsonl").open()} if Path("docs/trials.jsonl").exists() else set()
    for stype in v1.TYPES:
        if f"{stype}@{tf}" not in seen:
            trials.log_trial(f"{stype}@{tf}", {"version": v1.VERSION, "tf": tf}, "phase3 evaluation")
    n_trials = trials.count_trials()
    rows = []
    for sym, d in frames.items():
        p = prepare(d)
        rows += run_pair(sym, p)
        print(f"{sym}: {len(rows)} setups so far", flush=True)
    df = pd.DataFrame(rows)
    res = dict(version=f"{v1.VERSION}-{tf}", n_trials=n_trials, period=[str(min(f.index.min() for f in frames.values())),
               str(max(f.index.max() for f in frames.values()))], summary=summarise(df, n_trials),
               spreads=spread_report(frames))
    Path("docs/results").mkdir(parents=True, exist_ok=True)
    json.dump(res, open(f"docs/results/phase3_v1_{tf}.json", "w"), indent=1, default=str)
    df.to_parquet(f"data/phase3_v1_{tf}_setups.parquet")
    print(render(res))


def render(res) -> str:
    L = [f"PHASE 3 {res['version']} | {res['period'][0][:10]} -> {res['period'][1][:10]} (holdout hidden) | trials logged: {res['n_trials']}",
         "R = 1 planned stop distance (your £20). Costs: STRESSED.", ""]
    for k, v in res["summary"].items():
        L.append(f"[{k}] signals {v['signals']} | triggered {v['triggered']} | scored {v['scored']} | win {v['win_rate'] and round(v['win_rate'] * 100)}%")
        L.append(f"   net exp {v['exp_r_stressed'] and round(v['exp_r_stressed'], 3)}R stressed | {v['exp_r_unstressed'] and round(v['exp_r_unstressed'], 3)}R normal-cost | 95% CI {v['ci95']} | penalised low {v['ci_bonferroni_lo']} | passes: {v['passes_gate_b_math']}")
        L.append(f"   exits {v['exits']} | by year {v['by_year']}")
        L.append(f"   halfway hit {v['halfway_share'] and round(v['halfway_share'] * 100)}% | MC max-drawdown p95 {v['mc_drawdown_p95']}R")
    L.append("")
    L.append("Spreads (pips) measured vs assumed: " + ", ".join(f"{k} {s['measured_median_pips']}/{s['assumed_base_pips']}" for k, s in res["spreads"].items()))
    return "\n".join(L)


if __name__ == "__main__":
    import sys
    main(tf=sys.argv[1] if len(sys.argv) > 1 else "M15")
