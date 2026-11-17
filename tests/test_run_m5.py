import numpy as np, pandas as pd
from fxengine.data import store
from fxengine.backtest import run_m5
from fxengine.engine.costs import CostModel
from fxengine.engine.tracker import Setup, bar_arrays, track_arrays
from fxengine.research import stats


def synth_m5(n, seed, start="2024-01-01"):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="5min", tz="UTC")
    c = 1.10 + np.cumsum(rng.normal(0, 1.2e-4, n)) + 0.003 * np.sin(np.arange(n) / 900)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + np.abs(rng.normal(0, 6e-5, n))
    l = np.minimum(o, c) - np.abs(rng.normal(0, 6e-5, n))
    sp = 0.00012 + 0.00008 * (idx.hour >= 21)
    return pd.DataFrame({"bid_o": o, "bid_h": h, "bid_l": l, "bid_c": c, "ask_o": o + sp, "ask_h": h + sp,
                         "ask_l": l + sp, "ask_c": c + sp, "volume": 1.0}, index=idx)


def test_measured_cost_uses_bar_spread_and_no_commission():
    T0 = pd.Timestamp("2025-06-03 08:00", tz="UTC")
    s = Setup("r", "EURUSD", "long", "t", "v", T0, entry=1.1000, entry_kind="stop", stop=1.0990, target=1.1020,
              expires_at=T0 + pd.Timedelta(hours=1), max_hold_bars=8)
    idx = pd.date_range(T0, periods=3, freq="5min", tz="UTC")
    df = pd.DataFrame({"bid_o": [1.1000, 1.1005, 1.1012], "bid_h": [1.1006, 1.1013, 1.1025], "bid_l": [1.0999, 1.1004, 1.1011],
                       "bid_c": [1.1005, 1.1012, 1.1021], "ask_o": [1.1002, 1.1007, 1.1014]}, index=idx)
    tm = track_arrays(s, bar_arrays(df), pd.Timedelta(minutes=5), CostModel(False, measured=True))
    tn = track_arrays(s, bar_arrays(df), pd.Timedelta(minutes=5), CostModel(False))
    assert tm.outcome.reason == tn.outcome.reason == "TARGET"
    assert tm.fill == 1.1002 + 0.00003            # measured spread 2 pips + slippage, not the modelled 0.3 pip
    assert tm.outcome.cost_r < tn.outcome.cost_r  # no commission in measured mode


def test_cluster_bootstrap_wider_than_iid_and_mde_sane():
    rng = np.random.default_rng(0)
    r = np.repeat(rng.normal(0.1, 1.0, 40), 10)          # 400 trades but only 40 independent days
    days = np.repeat(np.arange(40), 10)
    lo_i, hi_i = stats.bootstrap_ci(r, n=2000)
    lo_c, hi_c = stats.cluster_bootstrap_ci(r, days, n=2000)
    assert (hi_c - lo_c) > (hi_i - lo_i) * 1.5
    g = stats.gate_b(r, 100, 10, clusters=days)
    assert g["n_eff"] == 40 and not g["pass"] and 0.2 < g["mde_r"] < 1.0


def test_challenger_percentile():
    pool = np.random.default_rng(1).normal(0.0, 1.0, 2000)
    assert stats.challenger(0.5, pool, 200)["pct"] > 99
    assert stats.challenger(-0.5, pool, 200)["pct"] < 1


def test_m5_rerun_end_to_end(tmp_path):
    for i, sym in enumerate(run_m5.PAIRS):
        store.merge_save(sym, "M5", synth_m5(15000, 50 + i), tmp_path / "c")
    res = run_m5.main(root=tmp_path / "c", reg=tmp_path / "t.jsonl", out=tmp_path / "r",
                      variants=[("v1_H1", "H1"), ("E2_donchian", "H4"), ("E4_donchian_trail", "H4")])
    s = res["summary"]
    assert set(s) == {"v1_H1", "E2_donchian", "E4_donchian_trail"} and set(s["v1_H1"]) == {"stressed", "normal", "measured"}
    v = s["v1_H1"]["stressed"]
    assert v["scored"] > 20 and v["pair_days"] <= v["scored"] and v["mde_r"] > 0 and v["challenger_pct"] is not None
    assert (tmp_path / "r" / "m5_rerun.md").exists() and "challenger" in (tmp_path / "r" / "m5_rerun.md").read_text()
    assert (tmp_path / "t.jsonl").read_text().count("\n") == 1          # logged once as a trial


def test_bootstrap_is_chunked_with_bounded_memory_and_same_answers():
    import tracemalloc
    rng = np.random.default_rng(3)
    r = rng.normal(0.02, 1.0, 6000)
    days = np.repeat(np.arange(3000), 2)
    tracemalloc.start()
    lo, hi = stats.cluster_bootstrap_ci(r, days, n=10000)
    lo2, hi2 = stats.bootstrap_ci(r, n=10000)
    peak = tracemalloc.get_traced_memory()[1] / 1e6
    tracemalloc.stop()
    assert peak < 120, peak                                  # was ~1 GB for the cluster bootstrap at this size
    assert abs((lo + hi) / 2 - r.mean()) < 0.06 and lo < r.mean() < hi and lo2 < r.mean() < hi2
    assert (hi - lo) > (hi2 - lo2) * 0.8                     # cluster CI is not narrower than the naive one
