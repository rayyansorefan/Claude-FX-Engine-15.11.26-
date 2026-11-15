"""Setup types v1 — PARAMETERS FROZEN (pre-registered, not tuned). Operates on M15 CLOSED bars.
Each generator returns a DataFrame of signals (one row per signal bar) using only data up to that
bar's close. Rows: pos (bar position), direction, entry, kind, stop, target, score, expiry_bars, max_hold."""
from __future__ import annotations
import numpy as np
import pandas as pd

VERSION = "v1"
TYPES = ["asia_breakout", "trend_pullback", "range_reversion"]
WARMUP = 300


def _frame(d: pd.DataFrame, pos, direction, entry, kind, stop, target, score, expiry_bars, max_hold):
    return pd.DataFrame({"pos": pos, "direction": direction, "entry": entry, "kind": kind,
                         "stop": stop, "target": target, "score": score,
                         "expiry_bars": expiry_bars, "max_hold": max_hold})


def asia_breakout(d: pd.DataFrame) -> pd.DataFrame:
    """First close beyond the Asian range (00:00-07:00 UTC) during 07:00-09:45; one per day.
    Enter on stop at the close; stop 1.5 ATR; target 3 ATR (2R)."""
    asia = d.hour < 7
    hi = d.bid_h.where(asia).groupby(d.date).transform("max")
    lo = d.bid_l.where(asia).groupby(d.date).transform("min")
    width = (hi - lo) / d.atr
    window = (d.hour >= 7) & ((d.hour < 9) | ((d.hour == 9) & (d.index.minute <= 45)))
    ok = window & (width >= 0.5) & (width <= 4) & d.atr.notna()
    up = ok & (d.bid_c > hi) & (d.bid_c.shift(1) <= hi)
    dn = ok & (d.bid_c < lo) & (d.bid_c.shift(1) >= lo)
    sig = (up | dn) & (np.arange(len(d)) >= WARMUP)
    s = d[sig].groupby(d.date[sig]).head(1)
    long = (s.bid_c > hi[s.index])
    a = s.atr
    entry = s.bid_c
    sign = np.where(long, 1, -1)
    return _frame(d, d.index.get_indexer(s.index), np.where(long, "long", "short"), entry.values, "stop",
                  (entry - sign * 1.5 * a).values, (entry + sign * 3.0 * a).values,
                  width[s.index].values, 4, 32)


def trend_pullback(d: pd.DataFrame) -> pd.DataFrame:
    """Trend (EMA50 vs EMA200, rising) + bar touches EMA20 and closes back through it; enter on stop
    beyond the bar; stop 0.5 ATR past the bar's far side; target 2R."""
    hrs = (d.hour >= 7) & (d.hour <= 19) & d.atr.notna() & (np.arange(len(d)) >= WARMUP)
    up = (d.ema50 > d.ema200) & (d.ema50 > d.ema50.shift(8)) & (d.bid_c > d.ema200)
    dn = (d.ema50 < d.ema200) & (d.ema50 < d.ema50.shift(8)) & (d.bid_c < d.ema200)
    lg = hrs & up & (d.bid_l <= d.ema20) & (d.bid_c > d.ema20) & (d.bid_c > d.bid_o)
    sh = hrs & dn & (d.bid_h >= d.ema20) & (d.bid_c < d.ema20) & (d.bid_c < d.bid_o)
    s = d[lg | sh]
    long = lg[s.index]
    entry = np.where(long, s.bid_h, s.bid_l)
    stop = np.where(long, s.bid_l - 0.5 * s.atr, s.bid_h + 0.5 * s.atr)
    risk = np.abs(entry - stop)
    target = np.where(long, entry + 2 * risk, entry - 2 * risk)
    keep = (risk <= 2.5 * s.atr.values)
    out = _frame(d, d.index.get_indexer(s.index), np.where(long, "long", "short"), entry, "stop", stop, target,
                 (np.abs(s.ema50 - s.ema200) / s.atr).values, 4, 32)
    return out[keep].reset_index(drop=True)


def range_reversion(d: pd.DataFrame) -> pd.DataFrame:
    """In a flat regime (|EMA50-EMA200| < 1.5 ATR) fade a close >= 2 ATR from EMA20; limit at the close;
    stop 1.5 ATR beyond; target = EMA20."""
    hrs = (d.hour >= 7) & (d.hour <= 19) & d.atr.notna() & (np.arange(len(d)) >= WARMUP)
    flat = (d.ema50 - d.ema200).abs() < 1.5 * d.atr
    z = (d.bid_c - d.ema20) / d.atr
    sh, lg = hrs & flat & (z >= 2.0), hrs & flat & (z <= -2.0)
    s = d[lg | sh]
    long = lg[s.index]
    entry = s.bid_c.values
    stop = np.where(long, entry - 1.5 * s.atr, entry + 1.5 * s.atr)
    return _frame(d, d.index.get_indexer(s.index), np.where(long, "long", "short"), entry, "limit", stop,
                  s.ema20.values, z[s.index].abs().values, 4, 24)


GENERATORS = {"asia_breakout": asia_breakout, "trend_pullback": trend_pullback, "range_reversion": range_reversion}
