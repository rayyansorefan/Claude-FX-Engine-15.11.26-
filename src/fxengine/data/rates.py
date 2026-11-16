"""Interest-rate data for the carry experiment (E7). Free source: FRED CSV downloads (no key).
Series are OECD 3-month interbank rates, monthly, one per currency.  !! SERIES IDS ARE UNVERIFIED from the build sandbox
(FRED not reachable there): `fetch_rates()` must be run on the VM, and it reports every gap loudly. Do not run E7 on a
rates file that `gap_report()` flags.
LOOK-AHEAD GUARD: a monthly value is only treated as known 45 days after the start of its month (publication lag)."""
from __future__ import annotations
from io import StringIO
from pathlib import Path
import pandas as pd

SERIES = {"USD": "IR3TIB01USM156N", "EUR": "IR3TIB01EZM156N", "GBP": "IR3TIB01GBM156N", "JPY": "IR3TIB01JPM156N",
          "CHF": "IR3TIB01CHM156N", "AUD": "IR3TIB01AUM156N", "CAD": "IR3TIB01CAM156N", "NZD": "IR3TIB01NZM156N"}
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
PATH = Path("data/rates.csv")
LAG_DAYS = 45


def parse_fred(text: str) -> pd.Series:
    if text.lstrip().startswith("<"):
        raise ValueError("FRED returned an HTML page, not CSV (wrong endpoint, blocked, or rate limited)")
    df = pd.read_csv(StringIO(text))
    df.columns = ["date", "v"]
    df["v"] = pd.to_numeric(df["v"], errors="coerce")          # FRED uses '.' for missing
    s = df.dropna().set_index(pd.to_datetime(df.dropna()["date"], utc=True))["v"]
    return s


def fetch_rates(path: Path = PATH, getter=None) -> pd.DataFrame:
    import requests
    getter = getter or (lambda u: requests.get(u, timeout=30).text)
    cols = {}
    for ccy, sid in SERIES.items():
        cols[ccy] = parse_fred(getter(URL.format(sid)))
    df = pd.DataFrame(cols).sort_index()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path)
    return df


def load_rates(path: Path = PATH) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    return df


def gap_report(df: pd.DataFrame, start="2023-06-01", end="2026-05-14") -> dict:
    """Per currency: last observation and missing months inside [start, end]. Empty dict values = clean."""
    want = pd.date_range(start, end, freq="MS", tz="UTC")
    out = {}
    for c in SERIES:
        if c not in df.columns:
            out[c] = "column missing"
            continue
        s = df[c].dropna()
        miss = [str(m.date())[:7] for m in want if not ((s.index.year == m.year) & (s.index.month == m.month)).any()]
        out[c] = {"last": str(s.index.max().date()) if len(s) else None, "missing_months": miss}
    return out


def rates_known_at(df: pd.DataFrame, times: pd.DatetimeIndex) -> pd.DataFrame:
    """Rates (percent) as KNOWN at each time: each monthly value becomes available LAG_DAYS after its month starts."""
    avail = df.copy()
    avail.index = avail.index + pd.Timedelta(days=LAG_DAYS)
    return avail.sort_index().reindex(avail.index.union(times)).ffill().reindex(times)


def main():
    """python -m fxengine.data.rates  -> downloads, saves data/rates.csv and prints the gap report (run on the VM)."""
    import json
    df = fetch_rates()
    print(json.dumps(gap_report(df), indent=1))
    print("saved", PATH, "rows", len(df))


if __name__ == "__main__":
    main()


def pair_diff(sym: str, known: pd.DataFrame) -> pd.Series:
    """Base-minus-quote rate differential in percentage points (positive: long the pair earns carry before mark-up)."""
    return known[sym[:3]] - known[sym[3:]]
