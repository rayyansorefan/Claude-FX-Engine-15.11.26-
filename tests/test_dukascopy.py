import lzma, struct
import pandas as pd
from fxengine.data.dukascopy import decode_day, divisor, url, REC


def blob(recs):
    return lzma.compress(b"".join(REC.pack(*r) for r in recs))


def test_decode_ohlc_order_and_time():
    day = pd.Timestamp("2025-01-06")
    raw = blob([(0, 108000, 108050, 107990, 108100, 5.0), (60, 108050, 108020, 108000, 108060, 3.0)])
    df = decode_day(raw, day, "EURUSD", "bid")
    r = df.iloc[0]
    assert (r.bid_o, r.bid_c, r.bid_l, r.bid_h) == (1.08, 1.0805, 1.0799, 1.081)
    assert df.index[1] == pd.Timestamp("2025-01-06 00:01:00")


def test_jpy_divisor_and_empty():
    assert divisor("USDJPY") == 1e3 and divisor("EURUSD") == 1e5
    assert decode_day(b"", pd.Timestamp("2025-01-06"), "EURUSD", "bid").empty


def test_url_month_is_zero_based():
    assert url("EURUSD", pd.Timestamp("2025-01-06"), "bid").endswith("EURUSD/2025/00/06/BID_candles_min_1.bi5")
