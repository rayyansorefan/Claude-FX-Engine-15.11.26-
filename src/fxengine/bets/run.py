"""Pre-registered betting tests on historical Bet365 prices. Every number is net profit per £1 staked at Bet365's own price (the margin is IN the price).
Pre-registered list (docs/BETTING_PLAN.md): 6 rules, no more. Sealed holdout = the latest FULL season and anything after it.
Gate: cluster-bootstrap (by match-week) lower bound of ROI > 0 at alpha 0.05/trials, AND mean above the random-bet challenger's 95th percentile.
Usage: PYTHONPATH=src python -m fxengine.bets.run  -> docs/results/bets.{json,md}"""
from __future__ import annotations
import gc, json
from pathlib import Path
import numpy as np
import pandas as pd
from . import odds as O, sim
from ..research import stats

NEEDED = ["Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR", "season", "B365H", "B365D", "B365A", "PSH", "PSD", "PSA", "PSCH", "PSCD", "PSCA",
          "B365>2.5", "B365<2.5", "P>2.5", "P<2.5"]            # the other columns (market max/avg, closing O/U) are not used by any rule


def _release():
    """Return freed memory to the operating system (glibc keeps it otherwise): the VM has ~200 MB spare."""
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


HOLDOUT_SEASONS = ("2526", "2627")
RULES = ["F1_all_favourites", "L1_longshots_5plus", "V1_b365_vs_pinnacle_3pc", "OV1_over25_all", "UN1_under25_all", "D1_draws_all"]


def bet_table(m: pd.DataFrame, chunk: int = 15000) -> pd.DataFrame:
    """One row per selectable bet: 1X2 (H/D/A) and over/under 2.5, priced at Bet365 (pre-match snapshot).
    Built with array operations (no Python object per bet): ~500k rows must fit in the VM's ~200 MB of spare memory."""
    if len(m) > chunk:                                   # build in slices: the one-shot version needs ~125 MB of scratch space on top
        return pd.concat([bet_table(m.iloc[i:i + chunk], chunk) for i in range(0, len(m), chunk)], ignore_index=True)
    m = m.reset_index(drop=True)
    d = m["Date"]
    key = (m["Div"].astype(str) + "-" + d.dt.strftime("%Y%m%d") + "-" + m["HomeTeam"].astype(str) + "-" + m["AwayTeam"].astype(str)).to_numpy(object)
    week = d.dt.strftime("%G-%V").to_numpy(object)
    div, season, date = m["Div"].to_numpy(object), m["season"].to_numpy(object), d.to_numpy()
    ftr = m["FTR"].to_numpy(object)
    num = lambda cols: m[cols].to_numpy(float)
    parts = []

    def block(rows, market, sel, odds, won, is_fav, fair_sharp, fair_close):
        parts.append(pd.DataFrame(dict(div=div[rows], season=season[rows], date=date[rows], match=key[rows], week=week[rows], market=market, sel=sel,
                                       odds=odds, won=won, is_fav=is_fav, fair_sharp=fair_sharp, fair_close=fair_close)))

    o3 = num(["B365H", "B365D", "B365A"])
    r1 = np.flatnonzero(~np.isnan(o3).any(axis=1))
    if len(r1):
        o3 = o3[r1]
        fs, fc = O.fair_probs_shin_arr(num(["PSH", "PSD", "PSA"])[r1]), O.fair_probs_shin_arr(num(["PSCH", "PSCD", "PSCA"])[r1])
        fav = np.argmin(o3, axis=1)
        for i, sel in enumerate("HDA"):
            block(r1, "1X2", sel, o3[:, i], ftr[r1] == sel, fav == i, fs[:, i], fc[:, i])
    ou = num(["B365>2.5", "B365<2.5"])
    goals = m["FTHG"].to_numpy(float) + m["FTAG"].to_numpy(float)
    r2 = np.flatnonzero(~np.isnan(ou).any(axis=1) & ~np.isnan(goals))
    if len(r2):
        fo = O.fair_probs_shin_arr(num(["P>2.5", "P<2.5"])[r2])
        for i, (sel, won) in enumerate((("O25", goals[r2] > 2.5), ("U25", goals[r2] < 2.5))):
            block(r2, "OU", sel, ou[r2, i], won, np.zeros(len(r2), bool), fo[:, i], np.full(len(r2), np.nan))
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def pick(b: pd.DataFrame, rule: str) -> pd.DataFrame:
    x = b[b.market == "1X2"]
    if rule == "F1_all_favourites":
        return x[x.is_fav]
    if rule == "L1_longshots_5plus":
        return x[x.odds >= 5.0]
    if rule == "V1_b365_vs_pinnacle_3pc":                    # Bet365 price at least 3% better than the sharp (Pinnacle, margin-removed) fair price
        v = b[b.fair_sharp.notna()]
        return v[v.odds * v.fair_sharp - 1.0 >= 0.03]
    if rule == "OV1_over25_all":
        return b[b.sel == "O25"]
    if rule == "UN1_under25_all":
        return b[b.sel == "U25"]
    if rule == "D1_draws_all":
        return x[x.sel == "D"]
    raise KeyError(rule)


