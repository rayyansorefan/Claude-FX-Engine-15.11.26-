import numpy as np, pandas as pd
from fxengine.features.indicators import prepare
from fxengine.setups import v1
from fxengine.backtest import run as bt


def synth(n=6000, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    c = 1.10 + np.cumsum(rng.normal(0, 3e-4, n)) + 0.002 * np.sin(np.arange(n) / 300)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + np.abs(rng.normal(0, 1.5e-4, n))
    l = np.minimum(o, c) - np.abs(rng.normal(0, 1.5e-4, n))
    sp = 0.00004
    return pd.DataFrame({"bid_o": o, "bid_h": h, "bid_l": l, "bid_c": c, "ask_o": o + sp, "ask_h": h + sp,
                         "ask_l": l + sp, "ask_c": c + sp, "volume": 1.0}, index=idx)


def test_signals_are_causal():
    """Signals up to bar k must be identical whether or not future bars exist (no look-ahead)."""
    d = synth()
    k = 4000
    full = prepare(d)
    cut = prepare(d.iloc[: k + 1])
    for name, gen in v1.GENERATORS.items():
        a = gen(full)
        a = a[a.pos <= k].reset_index(drop=True)
        b = gen(cut).reset_index(drop=True)
        assert len(a) == len(b) and len(a) > 0, name
        pd.testing.assert_frame_equal(a, b, check_dtype=False)


def test_signal_prices_sane():
    d = prepare(synth())
    for gen in v1.GENERATORS.values():
        s = gen(d)
        long = s.direction == "long"
        assert (s.stop[long] < s.entry[long]).all() and (s.stop[~long] > s.entry[~long]).all()
        assert (s.target[long] > s.entry[long]).all() and (s.target[~long] < s.entry[~long]).all()


def test_runner_end_to_end_and_unique_ids():
    d = prepare(synth())
    rows = bt.run_pair("EURUSD", d)
    df = pd.DataFrame(rows)
    assert len(df) > 20 and set(df.type) <= set(v1.TYPES)
    res = bt.summarise(df, n_trials=3)
    assert "ALL" in res and res["ALL"]["signals"] == len(df)
    # funnel reconciles: every signal is triggered or not
    assert res["ALL"]["triggered"] + res["ALL"]["not_triggered"] == res["ALL"]["signals"]


def _frames(n=5000):
    out = {}
    for i, sym in enumerate(["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]):
        d = synth(n, seed=10 + i)
        d.index = pd.date_range("2023-01-01", periods=n, freq="4h", tz="UTC")
        out[sym] = d
    return out


def test_e1_e2_signals_causal():
    from fxengine.setups import v2
    fr = _frames()
    k = 3800
    full = {s: prepare(d) for s, d in fr.items()}
    cut = {s: prepare(d.iloc[: k + 1]) for s, d in fr.items()}
    a1, b1 = v2.strength_signals(full), v2.strength_signals(cut)
    tot = 0
    for s in fr:
        a = a1[s][a1[s].pos <= k].reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b1[s].reset_index(drop=True), check_dtype=False)
        tot += len(a)
        a2 = v2.donchian_trend(full[s]); a2 = a2[a2.pos <= k].reset_index(drop=True)
        pd.testing.assert_frame_equal(a2, v2.donchian_trend(cut[s]).reset_index(drop=True), check_dtype=False)
    assert tot > 0


def test_e1_e2_run_end_to_end():
    from fxengine.setups import v2
    bt.TF = pd.Timedelta(hours=4)
    fr = {s: prepare(d) for s, d in _frames().items()}
    sig = v2.strength_signals(fr)
    rows = []
    for s, d in fr.items():
        rows += bt.run_signals(s, d, "E1_strength", sig[s])
        rows += bt.run_signals(s, d, "E2_donchian", v2.donchian_trend(d))
    bt.TF = pd.Timedelta(minutes=15)
    df = pd.DataFrame(rows)
    assert len(df) > 10 and df.triggered.sum() > 0


def test_run_all_end_to_end(tmp_path):
    from fxengine.data import store
    from fxengine.backtest import run_all
    for i, sym in enumerate(bt.PAIRS):
        d = synth(6000, seed=30 + i)
        d.index = pd.date_range("2023-11-01", periods=len(d), freq="4h", tz="UTC")
        store.merge_save(sym, "H4", d, tmp_path / "c")
    run_all.main(root=tmp_path / "c", reg=tmp_path / "t.jsonl", out=tmp_path / "res")
    bt.TF = pd.Timedelta(minutes=15); bt.TFNAME = "M15"
    txt = (tmp_path / "res" / "experiments_summary.md").read_text()
    assert "VERDICT" in txt and "E1:" in txt and "E2:" in txt


def test_verdict_rule_flags_failures():
    from fxengine.backtest import run_all
    rng = np.random.default_rng(0)
    n = 600
    df = pd.DataFrame(dict(symbol=rng.choice(["A", "B", "C"], n), type="x",
                           created=pd.date_range("2023-11-01", periods=n, freq="30D", tz="UTC"),
                           reason="STOP", net_r=rng.normal(-0.2, 1, n), net_r_free=0.0, gross_r=0.0, bars=1,
                           halfway=False, triggered=True))
    v = run_all.verdict(df, 8)
    assert v["PASS"] is False and v["n"] == n
