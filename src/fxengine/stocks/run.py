"""Pre-registered stock research (docs/STOCKS_PLAN.md). Price-only (gross) return per trade; costs are reported alongside but are NOT in the gate; gate = clustered (by entry week) bootstrap lower bound > 0 at
alpha 0.05/trials, beats a random-entry challenger, positive in both halves. The latest 365 days are sealed.
Usage: PYTHONPATH=src python -m fxengine.stocks.run  ->  docs/results/stocks.{json,md,html}"""
from __future__ import annotations
import gc, json, sys
from pathlib import Path
import numpy as np
import pandas as pd
from . import costs, strategies as S, backtest as B
from .data import BAD_MOVE
from .universe import kind as kind_of, market as market_of
from ..research import stats, trials

REG = Path("docs/stocks_trials.jsonl")
EVENTS_DF = None                                  # set by main()/open_holdout() from data/stocks/events.parquet when it exists (earnings events)
HOLDOUT_START = pd.Timestamp("2025-11-18")      # FIXED on 2026-11-18 (the first real run's boundary): everything from here on is sealed / forward data and never feeds a research result
HOLDOUT_LOG = Path("docs/stocks_holdout_log.txt")
MIN_WEEKS = 100


def load_panel(path: Path) -> dict[str, pd.DataFrame]:
    df = pd.read_parquet(path, columns=["date", "open", "high", "low", "close", "volume", "symbol"])
    return {s: g.drop(columns="symbol").set_index("date").sort_index() for s, g in df.groupby("symbol")}


def random_pool(panel, hold_bars: np.ndarray, start, end, n: int, rng, day: bool, mode="stressed") -> np.ndarray:
    """Net returns of RANDOM entries (random stock, random date) with the same holding times and the same costs: the 'doing it blindly' benchmark."""
    syms = [s for s, d in panel.items() if len(d) > 400]
    w = np.array([len(panel[s]) for s in syms], float)
    per = rng.multinomial(n, w / w.sum())
    out = []
    for s, k in zip(syms, per):
        if k == 0:
            continue
        d = panel[s]
        o, c, dates = d["open"].to_numpy(float), d["close"].to_numpy(float), d.index.to_numpy()
        bad = np.r_[False, np.abs(c[1:] / c[:-1] - 1.0) > BAD_MOVE]
        bc = np.r_[0, np.cumsum(bad)]
        ok = np.flatnonzero((dates >= start) & (dates < end))
        ok = ok[(ok >= 1) & (ok < len(o) - 2)]
        if len(ok) == 0:
            continue
        e = rng.choice(ok, size=k)
        h = np.zeros(k, int) if day else rng.choice(hold_bars, size=k)
        x = e + h
        keep = (x < len(o)) & (bc[np.minimum(x, len(o) - 1) + 1] - bc[e] == 0)
        e, x = e[keep], x[keep]
        gross = (c[e] / o[e] - 1.0) if day else (o[x] / o[e] - 1.0)
        cb, cs = costs.side_costs(kind_of(s), mode)
        out.append((1.0 + gross) * (1.0 - cs) / (1.0 + cb) - 1.0)
    return np.concatenate(out) if out else np.array([])


def robustness(tr: pd.DataFrame) -> dict:
    """Stress checks for a rule that passed (information, not extra pass criteria): survivorship control (ETFs have no survivor bias), outlier sensitivity,
    the crash years removed, concentration of the gains, worst year. All price-only, same trades."""
    r = tr["gross"].to_numpy(float)
    lo_q, hi_q = np.quantile(r, [0.01, 0.99])
    etf = tr[tr["symbol"].map(kind_of).str.endswith("_etf")]
    d = tr["entry_date"]
    crisis = ((d >= "2008-09-01") & (d <= "2009-06-30")) | ((d >= "2020-02-15") & (d <= "2020-06-30"))
    srt = np.sort(r)[::-1]
    top = srt[: max(1, int(len(r) * 0.01))].sum()
    yr = [float(x["gross"].mean()) for _, x in tr.groupby(d.dt.year) if len(x) >= 20]
    e = None
    if len(etf) >= 50:
        lo, hi = stats.cluster_bootstrap_ci(etf["gross"].to_numpy(float), etf["entry_date"].dt.strftime("%G-%V").to_numpy(), 0.05, n=2000)
        e = dict(n=int(len(etf)), mean=round(float(etf["gross"].mean()), 5), ci_lo=round(float(lo), 5), ci_hi=round(float(hi), 5))
    return dict(etf_only=e, trimmed_mean=round(float(np.clip(r, lo_q, hi_q).mean()), 5), ex_crisis=(round(float(tr.loc[~crisis, "gross"].mean()), 5) if (~crisis).sum() >= 50 else None),
                top1_share=round(float(top / r.sum()), 3) if r.sum() > 0 else float("nan"), worst_year=round(min(yr), 5) if yr else None, best_year=round(max(yr), 5) if yr else None)


