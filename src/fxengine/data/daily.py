"""Daily bars that close at 17:00 New York (the FX trading-day convention), built from M5 bid/ask candles.
DST-safe: bins are calendar days in New York time with a 17:00 offset, so winter/summer both close at 17:00 NY.
The Friday 17:00 bar is the last of the week; the bucket starting Sunday 17:00 NY is the Monday trading day.
Only COMPLETE buckets are kept (close <= last M5 close, enough M5 bars), so no forming day is ever used."""
from __future__ import annotations
import pandas as pd
from ..calendar import NY

M5 = pd.Timedelta(minutes=5)
MIN_BARS = 100            # a normal day has ~288 M5 bars; holiday-thin days still pass


def daily_bars_ny(m5: pd.DataFrame) -> pd.DataFrame:
    """Index = bar OPEN time (UTC). Extra column `close_time` (UTC) = start of the next NY-17:00 bucket. Columns as input."""
    if m5.empty:
        return m5.assign(close_time=pd.Series(dtype="datetime64[ns, UTC]"))
    cols = [c for c in m5.columns if c[-2:] in ("_o", "_h", "_l", "_c") or c == "volume"]
    agg = {c: ("first" if c.endswith("_o") else "max" if c.endswith("_h") else "min" if c.endswith("_l")
               else "last" if c.endswith("_c") else "sum") for c in cols}
    # Bucket by New York WALL-CLOCK time shifted back 17h: each bucket key is the calendar date on which the trading day
    # started (it opens 17:00 NY). Wall-clock keys are DST-safe because the 02:00 transitions never fall at 17:00.
    wall = m5.index.tz_convert(NY).tz_localize(None)
    key = (wall - pd.Timedelta(hours=17)).floor("D")
    g = m5.groupby(key)
    out = g.agg(agg)
    out["n"] = g[cols[0]].count()
    out = out[out["n"] >= MIN_BARS].drop(columns="n")
    start_ny = (out.index + pd.Timedelta(hours=17)).tz_localize(NY)
    close_ny = (out.index + pd.Timedelta(days=1, hours=17)).tz_localize(NY)
    out["close_time"] = close_ny.tz_convert("UTC")
    out.index = start_ny.tz_convert("UTC")
    last_close = m5.index[-1] + M5
    out = out[out["close_time"] <= last_close]
    return out.iloc[1:] if len(out) else out                         # first bucket may be partial at data start
