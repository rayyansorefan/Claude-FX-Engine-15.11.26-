"""Resample candles to a higher timeframe without look-ahead.
Works on any OHLC column set with prefixes like bid_/ask_ (or plain o,h,l,c + volume).
Index = base-candle OPEN time (UTC). Output index = bucket open time.
A bucket is kept only if its close time <= the close of the last base candle we hold
(or `now`), so a forming bucket is never emitted."""
import pandas as pd
from .timeframes import tf_delta

_FN = {"o": "first", "h": "max", "l": "min", "c": "last"}


def _agg_map(cols):
    agg = {}
    for c in cols:
        if c == "volume":
            agg[c] = "sum"
        elif c.rsplit("_", 1)[-1] in _FN and c not in ("n_base",):
            agg[c] = _FN[c.rsplit("_", 1)[-1]]
    return agg


def resample(df: pd.DataFrame, tf: str, base: str = "M1", now=None) -> pd.DataFrame:
    if tf_delta(tf) < tf_delta(base) or tf_delta(tf) % tf_delta(base):
        raise ValueError(f"cannot build {tf} from {base}")
    agg = _agg_map([c for c in df.columns if c != "n_base"])
    g = df.resample(f"{int(tf_delta(tf).total_seconds())}s", label="left", closed="left")
    out = g.agg(agg)
    out["n_base"] = g[next(iter(agg))].count()
    out = out[out["n_base"] > 0]
    ref = pd.Timestamp(now) if now is not None else df.index.max() + tf_delta(base)
    return out[out.index + tf_delta(tf) <= ref]
