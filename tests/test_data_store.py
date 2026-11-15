from types import SimpleNamespace as NS
import pandas as pd
from fxengine.data.decode import decode_trendbars
from fxengine.data import store
from fxengine.data.quality import quality


def bar(minute, low, do, dh, dc, vol=10):
    return NS(utcTimestampInMinutes=minute, low=low, deltaOpen=do, deltaHigh=dh, deltaClose=dc, volume=vol)


def test_decode_prices_and_time():
    m = 29_000_000  # arbitrary minute count
    df = decode_trendbars([bar(m, 108000, 50, 120, 80)])
    r = df.iloc[0]
    assert (r.bid_l, r.bid_o, r.bid_h, r.bid_c) == (1.08, 1.0805, 1.0812, 1.0808)
    assert df.index[0] == pd.Timestamp(m * 60, unit="s", tz="UTC")


def test_decode_sorts_and_dedupes():
    df = decode_trendbars([bar(10, 100000, 0, 10, 5), bar(5, 100000, 0, 10, 5), bar(10, 100000, 0, 20, 5)])
    assert list(df.index.minute % 60) == [5, 10] and df.iloc[1].bid_h == 1.0002


def test_store_merge_idempotent(tmp_path):
    a = decode_trendbars([bar(5 * i, 100000, 0, 10, 5) for i in range(4)])
    b = decode_trendbars([bar(5 * i, 100000, 0, 10, 5) for i in range(2, 7)])
    store.merge_save("EURUSD", "M5", a, tmp_path)
    df = store.merge_save("EURUSD", "M5", b, tmp_path)
    assert len(df) == 7 and df.index.is_monotonic_increasing
    assert store.last_open("EURUSD", "M5", tmp_path) == df.index.max()


def test_quality_flags_odd_gap_but_not_weekend():
    idx = list(pd.date_range("2025-01-06", periods=3, freq="5min", tz="UTC"))
    idx += [idx[-1] + pd.Timedelta(hours=10)]
    df = decode_trendbars([bar(int(t.timestamp() // 60), 100000, 0, 10, 5) for t in idx])
    q = quality(df, "M5")
    assert q["gaps_gt_tf"] == 1 and len(q["odd_gaps"]) == 1 and q["bad_ohlc"] == 0


def test_no_order_messages_in_data_layer():
    """Safety: research-only. The data layer must never reference order/trading messages."""
    import pathlib, re
    src = pathlib.Path(__file__).parent.parent / "src" / "fxengine"
    bad = re.compile(r"NewOrder|AmendOrder|CancelOrder|ClosePosition|AmendPosition|ProtoOAExecution", re.I)
    for f in src.rglob("*.py"):
        assert not bad.search(f.read_text()), f"{f} references trading messages"
