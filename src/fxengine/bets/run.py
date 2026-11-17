"""Pre-registered betting tests on historical Bet365 prices. Every number is net profit per £1 staked at Bet365's own price (the margin is IN the price).
Pre-registered list (docs/BETTING_PLAN.md): 6 rules, no more. Sealed holdout = the latest FULL season and anything after it.
Gate: cluster-bootstrap (by match-week) lower bound of ROI > 0 at alpha 0.05/trials, AND mean above the random-bet challenger's 95th percentile.
Usage: PYTHONPATH=src python -m fxengine.bets.run  -> docs/results/bets.{json,md}"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from . import odds as O, sim
from ..research import stats

HOLDOUT_SEASONS = ("2526", "2627")
RULES = ["F1_all_favourites", "L1_longshots_5plus", "V1_b365_vs_pinnacle_3pc", "OV1_over25_all", "UN1_under25_all", "D1_draws_all"]


def bet_table(m: pd.DataFrame) -> pd.DataFrame:
    """One row per selectable bet: 1X2 (H/D/A) and over/under 2.5, priced at Bet365 (pre-match snapshot)."""
    rows = []
    for r in m.itertuples(index=False):
        res = r.FTR
        base = dict(div=r.Div, season=r.season, date=r.Date, match=f"{r.Div}-{r.Date:%Y%m%d}-{r.HomeTeam}-{r.AwayTeam}", week=f"{r.Date:%G-%V}")
        o3 = (r.B365H, r.B365D, r.B365A)
        if not any(pd.isna(o3)):
            fair_ps = O.fair_probs_shin(r.PSH, r.PSD, r.PSA)
            fair_psc = O.fair_probs_shin(r.PSCH, r.PSCD, r.PSCA)
            fav = int(np.argmin(o3))
            for i, (sel, o) in enumerate(zip("HDA", o3)):
                rows.append(dict(base, market="1X2", sel=sel, odds=float(o), won=bool(res == sel), is_fav=(i == fav),
                                 fair_sharp=float(fair_ps[i]) if fair_ps is not None else np.nan,
                                 fair_close=float(fair_psc[i]) if fair_psc is not None else np.nan))
        if not (pd.isna(r._asdict()["B365>2.5"]) or pd.isna(r._asdict()["B365<2.5"])) and not (pd.isna(r.FTHG) or pd.isna(r.FTAG)):
            goals = r.FTHG + r.FTAG
            ou = O.fair_probs_shin(r._asdict()["P>2.5"], r._asdict()["P<2.5"])
            for i, (sel, o, won) in enumerate((("O25", r._asdict()["B365>2.5"], goals > 2.5), ("U25", r._asdict()["B365<2.5"], goals < 2.5))):
                rows.append(dict(base, market="OU", sel=sel, odds=float(o), won=bool(won), is_fav=False,
                                 fair_sharp=float(ou[i]) if ou is not None else np.nan, fair_close=np.nan))
    return pd.DataFrame(rows)


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
    pool_src = b[b.market.isin(d.market.unique())]
    pool = np.concatenate([profit(pool_src.sample(frac=1.0, random_state=int(rng.integers(1 << 30))).groupby("match").head(1)) for _ in range(5)])
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
    m = pd.read_parquet(path)
    m = m[~m.season.isin(HOLDOUT_SEASONS)]
    if m.empty:
        raise SystemExit("no research seasons available: run the download first")
    b = bet_table(m)
    prior = [json.loads(l)["name"] for l in reg.open()] if reg.exists() else []
    n_trials = len(set(prior) | set(RULES))
    rng = np.random.default_rng(3)
    rules = [score(b, k, n_trials, rng) for k in RULES]
    if any("roi" in r for r in rules):
        reg.parent.mkdir(parents=True, exist_ok=True)
        with reg.open("a") as f:
            for k in RULES:
                if k not in prior:
                    f.write(json.dumps({"name": k, "note": "pre-registered in docs/BETTING_PLAN.md"}) + "\n")
    res = dict(n_trials=n_trials, seasons=f"{m.season.min()}..{m.season.max()}", rules=rules)
    out.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(out / "bets.json", "w"), indent=1, default=str)
    (out / "bets.md").write_text(render(res)); print(render(res))
    return res


if __name__ == "__main__":
    main()
