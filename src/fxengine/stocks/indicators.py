"""Indicators on pandas Series. Each value at bar t uses bars <= t only (tested)."""
import numpy as np
import pandas as pd


def sma(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(n, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI."""
    d = close.diff()
    up, dn = d.clip(lower=0.0), (-d).clip(lower=0.0)
    au, ad = up.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean(), dn.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    return out.where(ad != 0.0, 100.0).where(au.notna() & ad.notna())


def prior_high(high: pd.Series, n: int) -> pd.Series:
    """Highest high of the PREVIOUS n bars (excludes today)."""
    return high.rolling(n, min_periods=n).max().shift(1)


def prior_low(low: pd.Series, n: int) -> pd.Series:
    return low.rolling(n, min_periods=n).min().shift(1)
