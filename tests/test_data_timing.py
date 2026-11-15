import numpy as np, pandas as pd, pytest
from fxengine.data.timeframes import close_time, closed_only, tf_delta
from fxengine.data.resample import resample
from fxengine.data.freshness import check_fresh, StaleDataError


def m1(start="2025-01-06 08:00", n=30):
    idx = pd.date_range(start, periods=n, freq="min", tz="UTC")
    p = 1.1 + np.arange(n) * 1e-4
    return pd.DataFrame({"bid_o": p, "bid_h": p + 5e-5, "bid_l": p - 5e-5, "bid_c": p + 1e-5,
                         "ask_o": p + 1e-4, "ask_h": p + 1.5e-4, "ask_l": p + 5e-5, "ask_c": p + 1.1e-4,
                         "volume": 1.0}, index=idx)


def test_close_time_is_open_plus_tf():
    o = pd.Timestamp("2025-01-06 08:00", tz="UTC")
    assert close_time(o, "M5") == o + pd.Timedelta(minutes=5)
    assert close_time(o, "H1") == o + pd.Timedelta(hours=1)


def test_candle_not_usable_before_close():
    df = m1(n=10)
    now = pd.Timestamp("2025-01-06 08:04:59", tz="UTC")
    assert closed_only(df, "M5", now).empty                      # 08:00 M5 closes 08:05
    assert len(closed_only(df, "M5", now + pd.Timedelta(seconds=1))) == 1


def test_unknown_timeframe():
    with pytest.raises(ValueError):
        tf_delta("M7")


def test_resample_drops_open_bucket():
    out = resample(m1(n=12), "M5")          # last M1 = 08:11 -> known to 08:12
    assert list(out.index.minute) == [0, 5]  # 08:10 bucket still open
    assert out.index[-1] + tf_delta("M5") <= pd.Timestamp("2025-01-06 08:12", tz="UTC")


def test_resample_ohlc_values():
    df = m1(n=10)
    out = resample(df, "M5").iloc[0]
    f = df.iloc[:5]
    assert out.bid_o == f.bid_o.iloc[0] and out.bid_c == f.bid_c.iloc[-1]
    assert out.bid_h == f.bid_h.max() and out.bid_l == f.bid_l.min() and out.n_m1 == 5


def test_resample_does_not_change_when_future_appended():
    """Look-ahead guard: a closed bar must be identical whether or not later data exists."""
    full = m1(n=30)
    a = resample(full.iloc[:15], "M5")
    b = resample(full, "M5")
    pd.testing.assert_frame_equal(a, b.loc[a.index])


def test_freshness_gate():
    last = pd.Timestamp("2025-01-06 08:05", tz="UTC")
    assert check_fresh(last, last + pd.Timedelta(seconds=120)) == 120
    with pytest.raises(StaleDataError):
        check_fresh(last, last + pd.Timedelta(seconds=301))
    with pytest.raises(StaleDataError):
        check_fresh(last, last - pd.Timedelta(seconds=60))      # future-dated
