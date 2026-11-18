"""Revolut-style cost model v1 (ASSUMPTIONS in docs/STOCKS_PLAN.md: replace with the owner's real plan fees; a replacement is a logged change).
Per side, as a fraction of trade value. net = (1 + gross) * (1 - cost_sell) / (1 + cost_buy) - 1."""
SLIP = {"normal": {"us": .0005, "us_etf": .0003, "uk": .0010, "uk_etf": .0006}, "stressed": {"us": .0010, "us_etf": .0006, "uk": .0020, "uk_etf": .0012}}
COMM = {"normal": .0005, "stressed": .0012}
FX = {"normal": {"us": 0.0, "us_etf": 0.0}, "stressed": {"us": .0025, "us_etf": .0025}}        # converting GBP <-> USD
STAMP = {"uk": .005}                                                                            # UK stock BUY only; UK ETFs are exempt
MODES = ("gross", "normal", "stressed")


def side_costs(kind: str, mode: str) -> tuple[float, float]:
    """(buy cost, sell cost) for a cost class and mode."""
    if mode == "gross":
        return 0.0, 0.0
    base = SLIP[mode][kind] + COMM[mode] + FX[mode].get(kind, 0.0)
    return base + STAMP.get(kind, 0.0), base


def net_return(gross: float, kind: str, mode: str) -> float:
    b, s = side_costs(kind, mode)
    return (1.0 + gross) * (1.0 - s) / (1.0 + b) - 1.0
