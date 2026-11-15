"""Position size so that hitting the stop loses ~GBP risk. Research output only; the engine never trades."""
import math
from ..engine.costs import pip


def gbp_per_pip_per_lot(symbol: str, px: dict) -> float:
    """GBP value of one pip on a 100k-unit lot. px = latest close per pair (needs GBPUSD, and USDJPY/USDCHF/USDCAD/GBPJPY as relevant)."""
    q = symbol[3:]
    if q == "GBP":
        return 10.0
    if q == "USD":
        return 10.0 / px["GBPUSD"]
    if q == "JPY":
        return 1000.0 / px["GBPJPY"]
    if q == "CHF":
        return 10.0 / (px["GBPUSD"] * px["USDCHF"])
    if q == "CAD":
        return 10.0 / (px["GBPUSD"] * px["USDCAD"])
    raise ValueError(q)


def lots_for_risk(symbol, entry, stop, px, risk_gbp=20.0):
    stop_pips = abs(entry - stop) / pip(symbol)
    pv = gbp_per_pip_per_lot(symbol, px)
    lots = math.floor(risk_gbp / (stop_pips * pv) * 100) / 100
    return max(lots, 0.0), stop_pips
