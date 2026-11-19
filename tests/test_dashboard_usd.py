from fxengine.dashboard import build as B


def test_usd_notional_for_each_pair_type():
    rates = {"EUR": 1.10, "GBP": 1.30, "AUD": 0.65, "NZD": 0.60}
    assert B.usd_notional("EURUSD", 0.28, 1.1000, rates) == 0.28 * 100000 * 1.1000          # quote is USD: units x price
    assert B.usd_notional("USDJPY", 0.5, 150.0, rates) == 50000.0                               # base is USD: just the units
    assert abs(B.usd_notional("EURGBP", 0.1, 0.85, rates) - 11000.0) < 1e-6                     # cross: units x USD per EUR
    assert abs(B.usd_notional("GBPJPY", 0.1, 190.0, rates) - 13000.0) < 1e-6
    assert B.usd_notional("EURGBP", 0.1, 0.85, {}) is None and B.usd_notional("EURUSD", None, 1.1, rates) is None
    assert B.usd_txt(28000.4) == "$28,000" and B.usd_txt(None) == ""
