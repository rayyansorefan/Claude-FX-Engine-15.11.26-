"""The six pre-registered rules (docs/STOCKS_PLAN.md). Fixed textbook parameters, no fitting. Every signal at bar t uses data up to t only.
Swing rules: signal at the CLOSE of bar t, enter the NEXT open. Day rules: decided at the OPEN of bar t (prior data + that open), buy that open, sell that close."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from . import indicators as I


@dataclass
class Sig:
    entry: np.ndarray            # bool per bar
    exit: np.ndarray             # bool per bar (swing rules; evaluated at the close, executed next open)
    max_hold: int                # bars; 0 = day trade (open -> close of the same bar)


def _b(x: pd.Series) -> np.ndarray:
    return x.fillna(False).to_numpy(bool)


def rsi2_pullback(d: pd.DataFrame) -> Sig:
    c = d["close"]
    return Sig(_b((I.rsi(c, 2) < 10) & (c > I.sma(c, 200))), _b(c > I.sma(c, 5)), 10)


def breakout_20(d: pd.DataFrame) -> Sig:
    c = d["close"]
    return Sig(_b((c > I.prior_high(d["high"], 20)) & (c > I.sma(c, 50))), _b(c < I.prior_low(d["low"], 10)), 60)


def trend_50_200(d: pd.DataFrame) -> Sig:
    c = d["close"]
    s50, s200 = I.sma(c, 50), I.sma(c, 200)
    state = ((s50 > s200) & (c > s200)).fillna(False)
    return Sig(_b(state & ~state.shift(1, fill_value=False)), _b(c < s50), 250)


def gap_cont_day(d: pd.DataFrame) -> Sig:
    c = d["close"]
    gap = d["open"] / c.shift(1) - 1.0
    return Sig(_b((gap > 0.02) & (c.shift(1) > I.sma(c, 50).shift(1))), np.zeros(len(d), bool), 0)


def gap_fade_day(d: pd.DataFrame) -> Sig:
    c = d["close"]
    gap = d["open"] / c.shift(1) - 1.0
    return Sig(_b((gap < -0.02) & (c.shift(1) > I.sma(c, 200).shift(1))), np.zeros(len(d), bool), 0)


BAR_RULES = {"RSI2_PULLBACK": rsi2_pullback, "BREAKOUT_20": breakout_20, "TREND_50_200": trend_50_200, "GAP_CONT_DAY": gap_cont_day, "GAP_FADE_DAY": gap_fade_day}
RULES = ["RSI2_PULLBACK", "BREAKOUT_20", "TREND_50_200", "MOM_12_1", "GAP_CONT_DAY", "GAP_FADE_DAY"]
INFO = {"RSI2_PULLBACK": ("Short-term pullback", "RSI(2) under 10 in an uptrend (above its 200-day average), exit when it recovers"),
        "BREAKOUT_20": ("Breakout", "New 20-day high above the 50-day average, exit on a 10-day low"),
        "TREND_50_200": ("Long-term trend", "50-day average crosses above the 200-day, exit below the 50-day"),
        "MOM_12_1": ("Momentum", "Month-end: buy the top 20% by 12-month return (skipping the last month), hold a month"),
        "GAP_CONT_DAY": ("Day trade: gap up", "Opens 2%+ higher in an uptrend: buy the open, sell the close"),
        "GAP_FADE_DAY": ("Day trade: gap down", "Opens 2%+ lower in a long-term uptrend: buy the open, sell the close")}


def momentum_entries(panel: dict[str, pd.DataFrame], top: float = 0.2) -> dict[str, np.ndarray]:
    """MOM_12_1: at each month-end (last bar of the month across the panel), rank symbols by return from t-252 to t-21 (own bars) and take the top fraction."""
    rets = {}
    for s, d in panel.items():
        c = d["close"]
        rets[s] = c.shift(21) / c.shift(252) - 1.0
    r = pd.DataFrame(rets)
    idx = r.index
    month_end = pd.Series(idx, index=idx).groupby(idx.to_period("M")).max().values
    rank = r.loc[r.index.isin(month_end)].rank(axis=1, pct=True)
    sel = rank >= (1.0 - top)
    out = {}
    for s, d in panel.items():
        flag = sel[s].reindex(d.index).fillna(False) if s in sel else pd.Series(False, index=d.index)
        out[s] = flag.to_numpy(bool)
    return out