def rule_trades(rule: str, panel, events=None, hold_start=None) -> pd.DataFrame:
    """All research-window trades of one rule (gross, net columns), sealed period excluded. The single source of a rule's trades."""
    hs = pd.Timestamp(hold_start) if hold_start is not None else HOLDOUT_START
    sigs = S.rule_sigs(rule, panel, events)
    parts = [t for t in (B.trades_for(sym, d, sigs[sym]) for sym, d in panel.items()) if len(t)]
    tr = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["symbol", "entry_date", "exit_date", "gross", "bars"])
    tr = B.add_net(tr, {s_: kind_of(s_) for s_ in panel})
    return tr[tr["entry_date"] < hs].reset_index(drop=True)


def score(rule: str, tr: pd.DataFrame, panel, start, end, n_trials: int, rng, mid) -> dict:
    if len(tr) < 50:
        return dict(rule=rule, n=int(len(tr)), verdict="too few trades")
    r = tr["gross"].to_numpy(float)                              # price-only: does the SETUP itself work? (costs are reported alongside, not in the gate)
    wk = tr["entry_date"].dt.strftime("%G-%V").to_numpy()
    g = stats.gate_b(r, MIN_WEEKS, n_trials, clusters=wk)
    day = bool((tr["bars"] == 0).all())
    pool = random_pool(panel, tr["bars"].to_numpy(int) if not day else np.array([0]), start, end, 40000, rng, day, mode="gross")
    ch = stats.challenger(float(r.mean()), pool, len(r), draws=1000) if len(pool) > 100 else dict(p95=float("nan"), pct=float("nan"), pool_mean=float("nan"))
    first, second = tr[tr["entry_date"] < mid], tr[tr["entry_date"] >= mid]
    halves = {"first": round(float(first["gross"].mean()), 4) if len(first) else None, "second": round(float(second["gross"].mean()), 4) if len(second) else None}
    c1, c2, c3, c4 = g["n_eff"] >= MIN_WEEKS, bool(g["expectancy_r"] > 0 and g["ci_lo"] > 0), bool(r.mean() > ch["p95"]), bool(all(v is not None and v > 0 for v in halves.values()))
    by_mkt = {m: round(float(x["gross"].mean()), 4) for m, x in tr.groupby(tr["symbol"].map(market_of)) if len(x) >= 20}
    core = tr["symbol"].map(market_of).isin(["US", "UK"])                                  # where the rules were found vs. markets they were never looked at in
    gen = dict(core_n=int(core.sum()), intl_n=int((~core).sum()), core_mean=(round(float(tr.loc[core, "gross"].mean()), 5) if core.sum() >= 30 else None),
               intl_mean=(round(float(tr.loc[~core, "gross"].mean()), 5) if (~core).sum() >= 30 else None))
    days = int(tr["entry_date"].dt.normalize().nunique())
    by_year = {str(y): round(float(x["gross"].mean()), 4) for y, x in tr.groupby(tr["entry_date"].dt.year) if len(x) >= 20}
    return dict(rule=rule, n=int(len(tr)), weeks=int(g["n_eff"]), hit_rate=round(float((r > 0).mean()), 4), avg_hold=round(float(tr["bars"].mean()), 1),
                gross=round(float(tr["gross"].mean()), 5), net_normal=round(float(tr["net_normal"].mean()), 5), net_stressed=round(float(tr["net_stressed"].mean()), 5), roi=round(float(r.mean()), 5),
                ci95_lo=round(float(g["ci_lo"]), 5), ci95_hi=round(float(g["ci_hi"]), 5), mde=round(float(g["mde_r"]), 5),
                challenger_p95=round(float(ch["p95"]), 5), real_pct=round(float(ch["pct"]), 1), halves=halves, by_market=by_mkt, by_year=by_year,
                gates=dict(weeks=bool(c1), lower_bound=c2, beats_random=c3, both_halves=c4), passes=bool(c1 and c2 and c3 and c4), day_trade=day, generalisation=gen, signal_days=days,
                robust=robustness(tr) if (c1 and c2 and c3 and c4) else None)


