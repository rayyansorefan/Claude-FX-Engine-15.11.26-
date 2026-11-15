"""Candle timing. RULE: a candle is labelled by its OPEN time; it is only
knowable at close_time = open_time + timeframe. Never use it earlier."""
from __future__ import annotations
import pandas as pd

TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}


def tf_delta(tf: str) -> pd.Timedelta:
    try:
        return pd.Timedelta(seconds=TF_SECONDS[tf])
    except KeyError:
        raise ValueError(f"unknown timeframe {tf!r}") from None


def close_time(open_time, tf: str):
    """Time at which the candle opened at `open_time` becomes known."""
    return pd.Timestamp(open_time) + tf_delta(tf)


def closed_only(df: pd.DataFrame, tf: str, now) -> pd.DataFrame:
    """Rows whose candle has fully closed at `now` (index = open time, UTC)."""
    now = pd.Timestamp(now)
    return df[df.index + tf_delta(tf) <= now]


def add_close_time(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    out = df.copy()
    out["close_time"] = out.index + tf_delta(tf)
    return out
