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


def donchian_55(d: pd.DataFrame) -> Sig:
    c = d["close"]
    return Sig(_b(c > I.prior_high(d["high"], 55)), _b(c < I.prior_low(d["low"], 20)), 120)


def vol_breakout(d: pd.DataFrame) -> Sig:
    c, v = d["close"], d["volume"]
    return Sig(_b((c > I.prior_high(d["high"], 20)) & (v > 2.0 * I.sma(v, 20).shift(1)) & (c > I.sma(c, 50))), _b(c < I.prior_low(d["low"], 10)), 60)


def adx_trend(d: pd.DataFrame) -> Sig:
    c = d["close"]
    a, pdi, mdi = I.adx(d["high"], d["low"], c, 14)
    return Sig(_b((a > 25) & (a.shift(1) <= 25) & (pdi > mdi) & (c > I.sma(c, 50))), _b((a < 20) | (c < I.sma(c, 50))), 120)


def bollinger_revert(d: pd.DataFrame) -> Sig:
    c = d["close"]
    m, _, lo = I.bollinger(c, 20, 2.0)
    return Sig(_b((c < lo) & (c > I.sma(c, 200))), _b(c > m), 10)


def ibs_revert(d: pd.DataFrame) -> Sig:
    c = d["close"]
    return Sig(_b((I.ibs(d["high"], d["low"], c) < 0.2) & (c > I.sma(c, 200))), _b(c > d["high"].shift(1)), 5)


def stoch_pullback(d: pd.DataFrame) -> Sig:
    c = d["close"]
    k = I.stoch_k(d["high"], d["low"], c, 14)
    return Sig(_b((k < 20) & (c > I.sma(c, 200))), _b(k > 70), 15)


def macd_cross(d: pd.DataFrame) -> Sig:
    c = d["close"]
    m, sg = I.macd(c)
    up = (m > sg) & (m.shift(1) <= sg.shift(1))
    return Sig(_b(up & (m < 0) & (c > I.sma(c, 200))), _b((m < sg) & (m.shift(1) >= sg.shift(1))), 60)


BAR_RULES = {"RSI2_PULLBACK": rsi2_pullback, "BREAKOUT_20": breakout_20, "TREND_50_200": trend_50_200, "GAP_CONT_DAY": gap_cont_day, "GAP_FADE_DAY": gap_fade_day,
             "DONCHIAN_55": donchian_55, "VOL_BREAKOUT": vol_breakout, "ADX_TREND": adx_trend, "BOLLINGER_REVERT": bollinger_revert, "IBS_REVERT": ibs_revert,
             "STOCH_PULLBACK": stoch_pullback, "MACD_CROSS": macd_cross}
RULES = ["RSI2_PULLBACK", "BREAKOUT_20", "TREND_50_200", "MOM_12_1", "GAP_CONT_DAY", "GAP_FADE_DAY",
         "HIGH52_MOM", "DONCHIAN_55", "VOL_BREAKOUT", "ADX_TREND", "BOLLINGER_REVERT", "IBS_REVERT", "STOCH_PULLBACK", "MACD_CROSS", "RS_PULLBACK", "PEAD_SUE"]
PANEL_RULES = ("MOM_12_1", "HIGH52_MOM", "RS_PULLBACK", "PEAD_SUE")                  # rules that need the whole panel (cross-section, or the market as a reference)
MAX_HOLD = {"RSI2_PULLBACK": 10, "BREAKOUT_20": 60, "TREND_50_200": 250, "MOM_12_1": 21, "HIGH52_MOM": 21, "DONCHIAN_55": 120, "VOL_BREAKOUT": 60, "ADX_TREND": 120,
            "BOLLINGER_REVERT": 10, "IBS_REVERT": 5, "STOCH_PULLBACK": 15, "MACD_CROSS": 60, "RS_PULLBACK": 10, "PEAD_SUE": 40}
INFO = {"RSI2_PULLBACK": ("Short-term pullback", "RSI(2) under 10 in an uptrend (above its 200-day average), exit when it recovers"),
        "BREAKOUT_20": ("Breakout", "New 20-day high above the 50-day average, exit on a 10-day low"),
        "TREND_50_200": ("Long-term trend", "50-day average crosses above the 200-day, exit below the 50-day"),
        "MOM_12_1": ("Momentum", "Month-end: buy the top 20% by 12-month return (skipping the last month), hold a month"),
        "GAP_CONT_DAY": ("Day trade: gap up", "Opens 2%+ higher in an uptrend: buy the open, sell the close"),
        "GAP_FADE_DAY": ("Day trade: gap down", "Opens 2%+ lower in a long-term uptrend: buy the open, sell the close"),
        "HIGH52_MOM": ("Near 52-week high", "Month-end: buy stocks within 5% of their 52-week high that are up over 6 months, hold a month"),
        "DONCHIAN_55": ("55-day breakout", "New 55-day high, exit on a 20-day low (the classic 'turtle' breakout)"),
        "VOL_BREAKOUT": ("Volume breakout", "20-day high on at least 2x normal volume, above the 50-day average"),
        "ADX_TREND": ("Strong trend starts", "ADX crosses above 25 with buyers in control, exit when the trend fades"),
        "BOLLINGER_REVERT": ("Bollinger snap-back", "Closes below its lower Bollinger band in an uptrend, exit at the middle band"),
        "IBS_REVERT": ("Weak close snap-back", "Closes in the bottom 20% of its day's range in an uptrend, exit above the prior day's high"),
        "STOCH_PULLBACK": ("Stochastic pullback", "Stochastic under 20 in an uptrend, exit when it passes 70"),
        "MACD_CROSS": ("MACD cross-up", "MACD crosses above its signal below zero, in an uptrend (a popular indicator, tested honestly)"),
        "PEAD_SUE": ("Earnings surprise drift", "A big positive earnings surprise (SEC filing): buy the day after the reaction day, hold about 8 weeks"),
        "RS_PULLBACK": ("Leader pullback", "A market-beating stock (6-month) with RSI(5) under 30 in an uptrend, exit above its 5-day average")}


