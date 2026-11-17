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
