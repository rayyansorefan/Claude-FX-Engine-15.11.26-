import types
import pandas as pd
from fxengine.live import positions as P


def _t(fill, mfe=0.4, mae=0.2, bars=10):
    s = types.SimpleNamespace(entry=1.1000, risk=0.0020, max_hold_bars=100)
    return types.SimpleNamespace(s=s, state="TRIGGERED", fill=fill, stop=1.0980, target=1.1060, mfe=mfe, mae=mae, bars_held=bars)


def test_open_position_text_shows_progress_to_target_and_time_left():
    c = dict(pair="EURUSD", direction="long", type="trend_pullback", created="2026-11-17T09:00:00+00:00", expires="2026-11-18T09:00:00+00:00")
    txt = P.describe(c, _t(1.1000), 1.1030, pd.Timestamp("2026-11-17T10:00:00+00:00"))
    assert "FILLED" in txt and "+1.50R" in txt and "1.50R away" in txt and "90 five-minute bars" not in txt and "of 100 five-minute bars" in txt


def test_unfilled_setup_text_says_so():
    c = dict(pair="EURUSD", direction="short", type="asia_breakout", created="2026-11-17T09:00:00+00:00", expires="2026-11-17T20:00:00+00:00")
    t = _t(None); t.state = "PUBLISHED"
    assert "not filled yet" in P.describe(c, t, 1.1010, pd.Timestamp("2026-11-17T10:00:00+00:00"))
