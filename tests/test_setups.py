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
