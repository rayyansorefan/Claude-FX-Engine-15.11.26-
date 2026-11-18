"""Cross-engine learning link. Two engines, kept separate, each publishes its market read; each can then TEST (on data it has not seen) whether the other's read improves its own trades.
Stocks -> FX: equity regime, breadth, volatility (daily history since 2000, point-in-time: the value on a date uses data up to that day's close only) -> docs/results/stocks_context_history.csv
FX -> Stocks: USD strength and risk mood from daily FX rates (Yahoo daily FX, free, history from 2003): computed here, stored with every stock setup, tested in the entry-filter study.
Nothing here reads or writes the FX engine's files. Research only."""
from __future__ import annotations
import csv
import json
from pathlib import Path
import numpy as np
import pandas as pd
from . import indicators as I
from .universe import kind as kind_of

FX_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "AUDJPY"]      # Yahoo: <PAIR>=X
USD_PAIRS = FX_PAIRS[:-1]
HIST = Path("docs/results/stocks_context_history.csv")
LATEST = Path("docs/results/stocks_context.json")


def load_fx(raw: Path = Path("data/stocks/raw")) -> dict[str, pd.Series]:
    out = {}
    for p in FX_PAIRS:
        f = raw / f"fx_{p}.csv"
        if f.exists():
            r = list(csv.DictReader(f.open()))
            if r and "Close" in r[0]:
                s = pd.Series({pd.Timestamp(x["Date"]): float(x["Close"]) for x in r if x.get("Close") not in (None, "", "nan")}).sort_index()
                if len(s) > 300:
                    out[p] = s
    return out


def _z(x: pd.Series, n: int = 250) -> pd.Series:
    """Standardise against the PAST year only (rolling), so a value never uses the future."""
    m, sd = x.rolling(n, min_periods=120).mean(), x.rolling(n, min_periods=120).std()
    return (x - m) / sd.replace(0, np.nan)


def usd_strength(fx: dict[str, pd.Series]) -> pd.Series:
    """Log-index of the US dollar against the six majors (equal weight): up = the dollar is getting stronger. EURUSD rising means the dollar FALLS, USDJPY rising means it RISES."""
    rets = []
    for p in USD_PAIRS:
        if p in fx:
            r = np.log(fx[p]).diff()
            rets.append(-r if p.endswith("USD") else r)
    if not rets:
        return pd.Series(dtype=float)
    return pd.concat(rets, axis=1).mean(axis=1, skipna=True).cumsum()


def build(panel: dict[str, pd.DataFrame], fx: dict[str, pd.Series] | None = None) -> pd.DataFrame:
    """Daily context indexed by SPY's trading dates. Every column at date t uses data up to the close of t only."""
    spy = panel.get("spy.us")
    if spy is None or len(spy) < 260:
        return pd.DataFrame()
    c = spy["close"]
    s200 = I.sma(c, 200)
    df = pd.DataFrame(index=c.index)
    df["spy_vs200"] = c / s200 - 1
    df["spy_trend"] = np.sign(df["spy_vs200"])
    df["spy_5d"] = c.pct_change(5)
    df["vol20"] = c.pct_change().rolling(20).std() * np.sqrt(252)
    flags = {s: (d["close"] > I.sma(d["close"], 200)).where(I.sma(d["close"], 200).notna()) for s, d in panel.items() if not kind_of(s).endswith("_etf") and len(d) > 260}
    if flags:
        b = pd.DataFrame(flags).reindex(c.index)
        df["breadth200"] = b.mean(axis=1).where(b.notna().sum(axis=1) >= 20)
    if fx:
        u = usd_strength(fx).reindex(c.index, method="ffill")
        df["usd_20d_z"] = _z(u.diff(20))
        if "AUDJPY" in fx:
            aj = np.log(fx["AUDJPY"]).reindex(c.index, method="ffill")
            df["risk_20d_z"] = _z(aj.diff(20))
    df["dow"] = c.index.dayofweek
    return df


def publish(ctx: pd.DataFrame, hist: Path = HIST, latest: Path = LATEST) -> dict | None:
    """The file the FX engine can read: daily history (for its own entry-filter study) and today's snapshot."""
    if ctx.empty:
        return None
    hist.parent.mkdir(parents=True, exist_ok=True)
    cols = [c for c in ("spy_trend", "spy_vs200", "spy_5d", "vol20", "breadth200") if c in ctx]
    ctx[cols].round(5).to_csv(hist, index_label="date")
    row = ctx.iloc[-1]
    snap = dict(asof=f"{ctx.index[-1]:%Y-%m-%d}", **{k: (None if pd.isna(v) else round(float(v), 5)) for k, v in row.items()},
                about="Equity-market context from the Stocks engine. Point-in-time: each value uses data up to that day's close only. History: stocks_context_history.csv.")
    latest.write_text(json.dumps(snap, indent=1))
    return snap


def at(ctx: pd.DataFrame, date) -> dict:
    """Context as known at the close of `date` (the last row on or before it)."""
    if ctx.empty:
        return {}
    i = ctx.index.searchsorted(pd.Timestamp(date), side="right") - 1
    if i < 0:
        return {}
    return {k: (None if pd.isna(v) else round(float(v), 4)) for k, v in ctx.iloc[i].items()}
