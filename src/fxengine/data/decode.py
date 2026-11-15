"""Decode cTrader trendbars into a DataFrame. Prices are BID. Fixed-point: 1e-5.
low is absolute; deltaOpen/Close/High are non-negative offsets from low.
Timestamp = minutes since epoch (UTC) of the bar OPEN."""
import pandas as pd

SCALE = 100000.0
COLS = ["bid_o", "bid_h", "bid_l", "bid_c", "volume"]


def decode_trendbars(bars) -> pd.DataFrame:
    rows = []
    for b in bars:
        low = b.low
        rows.append((pd.Timestamp(b.utcTimestampInMinutes * 60, unit="s", tz="UTC"),
                     (low + getattr(b, "deltaOpen", 0)) / SCALE,
                     (low + getattr(b, "deltaHigh", 0)) / SCALE,
                     low / SCALE,
                     (low + getattr(b, "deltaClose", 0)) / SCALE,
                     float(b.volume)))
    if not rows:
        return pd.DataFrame(columns=COLS, index=pd.DatetimeIndex([], tz="UTC"))
    df = pd.DataFrame(rows, columns=["t"] + COLS).set_index("t").sort_index()
    return df[~df.index.duplicated(keep="last")]
