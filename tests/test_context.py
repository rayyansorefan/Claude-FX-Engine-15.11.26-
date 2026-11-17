import numpy as np, pandas as pd
from fxengine.features import context as C
from fxengine.features.indicators import prepare
from fxengine.research import diagnose as D


def _frame(n=300, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-05", periods=n, freq="1h", tz="UTC")
    c = 1.10 + np.cumsum(rng.normal(0.0002, 0.001, n))
    return prepare(pd.DataFrame(dict(bid_o=c, bid_h=c + 0.0008, bid_l=c - 0.0008, bid_c=c), index=idx))


def test_snapshot_uses_only_closed_bars_and_records_conditions():
    d = _frame()
    s = C.snapshot(d, 250, "long", spread_pips=0.6, h4=d)
    assert {"atr_pct", "atr_rank", "trend_with", "ext_ema20", "hour_utc", "dow", "spread_pips", "htf_align"} <= set(s)
    d2 = d.copy(); d2.iloc[251:, d2.columns.get_loc("bid_c")] += 5          # changing the FUTURE must not change the snapshot
    d2 = prepare(d2[["bid_o", "bid_h", "bid_l", "bid_c"]])
    assert C.snapshot(d2, 250, "long") == {k: v for k, v in C.snapshot(d, 250, "long").items()}
    assert C.snapshot(d, 250, "short")["trend_with"] == -C.snapshot(d, 250, "long")["trend_with"]


def test_exposure_counts_correlated_setups():
    act = [dict(pair="EURUSD", direction="short"), dict(pair="GBPUSD", direction="short")]
    assert C.exposure("AUDUSD", "short", act)["max_ccy_exposure"] == 3          # three shorts against the dollar = one big USD bet
    assert C.exposure("USDJPY", "long", [])["max_ccy_exposure"] == 1


def test_context_bands_let_the_scan_find_a_planted_entry_effect():
    rng = np.random.default_rng(1)
    n = 800
    df = pd.DataFrame(dict(symbol=rng.choice(["EURUSD", "GBPUSD"], n), created=pd.date_range("2024-01-01", periods=n, freq="9h", tz="UTC"),
                           reason="STOP", trig_stressed=True, mfe_r=np.abs(rng.normal(.6, .4, n)), mae_r=np.abs(rng.normal(.5, .3, n)),
                           direction=rng.choice(["long", "short"], n), atr_rank=rng.random(n), trend_with=rng.normal(1, 1.5, n), ext_ema20=np.abs(rng.normal(1, .7, n))))
    df["hour"], df["dow"] = df.created.dt.hour, df.created.dt.dayofweek
    net = rng.normal(0, 1, n) - np.where(df.atr_rank > .67, 0.8, 0.0)           # high-volatility entries lose more
    df["net_r_stressed"], df["gross_r"] = net, net + .05
    r = D.diagnose(df, "planted")
    assert any(s["feature"] == "vol_band" and s["bucket"] == "high vol" for s in r["scan"]["supported"])