def profit(d: pd.DataFrame) -> np.ndarray:
    return np.where(d.won, d.odds - 1.0, -1.0)


def score(b: pd.DataFrame, rule: str, n_trials: int, rng) -> dict:
    d = pick(b, rule)
    if len(d) < 200:
        return dict(rule=rule, n=int(len(d)), verdict="too few bets")
    r = profit(d)
    g = stats.gate_b(r, 100, n_trials, clusters=d.week.values)
    # random-bet challenger: same markets, a random selection per match, same sample size
    pool_src = b.loc[b.market.isin(d.market.unique()), ["match", "odds", "won"]]
    pr = profit(pool_src)
    codes = pd.factorize(pool_src["match"].to_numpy())[0]
    pool = []
    for _ in range(5):                                           # one random selection per match, drawn without copying the table
        perm = rng.permutation(len(codes))
        order = perm[np.argsort(codes[perm], kind="stable")]
        first = np.r_[True, codes[order][1:] != codes[order][:-1]]
        pool.append(pr[order[first]])
    pool = np.concatenate(pool)
    del pool_src, pr, codes
    ch = stats.challenger(float(r.mean()), pool, len(r))
    ov = pick(b, "F1_all_favourites") if False else d
    return dict(rule=rule, n=int(len(d)), weeks=g["n_eff"], hit_rate=round(float(d.won.mean()), 4), roi=round(float(r.mean()), 4),
                ci95_lo=round(g["ci_lo"], 4), ci95_hi=round(g["ci_hi"], 4), mde=round(g["mde_r"], 4),
                margin_paid=round(float(np.mean(1.0 / d.odds) - d.won.mean()), 4),
                clv_vs_close=(round(float((d.odds * d.fair_close - 1).mean()), 4) if d.fair_close.notna().any() else None),
                challenger_mean=round(ch["pool_mean"], 4), challenger_p95=round(ch["p95"], 4), real_pct=round(ch["pct"], 1),
                by_season={s: round(float(profit(g_).mean()), 3) for s, g_ in d.groupby("season")},
                passes=bool(g["pass"]) and float(r.mean()) > ch["p95"], sim=sim.simulate(d.odds.values, d.won.values, n=1500))


def render(res) -> str:
    L = ["# Betting research (historical Bet365 prices, margin included)", "",
         f"Trials: {res['n_trials']} (alpha = 0.05/{res['n_trials']}). Seasons {res['seasons']}. Sealed: {', '.join(HOLDOUT_SEASONS)}.",
         "ROI = profit per £1 staked at Bet365's price. margin_paid = average gap between price-implied chance and actual hit rate. CLV = price vs Pinnacle's margin-free closing price (>0 = beat the close).", "",
         "| rule | bets | hit | ROI | 95% CI (clustered) | MDE | CLV vs close | random-bet p95 | passes | £100->£1000 / ruin (5% stakes) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in res["rules"]:
        if "roi" not in r:
            L.append(f"| {r['rule']} | {r['n']} | {r['verdict']} |||||||"); continue
        L.append(f"| {r['rule']} | {r['n']} | {r['hit_rate']:.1%} | {r['roi']:+.2%} | [{r['ci95_lo']:+.2%}, {r['ci95_hi']:+.2%}] | {r['mde']:.2%} | "
                 f"{'n/a' if r['clv_vs_close'] is None else format(r['clv_vs_close'], '+.2%')} | {r['challenger_p95']:+.2%} | {'YES' if r['passes'] else 'no'} | "
                 f"{r['sim']['p_goal']:.1%} / {r['sim']['p_ruin']:.0%} |")
    L += ["", "Reading: a rule 'passes' only if the lower end of its clustered CI is above 0 after the multiple-testing penalty AND it beats random bets. 'no' means no proven edge above the MDE.", ""]
    return "\n".join(L)


def main(path=Path("data/bets/matches.parquet"), out=Path("docs/results"), reg=Path("docs/bets_trials.jsonl")):
    stats._chunked.__defaults__ = (400_000,)              # smaller resampling batches: ~35 MB less scratch memory, same numbers
    m = pd.read_parquet(path, columns=NEEDED)
    m = m[~m.season.isin(HOLDOUT_SEASONS)]
    if m.empty:
        raise SystemExit("no research seasons available: run the download first")
    seasons = f"{m.season.min()}..{m.season.max()}"
    b = bet_table(m)
    del m
    _release()
    prior = [json.loads(l)["name"] for l in reg.open()] if reg.exists() else []
    n_trials = len(set(prior) | set(RULES))
    rng = np.random.default_rng(3)
    rules = []
    for k in RULES:
        rules.append(score(b, k, n_trials, rng))
        _release()
    if any("roi" in r for r in rules):
        reg.parent.mkdir(parents=True, exist_ok=True)
        with reg.open("a") as f:
            for k in RULES:
                if k not in prior:
                    f.write(json.dumps({"name": k, "note": "pre-registered in docs/BETTING_PLAN.md"}) + "\n")
    res = dict(n_trials=n_trials, seasons=seasons, rules=rules)
    out.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(out / "bets.json", "w"), indent=1, default=str)
    (out / "bets.md").write_text(render(res)); print(render(res))
    return res


if __name__ == "__main__":
    main()
