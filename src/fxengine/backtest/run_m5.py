"""R0 — M5-RESOLUTION RERUN of all seven pre-registered variants. NOT a new strategy trial: the rules, parameters,
data window and holdout are unchanged. What changes is how a setup is scored once published:
  * fills, stops and targets are resolved on M5 bars via engine.tracker.track_arrays, the SAME driver the live loop
    uses (the original runners resolved them on the signal bar itself, where "stop beats target in the same bar" and
    "no target on the entry bar" bite much harder on a 1h/4h bar);
  * three cost modes per setup: STRESSED (v1 headline), NORMAL (v1), MEASURED (the data's own ask-bid, no commission);
  * a random-entry CHALLENGER per variant: the same stop/target/expiry/hold rules at random bars with random direction,
    so "edge" is judged against what the rules' mechanics alone produce;
  * cluster bootstrap by pair-day, Bonferroni, and the minimum detectable effect printed with every number.
Usage: PYTHONPATH=src python -m fxengine.backtest.run_m5   -> docs/results/m5_rerun.{json,md}"""
from __future__ import annotations
import json, sys
from collections.abc import Mapping
from pathlib import Path
import numpy as np
import pandas as pd
from ..data import store
from ..research.diagnose import trade_fields
from ..data.resample import resample
from ..data.timeframes import tf_delta
from ..engine.costs import CostModel, BASE_SPREAD_PIPS
from ..engine.tracker import Setup, bar_arrays, track_arrays
from ..features.indicators import prepare
from ..research import split, stats, trials
from ..setups import v1, v2

PAIRS = list(BASE_SPREAD_PIPS)
FIVE = pd.Timedelta(minutes=5)
COSTS = {"stressed": CostModel(True), "normal": CostModel(False), "measured": CostModel(False, measured=True)}
TRAIL = 20
VARIANTS = [("v1_M15", "M15"), ("v1_H1", "H1"), ("E1_strength", "H4"), ("E2_donchian", "H4"),
            ("E4_donchian_trail", "H4"), ("E5_strength_trail", "H4")]
CHALLENGER_POOL = 3000


def signals_for(variant, frames_tf):
    """{(symbol, type): signal frame} for one variant over prepared frames of its timeframe."""
    out = {}
    if variant.startswith("v1"):
        for sym, d in frames_tf.items():
            for t in v1.TYPES:
                out[(sym, t)] = v1.GENERATORS[t](d)
    elif variant == "E1_strength":
        out = {(s, "E1_strength"): sig for s, sig in v2.strength_signals(frames_tf).items()}
    elif variant == "E2_donchian":
        out = {(s, "E2_donchian"): v2.donchian_trend(d) for s, d in frames_tf.items()}
    elif variant == "E4_donchian_trail":
        out = {(s, "E4_donchian_trail"): v2.with_trailing(v2.donchian_trend(d), 5, 120) for s, d in frames_tf.items()}
    elif variant == "E5_strength_trail":
        out = {(s, "E5_strength_trail"): v2.with_trailing(sig, 5, 60) for s, sig in v2.strength_signals(frames_tf).items()}
    return out


