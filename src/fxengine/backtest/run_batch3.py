"""Batch 3: E6 (daily time-series momentum) and E7 (carry + momentum). Pre-registered in docs/EXPERIMENTS.md.
Scored on M5 bars through the SAME driver as the live loop (engine.tracker.track_arrays), three cost modes, random-entry
challenger, cluster bootstrap, minimum detectable effect. E7 runs only if data/rates.csv exists AND gap_report is clean.
Usage: PYTHONPATH=src python -m fxengine.backtest.run_batch3 [E6|E7|all]   -> docs/results/batch3.{json,md}"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd
from ..data import store, rates as R
from ..data.daily import daily_bars_ny
from ..engine.tracker import Setup, bar_arrays, track_arrays
from ..research import split, trials
from ..research.diagnose import trade_fields
from ..setups import v3
from . import run_m5 as M

FIVE = pd.Timedelta(minutes=5)
MAX_HOLD_M5 = 60 * 288
CHALLENGER_POOL = 3000


def _hold_bars(m5_index, created, exit_at):
    j0 = int(m5_index.searchsorted(created))
    j1 = int(m5_index.searchsorted(exit_at))
    return j0, int(min(max(j1 - 1 - j0, 1), MAX_HOLD_M5))


def _setup(name, sym, row, created, hold):
    carry = None if (row.carry_annual != row.carry_annual) else float(row.carry_annual)
    return Setup(run_id=f"b3-{name}-{sym}-{created:%Y%m%d%H%M}", symbol=sym, direction=row.direction, setup_type=name,
                 version="B3", created_at=created, entry=float(row.entry), entry_kind="stop", stop=float(row.stop),
                 target=float(row.target), expires_at=created + pd.Timedelta(hours=72), max_hold_bars=hold,
                 score=float(row.score), reason=name, carry_annual=carry)


def run_experiment(name, frames, m5s, sigs, diffs=None, rng=None):
    """sigs: {sym: signal frame}. diffs: {sym: Series of rate diff (pp) aligned to the daily frame} for the E7 challenger."""
    rng = rng or np.random.default_rng(13)
    rows, pool, real = [], {k: [] for k in M.COSTS}, []
    for sym, sig in sigs.items():
        d, m5 = frames[sym], m5s[sym]
        arr = bar_arrays(m5)
        free_until = pd.Timestamp.min.tz_localize("UTC")
        for row in sig.itertuples():
            created = d.close_time.iloc[row.pos]
            if created < free_until:
                continue
            j0, hold = _hold_bars(m5.index, created, row.exit_at)
            if j0 >= len(m5):
                continue
            s = _setup(name, sym, row, created, hold)
            res = {k: track_arrays(s, arr, FIVE, cm, j0, j0 + hold + 867) for k, cm in M.COSTS.items()}
            ts = res["stressed"]
            free_until = ts.events[-1]["ts"]
            o = ts.outcome
            rows.append(dict(symbol=sym, type=name, created=created, day=f"{sym}-{created:%Y%m%d}", reason=o.reason if o else "OPEN",
                             triggered=ts.fill is not None, bars=o.bars_held if o else 0,
                             **{f"net_r_{k}": (r.outcome.net_r if r.outcome else 0.0) for k, r in res.items()},
                             **{f"trig_{k}": r.fill is not None for k, r in res.items()},
                             **trade_fields(o, row.direction, created)))
            real.append(hold)
    df = pd.DataFrame(rows)
    # ---- random-entry challenger: random Friday close, random direction, same stop/target ATR multiples, a real hold length
    if real:
        fri = {sym: np.flatnonzero((frames[sym].fri & frames[sym].atr20.notna()).values & (np.arange(len(frames[sym])) >= v3.WARMUP)) for sym in sigs}
        syms = [s for s in sigs if len(fri[s])]
        for _ in range(min(CHALLENGER_POOL, 3 * len(real))):
            sym = syms[rng.integers(len(syms))]
            d, m5 = frames[sym], m5s[sym]
            p = int(fri[sym][rng.integers(len(fri[sym]))])
            long = bool(rng.integers(2)); sign = 1 if long else -1
            a, e = float(d.atr20.iloc[p]), float(d.bid_c.iloc[p])
            created = d.close_time.iloc[p]
            exit_at = created + pd.Timedelta(days=int(real[rng.integers(len(real))] / 288 * 1.4) + 1)
            j0, hold = _hold_bars(m5.index, created, exit_at)
            if j0 >= len(m5):
                continue
            carry = np.nan
            if diffs is not None and diffs[sym].iloc[p] == diffs[sym].iloc[p]:
                carry = sign * float(diffs[sym].iloc[p]) / 100.0 - v3.MARKUP
            row = pd.Series(dict(direction="long" if long else "short", entry=e, stop=e - sign * v3.STOP_ATR * a,
                                 target=e + sign * v3.TARGET_ATR * a, score=0.0, carry_annual=carry))
            s = _setup("challenger", sym, row, created, hold)
            arr = bar_arrays(m5)
            for k, cm in M.COSTS.items():
                t = track_arrays(s, arr, FIVE, cm, j0, j0 + hold + 867)
                if t.outcome and t.fill is not None:
                    pool[k].append(t.outcome.net_r)
    return df, pool


def render(res) -> str:
    extra = ("\nRates: last observation per currency " + json.dumps(res["rates_last_observation"]) + " (45-day publication lag applied)\n") if res.get("rates_last_observation") else ""
    return extra + M.render(res).replace("# R0 — M5-resolution rerun (same rules, same data window, holdout untouched)",
                                 "# Batch 3 — daily momentum (E6) and carry+momentum (E7), scored on M5 bars (holdout untouched)")


def main(which="all", root="data/candles", reg=Path("docs/trials.jsonl"), out=Path("docs/results"), rates_path=R.PATH):
    m5s, frames = {}, {}
    for sym in M.PAIRS:
        d = store.load(sym, "M5", Path(root))
        if d.empty:
            sys.exit(f"missing M5 data for {sym}")
        m5s[sym] = split.research_view(d)
    if all(len(d) == 0 for d in m5s.values()):
        sys.exit("research window empty: the stored prices start after the holdout boundary. Run the history job first.")
    for sym, d in m5s.items():
        frames[sym] = v3.prep(daily_bars_ny(d))
    trials.ensure_seed(reg)
    seen = {json.loads(l)["name"] for l in reg.open()} if reg.exists() else set()
    todo = {"E6": "E6_tsmom_daily", "E7": "E7_carry_mom_daily"}
    run = [k for k in todo if which in ("all", k)]
    diffs = None
    if "E7" in run:
        if not Path(rates_path).exists():
            print("E7 skipped: no rates file. Run: python -m fxengine.data.rates"); run.remove("E7")
        else:
            rt = R.load_rates(Path(rates_path))
            gaps = {c: g for c, g in R.gap_report(rt).items() if g == "column missing" or g["missing_months"] or g["last"] is None}
            if gaps:
                print("E7 skipped: rates have gaps (fix the data first):", json.dumps(gaps)[:800]); run.remove("E7")
            else:
                diffs = {s: R.pair_diff(s, R.rates_known_at(rt, frames[s].close_time)).set_axis(frames[s].index) for s in M.PAIRS}
    pending = [k for k in run if todo[k] not in seen]                 # logged only AFTER a run that actually scored setups
    n_trials = trials.count_trials(reg) + len(pending)
    res = dict(version="B3", n_trials=n_trials, period=[str(min(f.index.min() for f in m5s.values())), str(max(f.index.max() for f in m5s.values()))], summary={})
    for k in run:
        sigs = ({s: v3.tsmom_signals(frames[s]) for s in M.PAIRS} if k == "E6"
                else {s: v3.carry_mom_signals(frames[s], diffs[s]) for s in M.PAIRS})
        df, pool = run_experiment(todo[k], frames, m5s, sigs, diffs if k == "E7" else None)
        res["summary"][todo[k]] = M.summarise(df, pool, n_trials)
        print(k, {c: (s["scored"], s["exp_r"], s["passes"]) for c, s in res["summary"][todo[k]].items()}, flush=True)
        if len(df):
            Path("data").mkdir(exist_ok=True)
            df.to_parquet(f"data/batch3_{k}.parquet")
    for k in pending:
        if any(s["scored"] for s in res["summary"].get(todo[k], {}).values()):
            trials.log_trial(todo[k], {"batch": 3}, "pre-registered in docs/EXPERIMENTS.md", reg=reg)
    if diffs is not None:
        res["rates_last_observation"] = {c: str(g["last"]) for c, g in R.gap_report(rt).items()}      # so the publication lag can be checked
    out.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(out / "batch3.json", "w"), indent=1, default=str)
    (out / "batch3.md").write_text(render(res))
    print(render(res))
    return res


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "all")
