"""Causal indicators: value at row i uses data up to and including bar i's CLOSE only."""
import numpy as np
import pandas as pd


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False, min_periods=span).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df.bid_c.shift(1)
    tr = pd.concat([df.bid_h - df.bid_l, (df.bid_h - pc).abs(), (df.bid_l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["atr"] = atr(out)
    for n in (20, 50, 200):
        out[f"ema{n}"] = ema(out.bid_c, n)
    out["hour"] = out.index.hour
    out["date"] = out.index.normalize()
    return out
