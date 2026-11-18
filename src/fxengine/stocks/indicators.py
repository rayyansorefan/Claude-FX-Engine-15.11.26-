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


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    pc = close.shift(1)
    return pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    return true_range(high, low, close).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14):
    """Wilder ADX with +DI / -DI. Returns (adx, plus_di, minus_di)."""
    up, dn = high.diff(), -low.diff()
    plus = ((up > dn) & (up > 0)) * up
    minus = ((dn > up) & (dn > 0)) * dn
    a = atr(high, low, close, n)
    pdi = 100 * plus.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean() / a
    mdi = 100 * minus.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean(), pdi, mdi


def stoch_k(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    lo, hi = low.rolling(n, min_periods=n).min(), high.rolling(n, min_periods=n).max()
    return 100 * (close - lo) / (hi - lo).replace(0, np.nan)


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    m, sd = close.rolling(n, min_periods=n).mean(), close.rolling(n, min_periods=n).std()
    return m, m + k * sd, m - k * sd


def macd(close: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9):
    line = close.ewm(span=fast, adjust=False, min_periods=slow).mean() - close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    return line, line.ewm(span=sig, adjust=False, min_periods=sig).mean()


def ibs(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Internal bar strength: where the close sits inside the day's range (0 = at the low, 1 = at the high)."""
    return (close - low) / (high - low).replace(0, np.nan)