def benchmarks(panel, start, end) -> dict:
    out = {}
    if "spy.us" in panel:
        c = panel["spy.us"]["close"]
        c = c[(c.index >= start) & (c.index < end)]
        if len(c) > 250:
            out["spy_cagr"] = round(float((c.iloc[-1] / c.iloc[0]) ** (365.25 / (c.index[-1] - c.index[0]).days) - 1), 4)
    rets = pd.concat([d["close"].pct_change() for s, d in panel.items() if len(d) > 400], axis=1)
    rets = rets[(rets.index >= start) & (rets.index < end)].clip(-BAD_MOVE, BAD_MOVE).mean(axis=1).dropna()
    if len(rets) > 250:
        out["equal_weight_cagr"] = round(float((1 + rets).prod() ** (365.25 / (rets.index[-1] - rets.index[0]).days) - 1), 4)
    return out


def main(path=Path("data/stocks/prices.parquet"), out=Path("docs/results"), reg=REG, hold_start=None):
    global EVENTS_DF
    from . import events as EV
    EVENTS_DF = EV.load(Path(path).parent.parent.parent if Path(path).name == "prices.parquet" else Path("."))
    panel = load_panel(path)
    if not panel:
        raise SystemExit("no price data: run  python -m fxengine.stocks.data  first")
    last = max(d.index.max() for d in panel.values())
    hold_start = pd.Timestamp(hold_start) if hold_start is not None else HOLDOUT_START
    first = min(d.index.min() for d in panel.values())
    mid = first + (hold_start - first) / 2
    kinds = {s: kind_of(s) for s in panel}
    rng = np.random.default_rng(3)
    prior = {json.loads(l)["name"] for l in reg.open()} if reg.exists() else set()
    n_trials = len(prior | set(S.RULES))
    rules, nsym = [], len(panel)
    for rule in S.RULES:
        parts = []
        sigs = S.rule_sigs(rule, panel, EVENTS_DF)
        for s, d in panel.items():
            t = B.trades_for(s, d, sigs[s])
            if len(t):
                parts.append(t)
        tr = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["symbol", "entry_date", "exit_date", "gross", "bars"])
        tr = B.add_net(tr, kinds)
        tr = tr[tr["entry_date"] < hold_start]                       # the latest 365 days are sealed
        rules.append(score(rule, tr, panel, first, hold_start, n_trials, rng, mid))
        del parts, tr
        gc.collect()
    reg.parent.mkdir(parents=True, exist_ok=True)
    with reg.open("a") as f:
        for k in S.RULES:
            if k not in prior:
                f.write(json.dumps({"name": k, "note": "pre-registered in docs/STOCKS_PLAN.md"}) + "\n")
    res = dict(n_trials=n_trials, symbols=nsym, window=f"{first:%Y-%m-%d}..{hold_start:%Y-%m-%d}", sealed_from=f"{hold_start:%Y-%m-%d}", benchmarks=benchmarks(panel, first, hold_start), rules=rules)
    out.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(out / "stocks.json", "w"), indent=1, default=str)
    (out / "stocks.md").write_text(render(res))
    print(render(res))
    try:
        from . import dashboard
        dashboard.write(out / "stocks.json", out / "stocks.html")
        from . import tab
        tab.write(out / "stocks.json")
    except ImportError:
        pass
    return res


