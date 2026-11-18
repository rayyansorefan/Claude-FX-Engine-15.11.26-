"""Currency conversion into pounds with the standard library only (the 5-minute live job must stay light). Reads the same files the nightly account uses."""
import csv
from bisect import bisect_right
from pathlib import Path
from .universe import currency


def load(raw: Path = Path("data/stocks/raw")) -> dict[str, tuple[list[str], list[float]]]:
    """{'USD': (dates, units_of_currency_per_GBP)}"""
    out = {}
    files = [("USD", raw / "gbpusd.csv")] + [(f.stem.split("_")[1].upper(), f) for f in raw.glob("gbp_*.csv")]
    for cur, f in files:
        if not f.exists():
            continue
        rows = sorted((r["Date"], float(r["Close"])) for r in csv.DictReader(f.open()) if r.get("Close") not in (None, "", "nan"))
        if rows:
            out[cur] = ([d for d, _ in rows], [v for _, v in rows])
    return out


def per_gbp(rates: dict, cur: str, day: str) -> float:
    s = rates.get(cur)
    if s:
        i = bisect_right(s[0], day) - 1
        if i >= 0:
            return s[1][i]
    return 1.30 if cur == "USD" else 1.0


def gbp(rates: dict, sym: str, price: float, day: str) -> float:
    cur, div = currency(sym)
    major = price / div
    return major if cur == "GBP" else major / per_gbp(rates, cur, day)
