"""Cost model v1 (FROZEN per version). Data is BID-only, so ask = bid + spread.
ALL numbers below are ASSUMPTIONS modelled on Pepperstone Razor (tight spread + commission),
deliberately pessimistic. Replace with measured live spreads when recorded; log any change.
Units: pips. STRESS multiplies spread/slippage; thin hours (21:00-23:59 UTC rollover) cost more."""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

BASE_SPREAD_PIPS = {"EURUSD": .3, "GBPUSD": .5, "USDJPY": .4, "USDCHF": .6, "AUDUSD": .5,
                    "USDCAD": .6, "NZDUSD": .7, "EURGBP": .6, "EURJPY": .8, "GBPJPY": 1.2}
COMMISSION_ROUND_TRIP_PIPS = 0.7     # ~USD 7 per 100k round trip
SLIPPAGE_PIPS = 0.3                  # on stop-type fills only (stop entries, stop losses)
SWAP_PIPS_PER_NIGHT = 0.3            # assumed AGAINST the trade, both directions (pessimistic)
STRESS = 2.0                         # spread & slippage multiplier in stressed mode
THIN_MULT = 2.5                      # 21:00-23:59 UTC


def pip(symbol: str) -> float:
    return 0.01 if symbol.endswith("JPY") else 0.0001


@dataclass(frozen=True)
class CostModel:
    stressed: bool = True

    def _mult(self, ts) -> float:
        m = STRESS if self.stressed else 1.0
        return m * (THIN_MULT if pd.Timestamp(ts).hour >= 21 else 1.0)

    def spread(self, symbol, ts) -> float:
        return BASE_SPREAD_PIPS[symbol] * pip(symbol) * self._mult(ts)

    def slippage(self, symbol, ts) -> float:
        return SLIPPAGE_PIPS * pip(symbol) * self._mult(ts)

    def commission(self, symbol) -> float:
        return COMMISSION_ROUND_TRIP_PIPS * pip(symbol)

    def swap_per_night(self, symbol) -> float:
        return SWAP_PIPS_PER_NIGHT * pip(symbol)


def rollover_nights(t0, t1) -> int:
    """Charged nights between t0 and t1: each 22:00 UTC rollover counts 1; Wednesday counts 3;
    Saturday/Sunday none."""
    t0, t1 = pd.Timestamp(t0), pd.Timestamp(t1)
    n = 0
    d = t0.normalize() + pd.Timedelta(hours=22)
    if d <= t0:
        d += pd.Timedelta(days=1)
    while d <= t1:
        wd = d.day_of_week
        n += 3 if wd == 2 else (0 if wd >= 5 else 1)
        d += pd.Timedelta(days=1)
    return n