def open_holdout(rule: str, why: str, path=Path("data/stocks/prices.parquet"), res_path=Path("docs/results/stocks.json"), log=HOLDOUT_LOG, hold_start=None) -> dict:
    """ONE-TIME look at the sealed period for ONE frozen rule that already passed the research gate. Refuses anything else, and refuses a second opening."""
    global EVENTS_DF
    from . import events as EV
    EVENTS_DF = EV.load(Path(path).parent.parent.parent if Path(path).name == "prices.parquet" else Path("."))
    hs = pd.Timestamp(hold_start) if hold_start is not None else HOLDOUT_START
    res = json.loads(Path(res_path).read_text())
    r0 = next((r for r in res["rules"] if r["rule"] == rule), None)
    if r0 is None or not r0.get("passes"):
        raise SystemExit(f"{rule} has not passed the research gate: the sealed period stays sealed.")
    if Path(log).exists() and any(l.split("|")[1].strip() == rule for l in Path(log).read_text().splitlines() if "|" in l):
        raise SystemExit(f"{rule}: the sealed period was already opened once (see {log}). It cannot be opened again.")
    panel = load_panel(Path(path))
    sigs = S.rule_sigs(rule, panel, EVENTS_DF)
    parts = []
    for sym, d in panel.items():
        t = B.trades_for(sym, d, sigs[sym])
        if len(t):
            parts.append(t)
    tr = B.add_net(pd.concat(parts, ignore_index=True), {s: kind_of(s) for s in panel}) if parts else pd.DataFrame()
    tr = tr[tr["entry_date"] >= hs] if len(tr) else tr
    n = int(len(tr))
    out = dict(rule=rule, why=why, opened=pd.Timestamp.today().strftime("%Y-%m-%d"), sealed_from=f"{hs:%Y-%m-%d}", n=n)
    if n:
        r = tr["gross"].to_numpy(float)
        lo, hi = stats.cluster_bootstrap_ci(r, tr["entry_date"].dt.strftime("%G-%V").to_numpy(), 0.05, n=5000) if n >= 10 else (float("nan"), float("nan"))
        out.update(mean=round(float(r.mean()), 5), hit_rate=round(float((r > 0).mean()), 4), ci95_lo=round(float(lo), 5), ci95_hi=round(float(hi), 5),
                   net_normal=round(float(tr["net_normal"].mean()), 5), net_stressed=round(float(tr["net_stressed"].mean()), 5), research_mean=r0["roi"])
    out["verdict"] = ("INCONCLUSIVE: fewer than 30 trades" if n < 30 else "PASS: positive on data the rule had never seen (still needs forward confirmation)" if out["mean"] > 0 else "FAIL: not positive on data the rule had never seen")
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    with Path(log).open("a") as f:
        f.write(f"{out['opened']} | {rule} | {why} | n={n} mean={out.get('mean')} | {out['verdict']}\n")
    print(json.dumps(out, indent=1))
    return out


def render(res) -> str:
    bm = res.get("benchmarks", {})
    L = ["# Stock research (pre-registered rules, net of costs)", "",
         f"Trials {res['n_trials']} (alpha = 0.05/{res['n_trials']}). {res['symbols']} symbols. Window {res['window']}. Sealed from {res['sealed_from']}.",
         f"Doing nothing: buy-and-hold SPY {bm.get('spy_cagr', float('nan')) * 100:+.1f}%/yr · equal-weight universe {bm.get('equal_weight_cagr', float('nan')) * 100:+.1f}%/yr (survivors only: flatters both).", "",
         "Return = mean % gain per trade from price moves alone (costs are NOT in the pass/fail test). The two 'after costs' columns are for information only.", "",
         "| rule | trades | weeks | hit | avg gain | CI (cluster) | MDE | random p95 | after costs (normal) | after costs (stressed) | passes |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in res["rules"]:
        if "roi" not in r:
            L.append(f"| {r['rule']} | {r['n']} | {r['verdict']} ||||||||"); continue
        L.append(f"| {r['rule']} | {r['n']} | {r['weeks']} | {r['hit_rate']:.0%} | {r['roi']:+.2%} | [{r['ci95_lo']:+.2%}, {r['ci95_hi']:+.2%}] | {r['mde']:.2%} | {r['challenger_p95']:+.2%} | {r['net_normal']:+.2%} | {r['net_stressed']:+.2%} | {'YES' if r['passes'] else 'no'} |")
    pr = [r for r in res["rules"] if r.get("passes") and r.get("robust")]
    if pr:
        L += ["", "## Stress checks on the rules that passed (information only)", "",
              "| rule | ETFs only (no survivor bias) | outliers trimmed | without 2008-09 & 2020 | top 1% of trades = share of all gains | worst year | best year |", "|---|---|---|---|---|---|---|"]
        for r in pr:
            b = r["robust"]
            e = b["etf_only"]
            L.append(f"| {r['rule']} | {('n/a' if not e else format(e['mean'], '+.2%') + ' [' + format(e['ci_lo'], '+.2%') + ', ' + format(e['ci_hi'], '+.2%') + '] n=' + str(e['n']))} | {b['trimmed_mean']:+.2%} | "
                     f"{('n/a' if b['ex_crisis'] is None else format(b['ex_crisis'], '+.2%'))} | {b['top1_share']:.0%} | {b['worst_year']:+.2%} | {b['best_year']:+.2%} |")
    L += ["", "A rule passes only if (price moves alone): 100+ independent weeks, penalised lower bound above 0, beats random entries, and is positive in both halves of the window."]
    return "\n".join(L)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", help="open the sealed period ONCE for this rule (must have passed the research gate)")
    ap.add_argument("--why", default="", help="required with --holdout: the reason, written to the log")
    a = ap.parse_args()
    if a.holdout:
        if not a.why.strip():
            raise SystemExit("--why is required: the reason is written to docs/stocks_holdout_log.txt")
        open_holdout(a.holdout, a.why)
    else:
        main()
