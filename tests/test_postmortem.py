import json
import random
import pandas as pd
from fxengine.learn import postmortem as PM
from fxengine.live import db as DB


def _trade(conn, i, typ, net_r, ctx, mfe=None):
    rid = f"{typ}-{i}"
    rec = dict(pair="GBPUSD", type=typ, tf="H1", direction="long", created=f"2026-11-{1 + i % 28:02d} 10:00+00:00", expires="2026-12-30 16:00+00:00", entry=1.31, stop=1.308, target=1.314,
               stop_pips=20.0, lots_for_20gbp_risk=0.01, score=1.0, ctx=ctx)
    DB.add_setup(conn, rid, rec)
    conn.execute("INSERT INTO outcomes(run_id,reason,net_r,fill,exit,resolved_at,gross_r,mfe_r,mae_r) VALUES(?,?,?,?,?,?,?,?,?)",
                 (rid, "TARGET" if net_r > 0 else "STOP", net_r, 1.31, 1.31, "2026-11-20T12:00:00+00:00", net_r, mfe if mfe is not None else max(net_r, 0.1), 0.5))
    conn.commit()


def _ctx(rng, htf):
    return dict(atr_rank=rng.random(), trend_with=rng.uniform(-1, 2), ext_ema20=rng.uniform(0, 2), hour_utc=rng.randint(0, 23), dow=rng.randint(0, 4), htf_align=htf)


def _r(rng, p_win):
    return 1.9 if rng.random() < p_win else -1.1


def test_pure_noise_almost_never_produces_a_supported_finding(tmp_path):
    """The multiple-testing guard: with NO real effect, across many random datasets, SUPPORTED findings must be (almost) never. Bonferroni family-wise error is 5%."""
    supported = 0
    for seed in range(30):
        rng = random.Random(seed)
        conn = DB.connect(str(tmp_path / f"n{seed}.db"))
        for i in range(120):
            _trade(conn, i, "asia_breakout" if i % 2 else "trend_pullback", _r(rng, 0.37), _ctx(rng, rng.choice([-1, 0, 1])))
        res = PM.analyse(conn)
        supported += sum(1 for s in res["pooled"] + [x for v in res["by_type"].values() for x in v["seps"]] if s["status"].startswith("SUPPORTED"))
    assert supported <= 2                                       # 30 noise datasets, ~36 comparisons each: expected well under 1.5 at a 5% family-wise error


def test_a_realistic_planted_effect_is_found_with_enough_trades_and_not_with_few(tmp_path):
    """Not a trivial 100%-win rule: aligned-with-higher-timeframe trades win 48% of the time, the others 33% (a gap of about 0.4R)."""
    rng = random.Random(7)
    conn = DB.connect(str(tmp_path / "big.db"))
    for i in range(1500):                                        # a realistic 0.45R gap needs well over a thousand trades to clear a Bonferroni bar: that is the honest cost of not fooling ourselves
        htf = rng.choice([-1, 1])
        _trade(conn, i, "asia_breakout", _r(rng, 0.48 if htf == 1 else 0.33), _ctx(rng, htf))
    res = PM.analyse(conn)
    s = {x["name"]: x for x in res["pooled"]}["htf_with"]
    assert s["status"].startswith("SUPPORTED") and "better" in s["status"] and s["lo"] > 0 and s["passes"]["n"] >= 30
    small = DB.connect(str(tmp_path / "small.db"))
    rng = random.Random(7)
    for i in range(24):                                          # the same effect, but only 24 trades: must NOT be called supported
        htf = rng.choice([-1, 1])
        _trade(small, i, "asia_breakout", _r(rng, 0.48 if htf == 1 else 0.33), _ctx(rng, htf))
    res2 = PM.analyse(small)
    assert not any(x["status"].startswith("SUPPORTED") for x in res2["pooled"])


def test_loss_anatomy_and_the_three_line_friday_note(tmp_path):
    conn = DB.connect(str(tmp_path / "a.db"))
    rng = random.Random(1)
    for i in range(10):
        _trade(conn, i, "x", -1.1, _ctx(rng, 1), mfe=0.1)       # wrong from the start
    for i in range(10, 14):
        _trade(conn, i, "x", -1.1, _ctx(rng, 1), mfe=1.4)       # faded after +1.4R
    for i in range(14, 20):
        _trade(conn, i, "x", 1.9, _ctx(rng, 1), mfe=2.0)
    res = PM.analyse(conn)
    k = res["anatomy"]["kinds"]
    assert res["anatomy"]["losers"] == 14 and k["wrong_from_start"] == 10 and k["faded"] == 4
    lines = PM.summary_lines(res)
    assert len(lines) == 3 and "71% wrong from the start" in lines[0] and "29% faded" in lines[0]
    assert len(PM.summary_lines(dict(n=3, anatomy=dict(losers=1, winners=2, kinds={}, avg_loss=-1.1, avg_win=1.9), pooled=[], by_type={}))) == 3
    text = PM.write_report(conn, tmp_path / "pm.md")["text"]
    assert "Bonferroni" in text and "comparisons were made" in text


def test_the_bonferroni_threshold_is_stated_and_correct(tmp_path):
    from statistics import NormalDist
    rng = random.Random(3)
    conn = DB.connect(str(tmp_path / "t.db"))
    for i in range(60):
        _trade(conn, i, "a" if i % 2 else "b", _r(rng, 0.4), _ctx(rng, rng.choice([-1, 1])))
    res = PM.analyse(conn)
    assert res["m"] == 12 * (1 + len(res["by_type"])) and abs(res["alpha_per_test"] - 0.05 / res["m"]) < 1e-12
    z = NormalDist().inv_cdf(1 - 0.05 / (2 * res["m"]))
    s = next(x for x in res["pooled"] if x["diff"] is not None)
    assert abs((s["hi"] - s["diff"]) - z * s["se"]) < 1e-9
