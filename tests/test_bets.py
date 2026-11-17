import numpy as np, pandas as pd
from fxengine.bets import odds as O, sim, run as R, data as D


def _matches(n=1500, seed=0, fair=True):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        p = rng.dirichlet([4, 2.5, 3.5])
        res = rng.choice(list("HDA"), p=p)
        o = 1 / (p * 1.05)                                           # a flat 5% margin
        g = rng.poisson(2.7)
        d = pd.Timestamp("2018-01-01") + pd.Timedelta(days=int(i // 4))
        rows.append(dict(Div="E0", Date=d, HomeTeam=f"h{i}", AwayTeam=f"a{i}", FTHG=g // 2, FTAG=g - g // 2, FTR=res, season="1819" if i < n // 2 else "1920",
                         B365H=o[0], B365D=o[1], B365A=o[2], PSH=o[0], PSD=o[1], PSA=o[2], PSCH=o[0], PSCD=o[1], PSCA=o[2], **{"B365>2.5": 1.9, "B365<2.5": 1.95, "P>2.5": 1.9, "P<2.5": 1.95}))
    return pd.DataFrame(rows)


def test_margin_removal():
    assert abs(O.overround(2.0, 3.5, 4.0) - (0.5 + 1 / 3.5 + 0.25 - 1)) < 1e-12
    assert abs(O.fair_probs(2.0, 3.5, 4.0).sum() - 1) < 1e-12 and abs(O.fair_probs_shin(2.0, 3.5, 4.0).sum() - 1) < 1e-9
    assert O.fair_probs(2.0, float("nan"), 4.0) is None
    s = O.fair_probs_shin(1.3, 5.5, 11.0); p = O.fair_probs(1.3, 5.5, 11.0)
    assert s[2] < p[2]                                               # Shin takes more margin off longshots


def test_shin_solves_its_own_equation():
    o = np.array([1.5, 4.2, 7.5]); q = 1 / o; s = q.sum()
    p = O.fair_probs_shin(*o)
    assert abs(p.sum() - 1) < 1e-9 and p[0] > p[2]
    # the solved z must give probabilities that sum to 1 BEFORE the final normalisation (guards against a reversed bisection)
    lo, hi = 0.0, 0.4
    for _ in range(200):
        z = (lo + hi) / 2
        raw = (np.sqrt(z * z + 4 * (1 - z) * q * q / s) - z) / (2 * (1 - z))
        lo, hi = (lo, z) if raw.sum() < 1 else (z, hi)
    assert np.allclose(raw / raw.sum(), p, atol=1e-6) and abs(raw.sum() - 1) < 1e-6
    assert abs(p[0] - 1 / 1.5 / s) < 0.02                           # favourite barely moves vs proportional removal


def test_a_fair_market_with_a_margin_shows_no_edge_and_loses_the_margin():
    b = R.bet_table(_matches())
    out = R.score(b, "F1_all_favourites", 6, np.random.default_rng(1))
    assert not out["passes"] and out["ci95_lo"] < 0.02 and out["roi"] < 0.03        # ~-5% expected, never a proven edge


def test_a_planted_mispricing_is_detected():
    m = _matches(16000, seed=2)                                    # longshots are noisy: a real edge needs a big sample to clear the gate (the gate is NOT loosened)
    mask = (m.B365H > 3.0)                                         # Bet365 offers 12% too much on longshot home wins whose true price is Pinnacle's
    m.loc[mask, "B365H"] = m.loc[mask, "B365H"] * 1.2
    b = R.bet_table(m)
    out = R.score(b, "V1_b365_vs_pinnacle_3pc", 6, np.random.default_rng(1))
    assert out["roi"] > 0.03 and out["passes"]


def test_bankroll_simulator_shows_the_lottery_and_ruin():
    r = sim.simulate(np.full(1000, 2.0), np.random.default_rng(0).random(1000) < 0.4762, frac=0.05, n=300)
    assert r["p_goal"] < 0.05 and r["p_ruin"] > 0.2


def test_parse_handles_missing_columns_and_dates():
    csv = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A\nE0,12/08/2023,A,B,1,0,H,2.0,3.4,3.9\n"
    p = D.parse(csv, "E0", "2324")
    assert len(p) == 1 and p.Date.iloc[0] == pd.Timestamp("2023-08-12") and np.isnan(p["PSH"].iloc[0])


def test_parse_coerces_text_odds_so_parquet_never_fails(tmp_path):
    csv = ("Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A,PSCH\n"
           "E0,12/08/2023,A,B,1,0,H,2.0,3.4,3.9,2.21\nE0,13/08/2023,C,D,2,2,D,2.0,3.4,3.9,-\n")
    p = D.parse(csv, "E0", "2324")
    assert str(p["PSCH"].dtype) == "float64" and np.isnan(p["PSCH"].iloc[1])
    p.to_parquet(tmp_path / "x.parquet")                              # the exact step that crashed on the VM


def test_download_saves_raw_files_and_a_rerun_makes_no_requests(tmp_path):
    calls = []
    class R:
        def __init__(s, c, t=""): s.status_code, s.content = c, t.encode()
    csv = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A\nE0,12/08/2023,A,B,1,0,H,2.0,3.4,3.9\n"
    def get(u):
        calls.append(u); return R(200, csv) if "/E0.csv" in u else R(404)
    D.download(tmp_path, divs=["E0", "E1"], seasons=["2324"], get=get, pause=0)
    n = len(calls)
    df = D.download(tmp_path, divs=["E0", "E1"], seasons=["2324"], get=get, pause=0)
    assert n == 2 and len(calls) == n and len(df) == 1                # second run reads the cache, asks the site for nothing


def _bet_table_reference(m: pd.DataFrame) -> pd.DataFrame:
    """One row per selectable bet: 1X2 (H/D/A) and over/under 2.5, priced at Bet365 (pre-match snapshot)."""
    rows = []
    for r in m.to_dict("records"):                     # dict rows: column names like 'B365>2.5' are not valid attribute names
        res = r["FTR"]
        base = dict(div=r["Div"], season=r["season"], date=r["Date"], match=f"{r['Div']}-{r['Date']:%Y%m%d}-{r['HomeTeam']}-{r['AwayTeam']}", week=f"{r['Date']:%G-%V}")
        o3 = (r["B365H"], r["B365D"], r["B365A"])
        if not pd.isna(list(o3)).any():
            fair_ps = O.fair_probs_shin(r["PSH"], r["PSD"], r["PSA"])
            fair_psc = O.fair_probs_shin(r["PSCH"], r["PSCD"], r["PSCA"])
            fav = int(np.argmin(o3))
            for i, (sel, o) in enumerate(zip("HDA", o3)):
                rows.append(dict(base, market="1X2", sel=sel, odds=float(o), won=bool(res == sel), is_fav=(i == fav),
                                 fair_sharp=float(fair_ps[i]) if fair_ps is not None else np.nan,
                                 fair_close=float(fair_psc[i]) if fair_psc is not None else np.nan))
        if not (pd.isna(r["B365>2.5"]) or pd.isna(r["B365<2.5"])) and not (pd.isna(r["FTHG"]) or pd.isna(r["FTAG"])):
            goals = r["FTHG"] + r["FTAG"]
            ou = O.fair_probs_shin(r["P>2.5"], r["P<2.5"])
            for i, (sel, o, won) in enumerate((("O25", r["B365>2.5"], goals > 2.5), ("U25", r["B365<2.5"], goals < 2.5))):
                rows.append(dict(base, market="OU", sel=sel, odds=float(o), won=bool(won), is_fav=False,
                                 fair_sharp=float(ou[i]) if ou is not None else np.nan, fair_close=np.nan))
    return pd.DataFrame(rows)


def test_vectorised_bet_table_matches_the_slow_reference_exactly():
    m = _matches(1200, seed=9)
    rng = np.random.default_rng(0)
    for c in ["B365H", "PSH", "PSCD", "B365>2.5", "P<2.5", "FTHG"]:                 # sprinkle missing values
        m.loc[rng.random(len(m)) < 0.07, c] = np.nan
    m.loc[rng.random(len(m)) < 0.03, "PSA"] = 1.0                                   # invalid odds (<=1)
    new = R.bet_table(m)
    ref = _bet_table_reference(m)
    k = ["match", "sel"]
    new, ref = new.sort_values(k).reset_index(drop=True), ref.sort_values(k).reset_index(drop=True)
    assert len(new) == len(ref) and len(new) > 3000
    for c in ["div", "season", "date", "match", "week", "market", "sel", "won", "is_fav"]:
        assert (new[c].to_numpy() == ref[c].to_numpy()).all(), c
    for c in ["odds", "fair_sharp", "fair_close"]:
        assert np.allclose(new[c].to_numpy(float), ref[c].to_numpy(float), equal_nan=True, atol=1e-9), c


def test_bet_table_in_slices_equals_one_shot():
    m = _matches(1000, seed=4)
    a, b = R.bet_table(m, chunk=10**6), R.bet_table(m, chunk=137)
    k = ["match", "sel"]
    a, b = a.sort_values(k).reset_index(drop=True), b.sort_values(k).reset_index(drop=True)
    assert len(a) == len(b) and (a.match.to_numpy() == b.match.to_numpy()).all() and np.allclose(a.odds, b.odds) and np.allclose(a.fair_sharp, b.fair_sharp, equal_nan=True)


def test_dashboard_renders_real_numbers_only_and_handles_empty(tmp_path):
    from fxengine.bets import dashboard as DB
    assert "No results yet" in DB.render(None) and "nan" not in DB.render(None).lower().replace("financial", "")
    res = dict(n_trials=6, seasons="1213..2425", rules=[
        dict(rule="F1_all_favourites", n=1000, hit_rate=0.5, roi=-0.04, ci95_lo=-0.08, ci95_hi=0.0, mde=0.1, clv_vs_close=float("nan"), challenger_p95=-0.03, passes=False,
             by_season={"1819": -0.05, "1920": 0.01}, sim=dict(p_goal=0.001, p_ruin=0.98, p_neither=0.019, median_bets=200, frac=0.05)),
        dict(rule="V1_b365_vs_pinnacle_3pc", n=5, verdict="too few bets")])
    h = DB.render(res)
    assert "No proven edge" in h and "Back every favourite" in h and "too few bets" in h and "-4.0%" in h and "<script" not in h
    res["rules"][0]["passes"] = True
    assert "cleared the gate" in DB.render(res)
    import json
    (tmp_path / "bets.json").write_text(json.dumps(res))
    assert DB.write(tmp_path / "bets.json", tmp_path / "bets.html").read_text().startswith("<!doctype html>")


def test_parse_uses_pp_columns_when_ps_columns_are_absent():
    csv = ("Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A,PPH,PPD,PPA,PPCH,PPCD,PPCA\n"
           "E0,12/08/2026,A,B,1,0,H,2.0,3.4,3.9,2.1,3.3,3.8,2.05,3.4,3.9\n")
    p = D.parse(csv, "E0", "2627")
    assert p["PSH"].iloc[0] == 2.1 and p["PSCA"].iloc[0] == 3.9
    both = csv.replace("PPH,", "PSH,PPH,").replace("2.1,3.3", "9.9,2.1,3.3")                  # when PS exists it wins
    assert D.parse(both, "E0", "2627")["PSH"].iloc[0] == 9.9
