"""FX market calendar. The market closes Friday 17:00 New York and reopens Sunday 17:00 New York; that is 21:00 or
22:00 UTC depending on daylight saving, so everything is computed in New York time, never with a fixed UTC hour.
Closed all day on 25 December and 1 January (no ticks => no candles => false 'stale' alarms otherwise)."""
import pandas as pd

NY = "America/New_York"
HOLIDAYS = {(12, 25), (1, 1)}


def ny(now) -> pd.Timestamp:
    t = pd.Timestamp(now)
    return (t.tz_localize("UTC") if t.tzinfo is None else t).tz_convert(NY)


def market_closed(now) -> bool:
    t = ny(now)
    if (t.month, t.day) in HOLIDAYS:
        return True
    d, h = t.day_of_week, t.hour
    return d == 5 or (d == 4 and h >= 17) or (d == 6 and h < 17)


def next_open(now) -> pd.Timestamp:
    """Next time the market is open (UTC). Used only for messages."""
    t = ny(now)
    while market_closed(t):
        t = (t + pd.Timedelta(hours=1)).floor("h")
    return t.tz_convert("UTC")