def _setup(row, sym, stype, d, tf, use_invalidation):
    created = d.index[row.pos] + tf
    inv = getattr(row, "invalidation", np.nan)
    return Setup(run_id=f"m5-{stype}-{sym}-{created:%Y%m%d%H%M}", symbol=sym, direction=row.direction, setup_type=stype,
                 version="R0-M5", created_at=created, entry=float(row.entry), entry_kind=row.kind, stop=float(row.stop),
                 target=float(row.target), expires_at=created + int(row.expiry_bars) * tf, max_hold_bars=int(row.max_hold) * int(tf // FIVE),
                 invalidation=None if (not use_invalidation or inv != inv) else float(inv), score=float(row.score), reason=stype)


def _trailer(d, tf, long, trail=TRAIL):
    """after_bar hook: on every closed bar of the signal timeframe, ratchet the stop to the trail-bar extreme."""
    idx, lo, hi = d.index, d.bid_l.values, d.bid_h.values

    def hook(t, j):
        close_t = t._last_close
        if t.fill is None or (close_t - idx[0]) % tf != pd.Timedelta(0):
            return
        q = idx.searchsorted(close_t) - 1          # signal-tf bar that just closed
        if q < trail - 1 or idx[q] + tf != close_t:
            return
        lvl = lo[q - trail + 1:q + 1].min() if long else hi[q - trail + 1:q + 1].max()
        c = t._last_c
        if (long and t.stop < lvl < c) or (not long and c < lvl < t.stop):
            t.adjust(close_t, stop=float(lvl), detail="trail")
    return hook


def track_m5(setup, arr_m5, j0, cost, trail_hook=None):
    span = int((setup.expires_at - setup.created_at) // FIVE) + setup.max_hold_bars + 3
    if trail_hook is None:
        return track_arrays(setup, arr_m5, FIVE, cost, j0, j0 + span)
    ot, o, h, l, c, sp = arr_m5

    def hook(t, j):
        t._last_close, t._last_c = ot[j] + FIVE, c[j]
        trail_hook(t, j)
    return track_arrays(setup, arr_m5, FIVE, cost, j0, j0 + span, after_bar=hook)


class PairCache(Mapping):
    """pair -> value, computed on demand and kept for ONE pair at a time, so peak memory is one pair, not ten
    (the eager version held every pair's M5 plus three prepared timeframes: 1.26 GB on 161k rows)."""
    def __init__(self, keys, loader):
        self._keys, self._loader, self._k, self._v = list(keys), loader, None, None

    def __getitem__(self, k):
        if k not in self._keys:
            raise KeyError(k)
        if self._k != k:
            self._k = self._v = None                    # drop the previous pair BEFORE loading the next
            self._v, self._k = self._loader(k), k
        return self._v

    def __iter__(self):
        return iter(self._keys)

    def __len__(self):
        return len(self._keys)


def run_variant(variant, tfname, frames_tf, m5s, use_invalidation=True, rng=None):
    tf = tf_delta(tfname)
    sigs = signals_for(variant, frames_tf)
    trail = variant.endswith("_trail")
    rows, pool = [], {k: [] for k in COSTS}
    rng = rng or np.random.default_rng(11)
    real = []                                        # (sym, risk_atr, rr, kind, expiry, max_hold) for the challenger
    cur, arr = None, None
    for (sym, stype), sig in sigs.items():
        d, m5 = frames_tf[sym], m5s[sym]
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
            s = _setup(row, sym, stype, d, tf, use_invalidation)
            hook = _trailer(d, tf, s.direction == "long") if trail else None
            res = {k: track_m5(s, arr, j0, cm, hook) for k, cm in COSTS.items()}
            ts = res["stressed"]
            free_until = ts.events[-1]["ts"]
            o = ts.outcome
            rows.append(dict(symbol=sym, type=stype, created=created, day=f"{sym}-{created:%Y%m%d}",
                             reason=o.reason if o else "OPEN", triggered=ts.fill is not None, bars=o.bars_held if o else 0,
                             **{f"net_r_{k}": (r.outcome.net_r if r.outcome else 0.0) for k, r in res.items()},
                             **{f"trig_{k}": r.fill is not None for k, r in res.items()},
                             **trade_fields(o, row.direction, created)))
            a = float(d.atr.iloc[row.pos])
            if a > 0:
                real.append((sym, abs(row.entry - row.stop) / a, abs(row.target - row.entry) / abs(row.entry - row.stop),
                             row.kind, int(row.expiry_bars), int(row.max_hold)))
    df = pd.DataFrame(rows)
    # ---- random-entry challenger: same mechanics, random bar, random direction. Draws are made first and processed
    # grouped by pair so each pair's data is loaded once (random pair order would thrash the one-pair cache).
    n_pool = min(CHALLENGER_POOL, 3 * max(len(real), 1))
    by_sym = {}
    for _ in range(n_pool if real else 0):
        sym, risk_atr, rr, kind, exp_b, hold = real[rng.integers(len(real))]
        by_sym.setdefault(sym, []).append((risk_atr, rr, kind, exp_b, hold, float(rng.random()), bool(rng.integers(2))))
    for sym, items in by_sym.items():
        d, m5 = frames_tf[sym], m5s[sym]
        arr_m5 = bar_arrays(m5)
        for risk_atr, rr, kind, exp_b, hold, u, long in items:
            p = v1.WARMUP + int(u * max(len(d) - 2 - v1.WARMUP, 0))
            if variant.startswith("v1") and not (7 <= d.index[p].hour <= 19):      # v1 only trades 07-19 UTC; sample the same hours
                continue
            a = float(d.atr.iloc[p])
            if not a > 0:
                continue
            e = float(d.bid_c.iloc[p]); sign = 1 if long else -1
            created = d.index[p] + tf
            s = Setup(run_id="ch", symbol=sym, direction="long" if long else "short", setup_type="challenger", version="R0", created_at=created,
                      entry=e, entry_kind=kind, stop=e - sign * risk_atr * a, target=e + sign * rr * risk_atr * a,
                      expires_at=created + exp_b * tf, max_hold_bars=hold * int(tf // FIVE))
            j0 = int(m5.index.searchsorted(created))
            if j0 >= len(m5):
                continue
            hook = _trailer(d, tf, long) if trail else None
            for k, cm in COSTS.items():
                t = track_m5(s, arr_m5, j0, cm, hook)
                if t.outcome and t.fill is not None:
                    pool[k].append(t.outcome.net_r)
    return df, pool


def summarise(df, pool, n_trials):
    out = {}
    for k in COSTS:
        sc = df[df[f"trig_{k}"] & (df.reason != "OPEN")] if len(df) else df
        r = sc[f"net_r_{k}"].values if len(sc) else np.array([])
        gb = stats.gate_b(r, 100, n_trials, clusters=sc.day.values) if len(r) > 1 else {}
        ch = stats.challenger(float(r.mean()), pool[k], len(r)) if len(r) else {}
        yrs = sc.groupby(sc.created.dt.year)[f"net_r_{k}"].mean() if len(sc) else pd.Series(dtype=float)
        out[k] = dict(signals=int(len(df)), scored=int(len(r)), pair_days=gb.get("n_eff"), win=float((r > 0).mean()) if len(r) else None,
                      exp_r=float(r.mean()) if len(r) else None, ci95_cluster=[round(gb["ci_lo"], 3), round(gb["ci_hi"], 3)] if gb else None,
                      penalised_lo=round(gb["ci_lo"], 3) if gb else None, mde_r=round(gb["mde_r"], 3) if gb else None,
                      by_year={int(y): round(v, 3) for y, v in yrs.items()},
                      challenger_pct=round(ch["pct"], 1) if ch else None, challenger_p95=round(ch["p95"], 3) if ch else None,
                      challenger_mean=round(ch["pool_mean"], 3) if ch else None,
                      passes=bool(gb.get("pass")) and bool(ch) and float(r.mean()) > ch["p95"])
    return out


def render(res) -> str:
    L = ["# R0 — M5-resolution rerun (same rules, same data window, holdout untouched)", "",
         f"Trials logged: {res['n_trials']} (alpha = 0.05/{res['n_trials']}). Period {res['period'][0][:10]} -> {res['period'][1][:10]}.",
         "Pass = penalised cluster-bootstrap lower bound > 0 AND mean above the random-entry challenger's 95th percentile.",
         "MDE = smallest true edge (R/trade) this sample could have detected; read 'no edge' as 'no edge above MDE'.", "",
         "| variant | cost | signals | scored | pair-days | win | net R | 95% cluster CI | penalised low | MDE | challenger mean / p95 / real pct | years | pass |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for v, modes in res["summary"].items():
        for k, s in modes.items():
            if s["scored"] == 0:
                L.append(f"| {v} | {k} | {s['signals']} | 0 | | | | | | | | | no data |")
                continue
            L.append(f"| {v} | {k} | {s['signals']} | {s['scored']} | {s['pair_days']} | {s['win'] * 100:.0f}% | {s['exp_r']:+.3f} | {s['ci95_cluster']} | "
                     f"{s['penalised_lo']:+.3f} | {s['mde_r']:.3f} | {s['challenger_mean']:+.3f} / {s['challenger_p95']:+.3f} / {s['challenger_pct']}% | "
                     f"{s['by_year']} | {'PASS' if s['passes'] else 'FAIL'} |")
    return "\n".join(L) + "\n"


def main(root="data/candles", reg=Path("docs/trials.jsonl"), out=Path("docs/results"), variants=VARIANTS):
    def load_m5(sym):
        d = store.load(sym, "M5", Path(root))
        if d.empty:
            sys.exit(f"missing M5 data for {sym}")
        return split.research_view(d)
    m5s = PairCache(PAIRS, load_m5)
    n_rows = {s: len(m5s[s]) for s in PAIRS}                 # one pass, one pair in memory at a time
    if all(n == 0 for n in n_rows.values()):
        sys.exit("research window empty: the stored prices start after the holdout boundary. Run the history job first.")
    frames = {tf: PairCache(PAIRS, lambda s, tf=tf: prepare(resample(m5s[s], tf, base="M5"))) for tf in ("M15", "H1")}
    frames["H4"] = {s: prepare(resample(m5s[s], "H4", base="M5")) for s in PAIRS if n_rows[s]}      # small; E1/E5 need every pair at once
    trials.ensure_seed(reg)
    seen = {json.loads(l)["name"] for l in reg.open()} if reg.exists() else set()
    pending = "R0_m5_rerun_measured_cost" not in seen                 # logged only AFTER a run that actually scored setups
    n_trials = trials.count_trials(reg) + (1 if pending else 0)
    res = dict(version="R0-M5", n_trials=n_trials, period=[str(min(f.index.min() for f in frames["H4"].values())), str(max(f.index.max() for f in frames["H4"].values()))], summary={})
    for variant, tfname in variants:
        df, pool = run_variant(variant, tfname, frames[tfname], m5s)
        res["summary"][variant] = summarise(df, pool, n_trials)
        print(variant, {k: (s["scored"], s["exp_r"], s["passes"]) for k, s in res["summary"][variant].items()}, flush=True)
        if len(df):
            Path("data").mkdir(exist_ok=True)
            df.to_parquet(f"data/m5_rerun_{variant}.parquet")
    if pending and any(s["scored"] for modes in res["summary"].values() for s in modes.values()):
        trials.log_trial("R0_m5_rerun_measured_cost", {"resolution": "M5", "costs": list(COSTS)}, "R0: same rules at M5 resolution + measured-cost mode", reg=reg)
    out.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(out / "m5_rerun.json", "w"), indent=1, default=str)
    (out / "m5_rerun.md").write_text(render(res))
    print(render(res))
    return res


if __name__ == "__main__":
    main()
