"""Market-context snapshot taken at the moment a setup fires (closed bars only). Stored in the immutable setup record and in every backtest row,
so the engine can later ask WHICH conditions its winners and losers had in common (entry learning). Pure functions."""
from __future__ import annotations
import numpy as np
import pandas as pd


def snapshot(d: pd.DataFrame, pos: int, direction: str, spread_pips=None, h4: pd.DataFrame | None = None) -> dict:
    """d = prepared frame (needs atr, ema20/50/200, bid_c). All values use bars up to and including `pos` (closed)."""
    sign = 1 if direction == "long" else -1
    r = d.iloc[pos]
    a, c = float(r.atr), float(r.bid_c)
    if not (a > 0):
        return {}
    win = d.atr.iloc[max(0, pos - 99):pos + 1].dropna()
    rank = float((win <= a).mean()) if len(win) >= 20 else None
    out = dict(atr_pct=round(a / c * 100, 4), atr_rank=None if rank is None else round(rank, 3),
               trend_with=None if np.isnan(r.ema200) else round(float(sign * (r.ema50 - r.ema200) / a), 3),
               ext_ema20=None if np.isnan(r.ema20) else round(float(sign * (c - r.ema20) / a), 3),
               hour_utc=int(d.index[pos].hour), dow=int(d.index[pos].dayofweek))
    if spread_pips is not None:
        out["spread_pips"] = round(float(spread_pips), 2)
    if h4 is not None and len(h4):
        h = h4.iloc[-1]
        out["htf_align"] = None if np.isnan(h.ema200) else int(np.sign(sign * (h.ema50 - h.ema200)))
    return {k: v for k, v in out.items() if v is not None}


def exposure(pair: str, direction: str, active: list[dict]) -> dict:
    """Net currency exposure if this setup is added to the active ones: +1 per long base / short quote. Correlated setups lose together."""
    net: dict[str, int] = {}
    for p, dr in [(pair, direction)] + [(a["pair"], a["direction"]) for a in active]:
        s = 1 if dr == "long" else -1
        net[p[:3]] = net.get(p[:3], 0) + s
        net[p[3:]] = net.get(p[3:], 0) - s
    own = max(abs(net[pair[:3]]), abs(net[pair[3:]]))
    return dict(max_ccy_exposure=int(own), n_active=len(active))
