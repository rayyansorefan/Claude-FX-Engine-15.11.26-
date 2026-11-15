import os, threading
import numpy as np, pandas as pd
from fxengine.data import store
from fxengine.data.quality import quality


def frame(start, n):
    idx = pd.date_range(start, periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"bid_o": 1.0, "bid_h": 1.0, "bid_l": 1.0, "bid_c": 1.0}, index=idx)


def test_store_merge_idempotent(tmp_path):
    a = frame("2025-01-06 08:00", 10)
    store.merge_save("EURUSD", "M5", a, tmp_path)
    store.merge_save("EURUSD", "M5", a.iloc[5:], tmp_path)
    out = store.load("EURUSD", "M5", tmp_path)
    assert len(out) == 10 and out.index.is_monotonic_increasing and not out.index.duplicated().any()
    assert store.last_open("EURUSD", "M5", tmp_path) == a.index[-1]


def test_store_concurrent_writers_lose_nothing_and_never_corrupt(tmp_path):
    """Live loop + research run write the same file: with the lock and atomic replace no rows are lost and a
    reader never sees a half-written parquet (this failed before 2026-11-15)."""
    store.merge_save("EURUSD", "M5", frame("2025-01-01", 500), tmp_path)
    errs = []

    def writer(start):
        for k in range(25):
            try:
                store.merge_save("EURUSD", "M5", frame(start + pd.Timedelta(minutes=50 * k), 10), tmp_path)
            except Exception as e:
                errs.append(e)

    def reader():
        for _ in range(60):
            try:
                store.load("EURUSD", "M5", tmp_path)
            except Exception as e:
                errs.append(e)
    ths = [threading.Thread(target=writer, args=(pd.Timestamp("2025-02-01", tz="UTC"),)),
           threading.Thread(target=writer, args=(pd.Timestamp("2025-03-01", tz="UTC"),)), threading.Thread(target=reader)]
    [t.start() for t in ths]; [t.join() for t in ths]
    assert not errs and len(store.load("EURUSD", "M5", tmp_path)) == 500 + 250 + 250
    assert not [f for f in os.listdir(tmp_path / "EURUSD") if ".tmp" in f]      # no temp files left behind


def test_quality_flags_odd_gap_but_not_weekend():
    idx = list(pd.date_range("2025-01-10 20:00", periods=12, freq="5min", tz="UTC"))
    idx += list(pd.date_range("2025-01-12 22:00", periods=12, freq="5min", tz="UTC"))     # weekend gap: fine
    idx += list(pd.date_range("2025-01-13 06:00", periods=12, freq="5min", tz="UTC"))     # 7h gap on a Monday: odd
    df = pd.DataFrame({"bid_o": 1.0, "bid_h": 1.0, "bid_l": 1.0, "bid_c": 1.0}, index=pd.DatetimeIndex(idx))
    q = quality(df, "M5")
    assert q["gaps_gt_tf"] == 2 and len(q["odd_gaps"]) == 1 and q["dupes"] == 0


def test_no_order_messages_in_src():
    """Read-only by design: no order/trade message names anywhere in the package."""
    import pathlib
    bad = ("NewOrder", "ClosePosition", "AmendOrder", "/orders", "/trades", "OrderReq", "ProtoOANewOrder")
    for f in pathlib.Path("src").rglob("*.py"):
        txt = f.read_text()
        for b in bad:
            assert b not in txt, (f, b)
