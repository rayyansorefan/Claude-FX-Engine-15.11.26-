"""Data-quality report for a candle frame: gaps, duplicates, bad OHLC, weekend rows."""
import pandas as pd
from .timeframes import tf_delta


def quality(df: pd.DataFrame, tf: str) -> dict:
    if df.empty:
        return {"rows": 0}
    d = tf_delta(tf)
    gaps = df.index.to_series().diff().dropna()
    big = gaps[gaps > d * 1]
    # a normal weekend gap is ~48h; flag anything > 4h on intraday that is not a weekend
    odd = big[(big > pd.Timedelta(hours=4)) & ~((big > pd.Timedelta(hours=40)) & (big < pd.Timedelta(hours=75)))]
    bad = ((df.bid_h < df[["bid_o", "bid_c"]].max(axis=1)) | (df.bid_l > df[["bid_o", "bid_c"]].min(axis=1))).sum()
    return {"rows": len(df), "first": str(df.index[0]), "last": str(df.index[-1]),
            "dupes": int(df.index.duplicated().sum()), "bad_ohlc": int(bad),
            "gaps_gt_tf": int(len(big)), "odd_gaps": [(str(i), str(v)) for i, v in odd.head(20).items()],
            "weekend_rows": int((df.index.day_of_week.isin([5])).sum())}
