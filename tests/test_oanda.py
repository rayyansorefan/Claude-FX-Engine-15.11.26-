import re, pathlib
import pandas as pd
from fxengine.data.oanda import parse_candles, instrument

P = {"candles": [
    {"complete": True, "volume": 12, "time": "2025-01-06T08:00:00.000000000Z",
     "bid": {"o": "1.03000", "h": "1.03050", "l": "1.02980", "c": "1.03020"},
     "ask": {"o": "1.03008", "h": "1.03058", "l": "1.02988", "c": "1.03028"}},
    {"complete": False, "volume": 3, "time": "2025-01-06T08:05:00.000000000Z",
     "bid": {"o": "1", "h": "1", "l": "1", "c": "1"}, "ask": {"o": "1", "h": "1", "l": "1", "c": "1"}}]}


def test_parse_keeps_only_complete_and_both_sides():
    df = parse_candles(P)
    assert len(df) == 1 and df.index[0] == pd.Timestamp("2025-01-06 08:00", tz="UTC")
    assert df.iloc[0].ask_o - df.iloc[0].bid_o > 0


def test_instrument_name_and_readonly():
    assert instrument("EURUSD") == "EUR_USD"
    src = pathlib.Path(__file__).parent.parent / "src/fxengine/data/oanda.py"
    urls = re.findall(r'f"\{HOST\}([^"]+)"', src.read_text())
    assert all("/candles" in u for u in urls)       # only the candles endpoint is ever called