def high52_entries(panel: dict[str, pd.DataFrame]) -> dict[str, np.ndarray]:
    """HIGH52_MOM (George & Hwang): at each month-end, stocks within 5% of their 52-week high and up over 126 days."""
    out = {}
    for s, d in panel.items():
        c = d["close"]
        cond = (c >= 0.95 * d["high"].rolling(252, min_periods=252).max()) & (c / c.shift(126) - 1 > 0)
        me = pd.Series(d.index, index=d.index).groupby(d.index.to_period("M")).transform("max") == d.index
        out[s] = (cond.fillna(False) & me).to_numpy(bool)
    return out


def rs_pullback_sigs(panel: dict[str, pd.DataFrame]) -> dict[str, Sig]:
    """RS_PULLBACK: a stock that beat the S&P over 6 months, short-term oversold (RSI(5) < 30), in an uptrend; exit above its 5-day average."""
    spy = panel.get("spy.us")
    out = {}
    for s, d in panel.items():
        c = d["close"]
        if spy is None or s == "spy.us":
            out[s] = Sig(np.zeros(len(d), bool), np.zeros(len(d), bool), 10)
            continue
        rs = (c / c.shift(126) - 1) - (spy["close"] / spy["close"].shift(126) - 1).reindex(d.index, method="ffill")
        out[s] = Sig(_b((rs > 0) & (I.rsi(c, 5) < 30) & (c > I.sma(c, 200))), _b(c > I.sma(c, 5)), 10)
    return out


def panel_sigs(rule: str, panel: dict[str, pd.DataFrame]) -> dict[str, Sig]:
    """Signals for the panel-level rules, one Sig per symbol."""
    if rule == "RS_PULLBACK":
        return rs_pullback_sigs(panel)
    ent = momentum_entries(panel) if rule == "MOM_12_1" else high52_entries(panel)
    return {s: Sig(ent[s], np.zeros(len(d), bool), 21) for s, d in panel.items()}


SUE_MIN, PEAD_HOLD = 2.0, 40


def pead_sigs(panel: dict[str, pd.DataFrame], events: pd.DataFrame | None) -> dict[str, Sig]:
    """PEAD_SUE (Bernard & Thomas): after a large positive standardised earnings surprise (SUE >= 2, EPS up, revenue up) buy. POINT-IN-TIME and conservative: the company's release
    (SEC 8-K filing date D) is treated as public at D; the signal is the close of the FIRST trading day after D (the reaction day), so the buy is at the open after that."""
    out = {s: Sig(np.zeros(len(d), bool), np.zeros(len(d), bool), PEAD_HOLD) for s, d in panel.items()}
    if events is None or len(events) == 0:
        return out
    good = events[(events["sue"] >= SUE_MIN) & (events["eps_change"] > 0) & ((events["rev_yoy"] > 0) | events["rev_yoy"].isna())]
    for s, g in good.groupby("symbol"):
        if s not in panel:
            continue
        d = panel[s]
        for D in g["announce_date"]:
            i = d.index.searchsorted(pd.Timestamp(D), side="right")           # first bar strictly after the filing date
            if i < len(d):
                out[s].entry[i] = True
    return out


def rule_sigs(rule: str, panel: dict[str, pd.DataFrame], events: pd.DataFrame | None = None) -> dict[str, Sig]:
    """Signals of ANY pre-registered swing rule for every symbol (the one entry point the research and the scanner both use)."""
    if rule == "PEAD_SUE":
        return pead_sigs(panel, events)
    if rule in PANEL_RULES:
        return panel_sigs(rule, panel)
    return {s: BAR_RULES[rule](d) for s, d in panel.items()}


SWING_RULES = [r for r in RULES if r not in ("GAP_CONT_DAY", "GAP_FADE_DAY")]      # decided at a close, entered at the next open (the day-trade rules are decided at the open)
MONTHLY_RULES = ("MOM_12_1", "HIGH52_MOM")                                           # only fire on the last trading day of a month


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
