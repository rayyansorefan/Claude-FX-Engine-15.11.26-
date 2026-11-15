"""Experiments E1/E2 (H4) — PARAMETERS FROZEN in docs/EXPERIMENTS.md. Causal; signals use data to bar close."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .v1 import _frame, _fmt, WARMUP

LOOKBACK, ZWIN, ZMIN, ZTOP = 30, 500, 1.5, 3


def donchian_trend(d: pd.DataFrame) -> pd.DataFrame:
    """E2: close above prior-55-bar high with EMA50>EMA200 (mirror for shorts). Stop 3 ATR, target 6 ATR.
    Invalid if a close comes back inside the channel before entry."""
    hh = d.bid_h.rolling(55).max().shift(1)
    ll = d.bid_l.rolling(55).min().shift(1)
    ok = d.atr.notna() & (np.arange(len(d)) >= WARMUP)
    up = ok & (d.bid_c > hh) & (d.bid_c.shift(1) <= hh) & (d.ema50 > d.ema200)
    dn = ok & (d.bid_c < ll) & (d.bid_c.shift(1) >= ll) & (d.ema50 < d.ema200)
    s = d[up | dn]
    long = up[s.index].values
    sign = np.where(long, 1, -1)
    e = s.bid_c.values
    lvl = np.where(long, hh[s.index], ll[s.index])
    reason = [f"Close {'above' if lg else 'below'} the 55-bar {'high' if lg else 'low'} {_fmt(v)} with EMA50 {'above' if lg else 'below'} EMA200\n"
              f"Stop 3 ATR, target 6 ATR (2R); cancel if a close returns inside the channel" for lg, v in zip(long, lvl)]
    return _frame(d, d.index.get_indexer(s.index), np.where(long, "long", "short"), e, "stop",
                  e - sign * 3 * s.atr.values, e + sign * 6 * s.atr.values,
                  (np.abs(s.bid_c - lvl) / s.atr).values, 3, 40, invalidation=lvl, reason=reason)


def strength_signals(frames: dict) -> dict:
    """E1: frames = {symbol: prepared H4 df}. Returns {symbol: signals}. Cross-sectional, causal."""
    close = pd.DataFrame({k: v.bid_c for k, v in frames.items()}).sort_index()
    ret = np.log(close).diff(LOOKBACK)
    ccy = {}
    for sym in close.columns:
        b, q = sym[:3], sym[3:]
        ccy.setdefault(b, []).append(ret[sym])
        ccy.setdefault(q, []).append(-ret[sym])
    strength = {c: pd.concat(v, axis=1).mean(axis=1) for c, v in ccy.items()}
    z = pd.DataFrame({sym: (strength[sym[:3]] - strength[sym[3:]]) for sym in close.columns})
    z = z / z.rolling(ZWIN, min_periods=250).std()
    rank = z.abs().rank(axis=1, ascending=False)
    out = {}
    for sym, d in frames.items():
        zz = z[sym].reindex(d.index)
        rk = rank[sym].reindex(d.index)
        ok = d.atr.notna() & (np.arange(len(d)) >= WARMUP) & (zz.abs() >= ZMIN) & (rk <= ZTOP)
        s = d[ok]
        long = (zz[ok] > 0).values
        sign = np.where(long, 1, -1)
        e = s.bid_c.values
        stop = e - sign * 2 * s.atr.values
        reason = [f"{sym[:3]} vs {sym[3:]} 5-day strength gap z={zv:+.1f}, top-{ZTOP} across the 10 pairs\n"
                  f"Enter {'long' if lg else 'short'} at the close, stop 2 ATR, target 4 ATR (2R), 2-bar expiry"
                  for lg, zv in zip(long, zz[ok].values)]
        out[sym] = _frame(d, d.index.get_indexer(s.index), np.where(long, "long", "short"), e, "stop",
                          stop, e + sign * 4 * s.atr.values, zz[ok].abs().values, 2, 12, invalidation=stop, reason=reason)
    return out


def with_trailing(sig: pd.DataFrame, rr: float, max_hold: int) -> pd.DataFrame:
    """Batch 2: same entries/stops, but the target is pushed out to rr x risk (practically never hit) and the
    hold limit extended; the exit is the trailing stop applied by backtest.run.track(trail=20)."""
    out = sig.copy()
    risk = (out.entry - out.stop).abs()
    sign = np.where(out.direction == "long", 1, -1)
    out["target"] = out.entry + sign * rr * risk
    out["max_hold"] = max_hold
    return out
