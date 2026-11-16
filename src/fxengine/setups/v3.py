"""Batch 3 (E6 momentum, E7 carry+momentum) on DAILY bars that close 17:00 New York. PARAMETERS FROZEN in docs/EXPERIMENTS.md
(pre-registered 2026-11-16 before any result). Causal: the signal at a Friday close uses data up to that close only.
Signals are CHANGES of a weekly position state; the position is held until the state next changes (exit_at), a 3-ATR stop, or
84 calendar days. Entry is a stop order at the Friday close, so a weekend gap is paid for, not ignored."""
from __future__ import annotations
import numpy as np
import pandas as pd
from ..calendar import NY
from ..features.indicators import atr

LOOKBACK = 60            # trading days
STOP_ATR = 3.0
TARGET_ATR = 10.0        # practically no profit target
MAX_HOLD_DAYS = 84       # calendar days (~60 trading days)
MIN_DIFF_PP = 1.0        # E7: minimum rate differential, percentage points
MARKUP = 0.01            # E7: broker financing mark-up, 1.0 percentage point per year, charged on every position
WARMUP = LOOKBACK + 25


def prep(d: pd.DataFrame) -> pd.DataFrame:
    out = d.copy()
    out["atr20"] = atr(out, 20)
    out["ret"] = out.bid_c / out.bid_c.shift(LOOKBACK) - 1
    out["fri"] = out.close_time.dt.tz_convert(NY).dt.day_of_week == 4
    return out


def _state_to_signals(d: pd.DataFrame, state: pd.Series, carry=None) -> pd.DataFrame:
    """state: -1/0/+1 on Friday-close rows, NaN elsewhere. Emits a signal whenever the state changes to non-zero."""
    pos = np.flatnonzero(state.notna().values)
    st = state.values[pos]
    rows, prev = [], 0.0
    for k, (p, s) in enumerate(zip(pos, st)):
        if s != 0 and s != prev:
            q = next((pos[m] for m in range(k + 1, len(pos)) if st[m] != s), None)
            exit_at = d.close_time.iloc[q] if q is not None else d.close_time.iloc[-1] + pd.Timedelta(days=MAX_HOLD_DAYS)
            exit_at = min(exit_at, d.close_time.iloc[p] + pd.Timedelta(days=MAX_HOLD_DAYS))
            a = float(d.atr20.iloc[p])
            e = float(d.bid_c.iloc[p])
            if not a > 0:
                prev = s
                continue
            sign = 1 if s > 0 else -1
            rows.append(dict(pos=p, direction="long" if sign > 0 else "short", entry=e, kind="stop",
                             stop=e - sign * STOP_ATR * a, target=e + sign * TARGET_ATR * a, score=abs(float(d.ret.iloc[p])),
                             exit_at=exit_at, carry_annual=(np.nan if carry is None else sign * float(carry.iloc[p]) / 100.0 - MARKUP)))
        prev = s
    return pd.DataFrame(rows, columns=["pos", "direction", "entry", "kind", "stop", "target", "score", "exit_at", "carry_annual"])


def tsmom_signals(d: pd.DataFrame) -> pd.DataFrame:
    """E6: sign of the 60-day return at each Friday close."""
    d = d if "atr20" in d.columns else prep(d)
    ok = d.fri & d.ret.notna() & d.atr20.notna() & (np.arange(len(d)) >= WARMUP)
    state = pd.Series(np.where(ok, np.sign(d.ret), np.nan), index=d.index)
    return _state_to_signals(d, state)


def carry_mom_signals(d: pd.DataFrame, diff_pp: pd.Series) -> pd.DataFrame:
    """E7: trade only when the rate differential (percentage points, as KNOWN at the close) agrees in sign with the 60-day
    momentum and is at least MIN_DIFF_PP. Carry is earned/paid by sign, minus the broker mark-up."""
    d = d if "atr20" in d.columns else prep(d)
    diff = pd.Series(np.asarray(diff_pp), index=d.index)
    mom = np.sign(d.ret)
    agree = (np.sign(diff) == mom) & (diff.abs() >= MIN_DIFF_PP) & (mom != 0)
    ok = d.fri & d.ret.notna() & d.atr20.notna() & diff.notna() & (np.arange(len(d)) >= WARMUP)
    state = pd.Series(np.where(ok, np.where(agree, mom, 0.0), np.nan), index=d.index)
    return _state_to_signals(d, state, carry=diff)
