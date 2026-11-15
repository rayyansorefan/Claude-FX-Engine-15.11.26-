"""Setup types v1 — PARAMETERS FROZEN (pre-registered, not tuned). Operates on CLOSED bars of the signal timeframe.
Each generator returns a DataFrame of signals (one row per signal bar) using only data up to that
bar's close. Rows: pos (bar position), direction, entry, kind, stop, target, score, expiry_bars, max_hold,
invalidation (pre-trigger cancel level, added 2026-11-15 for the published record; the frozen H1/M15 research
runner ignores it), reason (two short lines built from the signal's own numbers)."""
from __future__ import annotations
import numpy as np
import pandas as pd

VERSION = "v1"
TYPES = ["asia_breakout", "trend_pullback", "range_reversion"]
WARMUP = 300


def _frame(d: pd.DataFrame, pos, direction, entry, kind, stop, target, score, expiry_bars, max_hold,
           invalidation=None, reason=""):
    out = pd.DataFrame({"pos": pos, "direction": direction, "entry": entry, "kind": kind,
                        "stop": stop, "target": target, "score": score,
                        "expiry_bars": expiry_bars, "max_hold": max_hold})
    out["invalidation"] = np.nan if invalidation is None else invalidation
    out["reason"] = reason
    return out


def _fmt(v):
    return f"{v:.3f}" if v > 20 else f"{v:.5f}"


def asia_breakout(d: pd.DataFrame) -> pd.DataFrame:
    """First close beyond the Asian range (00:00-07:00 UTC) during 07:00-09:45; one per day.
    Enter on stop at the close; stop 1.5 ATR; target 3 ATR (2R). Invalid if a close comes back inside the range."""
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
    h_, l_, w_ = hi[s.index].values, lo[s.index].values, width[s.index].values
    reason = [f"First close {'above' if lg else 'below'} the Asian range {_fmt(l)}-{_fmt(h)} ({w:.1f} ATR wide)\n"
              f"Stop 1.5 ATR beyond entry, target 2R; cancel if a bar closes back inside the range"
              for lg, h, l, w in zip(long.values, h_, l_, w_)]
    return _frame(d, d.index.get_indexer(s.index), np.where(long, "long", "short"), entry.values, "stop",
                  (entry - sign * 1.5 * a).values, (entry + sign * 3.0 * a).values,
                  w_, 4, 32, invalidation=np.where(long, h_, l_), reason=reason)


def trend_pullback(d: pd.DataFrame) -> pd.DataFrame:
    """Trend (EMA50 vs EMA200, rising) + bar touches EMA20 and closes back through it; enter on stop
    beyond the bar; stop 0.5 ATR past the bar's far side; target 2R. Invalid if a close goes beyond the stop first."""
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
    strength = (np.abs(s.ema50 - s.ema200) / s.atr).values
    reason = [f"{'Up' if lg else 'Down'}trend (EMA50 {'above' if lg else 'below'} EMA200 by {st:.1f} ATR); price touched EMA20 and closed back {'above' if lg else 'below'} it\n"
              f"Entry on a break of the bar's {'high' if lg else 'low'}, stop 0.5 ATR past its {'low' if lg else 'high'}, target 2R"
              for lg, st in zip(long.values, strength)]
    out = _frame(d, d.index.get_indexer(s.index), np.where(long, "long", "short"), entry, "stop", stop, target,
                 strength, 4, 32, invalidation=stop, reason=reason)
    return out[keep].reset_index(drop=True)


def range_reversion(d: pd.DataFrame) -> pd.DataFrame:
    """In a flat regime (|EMA50-EMA200| < 1.5 ATR) fade a close >= 2 ATR from EMA20; limit at the close;
    stop 1.5 ATR beyond; target = EMA20. Invalid if a close goes beyond the stop before the limit fills."""
    hrs = (d.hour >= 7) & (d.hour <= 19) & d.atr.notna() & (np.arange(len(d)) >= WARMUP)
    flat = (d.ema50 - d.ema200).abs() < 1.5 * d.atr
    z = (d.bid_c - d.ema20) / d.atr
    sh, lg = hrs & flat & (z >= 2.0), hrs & flat & (z <= -2.0)
    s = d[lg | sh]
    long = lg[s.index]
    entry = s.bid_c.values
    stop = np.where(long, entry - 1.5 * s.atr, entry + 1.5 * s.atr)
    zz = z[s.index].abs().values
    reason = [f"Flat market; close is {zv:.1f} ATR {'below' if lg else 'above'} the EMA20\n"
              f"Limit {'buy' if lg else 'sell'} at the close, stop 1.5 ATR beyond, target back at the EMA20"
              for lg, zv in zip(long.values, zz)]
    return _frame(d, d.index.get_indexer(s.index), np.where(long, "long", "short"), entry, "limit", stop,
                  s.ema20.values, zz, 4, 24, invalidation=stop, reason=reason)


GENERATORS = {"asia_breakout": asia_breakout, "trend_pullback": trend_pullback, "range_reversion": range_reversion}
