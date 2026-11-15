import pandas as pd
from fxengine.calendar import market_closed, next_open

U = lambda s: pd.Timestamp(s, tz="UTC")


def test_summer_close_is_2100_utc_and_winter_2200_utc():
    assert market_closed(U("2025-06-06 21:30"))            # Friday 17:30 New York (EDT): closed
    assert not market_closed(U("2025-06-06 20:59"))
    assert not market_closed(U("2025-01-10 21:30"))        # Friday 16:30 New York (EST): still open
    assert market_closed(U("2025-01-10 22:00"))
    assert market_closed(U("2025-06-08 20:59")) and not market_closed(U("2025-06-08 21:00"))   # Sunday reopen EDT
    assert market_closed(U("2025-01-12 21:59")) and not market_closed(U("2025-01-12 22:00"))   # Sunday reopen EST
    assert market_closed(U("2025-06-07 12:00"))            # Saturday


def test_holidays_and_next_open():
    assert market_closed(U("2025-12-25 10:00")) and market_closed(U("2026-01-01 10:00"))
    assert not market_closed(U("2025-12-24 10:00"))
    assert next_open(U("2025-06-07 12:00")) == U("2025-06-08 21:00")
