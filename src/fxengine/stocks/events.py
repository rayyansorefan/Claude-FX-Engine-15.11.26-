"""Events layer: company earnings (SEC EDGAR) and macro (FRED), deterministic and POINT-IN-TIME: every number is dated by when it was public, never by the period it describes.
Free, official sources only. The SEC requires a contact in the User-Agent: it is read from the SEC_CONTACT environment variable or data/stocks/sec_contact.txt on the VM
(never stored in the repository). Runs on the VM (the build sandbox cannot reach these hosts); everything here is tested against the sources' documented JSON/CSV shapes.
Earnings event = an 8-K carrying Item 2.02 (Results of Operations), dated by its filing date. Its numbers come from the XBRL company facts, using each quarter's value AS FIRST REPORTED
(later restatements are ignored, so nothing from the future leaks in). Surprise = standardised year-on-year change in quarterly EPS (the classic seasonal-random-walk SUE)."""
from __future__ import annotations
import csv
import json
import os
import time
from datetime import date
from pathlib import Path
import numpy as np
import pandas as pd

EDGAR = Path("data/stocks/edgar")
EVENTS = Path("data/stocks/events.parquet")
FRED_DIR = Path("data/stocks/fred")
FRED_SERIES = {"VIXCLS": "VIX volatility index", "T10Y2Y": "10y minus 2y Treasury yield", "BAMLH0A0HYM2": "High-yield credit spread"}
REV_TAGS = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax")
SUE_MIN_HISTORY = 6


def sec_contact(root: Path = Path(".")) -> str:
    c = os.environ.get("SEC_CONTACT", "").strip()
    f = root / "data/stocks/sec_contact.txt"
    if not c and f.exists():
        c = f.read_text().strip()
    if "@" not in c:
        raise SystemExit("SEC requires a contact in the User-Agent: put your email in data/stocks/sec_contact.txt (or the SEC_CONTACT variable) on the VM. It is never stored in git.")
    return c


def _http(url: str, contact: str):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": f"StocksResearch/1.0 ({contact})", "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read()


# ----------------------------- parsing (pure functions) ---------------------------------------------------------------
def ticker_to_cik(raw: dict) -> dict[str, str]:
    """company_tickers.json -> {'AAPL': '0000320193'}."""
    return {v["ticker"].upper(): f"{int(v['cik_str']):010d}" for v in raw.values()}


def earnings_8ks(sub: dict) -> list[dict]:
    """8-K filings that carry Item 2.02 (an earnings release), from a submissions JSON. Dated by filing date; acceptance time kept."""
    r = (sub.get("filings") or {}).get("recent") or {}
    out = []
    for form, d, items, acc in zip(r.get("form", []), r.get("filingDate", []), r.get("items", []), r.get("acceptanceDateTime", [])):
        if form == "8-K" and "2.02" in str(items).split(","):
            out.append(dict(date=d, accepted=acc))
    return sorted(out, key=lambda x: x["date"])


def _first_reported(units: list[dict], quarterly=True) -> pd.DataFrame:
    """Facts as FIRST reported: for each period end keep the earliest-filed value. Quarterly = ~3-month durations from a 10-Q."""
    rows = []
    for u in units:
        if u.get("form") not in ("10-Q", "10-K") or "end" not in u or "val" not in u or "filed" not in u:
            continue
        if quarterly:
            if not u.get("start") or u["form"] != "10-Q":
                continue
            days = (pd.Timestamp(u["end"]) - pd.Timestamp(u["start"])).days
            if not 70 <= days <= 110:
                continue
        rows.append(dict(end=pd.Timestamp(u["end"]), val=float(u["val"]), filed=pd.Timestamp(u["filed"])))
    if not rows:
        return pd.DataFrame(columns=["end", "val", "filed"])
    d = pd.DataFrame(rows).sort_values(["end", "filed"]).drop_duplicates("end", keep="first")
    return d.reset_index(drop=True)


def _facts(facts: dict, tags) -> list[dict]:
    g = (facts.get("facts") or {}).get("us-gaap", {})
    for t in tags:
        if t in g:
            u = g[t].get("units", {})
            for k in ("USD/shares", "USD", "pure"):
                if k in u:
                    return u[k]
    return []


def earnings_events(symbol: str, sub: dict, facts: dict) -> list[dict]:
    """One row per earnings release (8-K 2.02) that we can match to a quarterly 10-Q: EPS, EPS a year earlier, standardised surprise (SUE), revenue growth. Point-in-time."""
    eps = _first_reported(_facts(facts, ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic")))
    rev = _first_reported(_facts(facts, REV_TAGS))
    if eps.empty:
        return []
    out = []
    for ev in earnings_8ks(sub):
        d = pd.Timestamp(ev["date"])
        m = eps[(eps["end"] <= d - pd.Timedelta(days=5)) & (eps["end"] >= d - pd.Timedelta(days=130)) & (eps["filed"] >= d) & (eps["filed"] <= d + pd.Timedelta(days=75))]
        if m.empty:
            continue                                                  # a fiscal-year-end release (annual 10-K): not a quarterly fact, skipped on purpose
        q = m.sort_values("end").iloc[-1]
        prior = eps[eps["end"] < q["end"]].copy()
        py = prior[(prior["end"] - (q["end"] - pd.DateOffset(years=1))).abs() <= pd.Timedelta(days=20)]
        if py.empty:
            continue
        eps_prev = float(py.iloc[-1]["val"])
        # standardise by the volatility of PAST year-on-year changes only (quarters that ended before this one)
        hist = []
        for _, r in prior.iterrows():
            p = eps[(eps["end"] - (r["end"] - pd.DateOffset(years=1))).abs() <= pd.Timedelta(days=20)]
            p = p[p["end"] < r["end"]]
            if len(p):
                hist.append(float(r["val"]) - float(p.iloc[-1]["val"]))
        hist = hist[-8:]
        sd = float(np.std(hist, ddof=1)) if len(hist) >= SUE_MIN_HISTORY else float("nan")
        chg = float(q["val"]) - eps_prev
        sue = chg / sd if sd and sd == sd and sd > 1e-9 else float("nan")
        rg = float("nan")
        rq = rev[rev["end"] == q["end"]]
        rp = rev[(rev["end"] - (q["end"] - pd.DateOffset(years=1))).abs() <= pd.Timedelta(days=20)]
        rp = rp[rp["end"] < q["end"]]
        if len(rq) and len(rp) and float(rp.iloc[-1]["val"]) > 0:
            rg = float(rq.iloc[0]["val"]) / float(rp.iloc[-1]["val"]) - 1
        out.append(dict(symbol=symbol, announce_date=d, accepted=ev["accepted"], period_end=q["end"], eps=float(q["val"]), eps_prev=eps_prev, eps_change=chg, sue=sue, rev_yoy=rg, n_hist=len(hist)))
    return out


def parse_fred(text: str, series: str) -> pd.Series:
    """FRED fredgraph.csv -> Series by observation date ('.' or blank = missing)."""
    rows = list(csv.reader(text.strip().splitlines()))
    if len(rows) < 2:
        return pd.Series(dtype=float)
    out = {}
    for r in rows[1:]:
        if len(r) >= 2 and r[1] not in (".", "", "NA"):
            try:
                out[pd.Timestamp(r[0])] = float(r[1])
            except ValueError:
                pass
    return pd.Series(out).sort_index()


def macro_context(fred: dict[str, pd.Series], index: pd.DatetimeIndex) -> pd.DataFrame:
    """Daily macro read for the cross-engine context. Every value is LAGGED one trading day (FRED publishes a day's value after the day), so nothing from the future is used."""
    df = pd.DataFrame(index=index)
    for k, name in (("VIXCLS", "vix"), ("T10Y2Y", "curve_10y2y"), ("BAMLH0A0HYM2", "hy_spread")):
        if k in fred and len(fred[k]):
            s = fred[k].reindex(index, method="ffill").shift(1)
            df[name] = s
            m, sd = s.rolling(250, min_periods=120).mean(), s.rolling(250, min_periods=120).std()
            df[name + "_z"] = (s - m) / sd.replace(0, np.nan)
    return df


# ----------------------------- I/O (runs on the VM) -------------------------------------------------------------------
def fetch_all(symbols: list[str], root: Path = Path("."), get=None, pause: float = 0.2, refresh_days: int = 7) -> pd.DataFrame:
    """Download submissions + company facts for the US stocks, cache them, and build the events table. Never stops on one bad company."""
    contact = sec_contact(root) if get is None else "test@example.com"
    get = get or (lambda u: _http(u, contact))
    d = root / EDGAR
    d.mkdir(parents=True, exist_ok=True)
    st, body = get("https://www.sec.gov/files/company_tickers.json")
    cik = ticker_to_cik(json.loads(body)) if st == 200 else {}
    rows, gaps = [], []
    for sym in symbols:
        t = sym.split(".")[0].upper().replace("-", "-")
        c = cik.get(t) or cik.get(t.replace("-", "."))
        if not c:
            gaps.append(f"{sym}: no SEC CIK")
            continue
        try:
            files = {}
            for kind, url in (("sub", f"https://data.sec.gov/submissions/CIK{c}.json"), ("facts", f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c}.json")):
                f = d / f"{sym}_{kind}.json"
                if not (f.exists() and (time.time() - f.stat().st_mtime) < refresh_days * 86400):
                    s2, b = get(url)
                    time.sleep(pause)
                    if s2 != 200:
                        raise RuntimeError(f"HTTP {s2}")
                    f.write_bytes(b if isinstance(b, bytes) else str(b).encode())
                files[kind] = json.loads(f.read_text())
            ev = earnings_events(sym, files["sub"], files["facts"])
            rows += ev
            print(f"{sym}: {len(ev)} earnings events", flush=True)
        except Exception as e:
            gaps.append(f"{sym}: {type(e).__name__}")
            print(f"{sym}: FAILED {type(e).__name__}", flush=True)
    df = pd.DataFrame(rows)
    if len(df):
        (root / EVENTS).parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(root / EVENTS)
    (root / "data/stocks/events_gaps.txt").write_text("\n".join(gaps))
    return df


YAHOO_MACRO = {"VIXCLS": "%5EVIX", "TNX": "%5ETNX", "IRX": "%5EIRX"}       # fallback when FRED does not answer: VIX, 10-year yield, 13-week bill yield


def _yahoo_close(get, symbol: str) -> pd.Series:
    from .data import YAHOO, parse_yahoo
    st, b = get(YAHOO.format(t=symbol, now=int(time.time())))
    csv_ = parse_yahoo((b.decode("utf-8", "replace") if isinstance(b, bytes) else str(b))) if st == 200 else ""
    if not csv_:
        return pd.Series(dtype=float)
    return pd.Series({pd.Timestamp(r["Date"]): float(r["Close"]) for r in csv.DictReader(csv_.splitlines()) if r.get("Close") not in (None, "", "nan")}).sort_index()


def _write_fred_format(path: Path, series: pd.Series, name: str) -> None:
    path.write_text("observation_date," + name + "\n" + "".join(f"{d:%Y-%m-%d},{v}\n" for d, v in series.items()))


def fetch_fred(root: Path = Path("."), get=None) -> dict[str, pd.Series]:
    import urllib.request

    def default(u):
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (research-script)"})
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read()
    get = get or default
    d = root / FRED_DIR
    d.mkdir(parents=True, exist_ok=True)
    for sid in FRED_SERIES:
        f = d / f"{sid}.csv"
        for attempt in (1, 2):                                       # one retry: FRED is sometimes slow
            try:
                st, b = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}")
                if st == 200 and len(b) > 100:
                    f.write_bytes(b)
                    break
            except Exception as e:
                print(f"FRED {sid} attempt {attempt}: {type(e).__name__}", flush=True)
    try:                                                              # Yahoo fallback for whatever FRED did not give us (credit spread has none)
        if not (d / "VIXCLS.csv").exists():
            v = _yahoo_close(get, YAHOO_MACRO["VIXCLS"])
            if len(v):
                _write_fred_format(d / "VIXCLS.csv", v, "VIXCLS")
                print("VIX from Yahoo (FRED unavailable)", flush=True)
        if not (d / "T10Y2Y.csv").exists():
            t10, t3 = _yahoo_close(get, YAHOO_MACRO["TNX"]), _yahoo_close(get, YAHOO_MACRO["IRX"])
            if len(t10) and len(t3):
                _write_fred_format(d / "T10Y2Y.csv", (t10 - t3.reindex(t10.index, method="ffill")).dropna(), "T10Y2Y")
                print("yield-curve slope (10y minus 13-week) from Yahoo (FRED unavailable)", flush=True)
    except Exception as e:
        print("Yahoo macro fallback failed:", type(e).__name__, flush=True)
    return load_fred(root)


def load_fred(root: Path = Path(".")) -> dict[str, pd.Series]:
    d = root / FRED_DIR
    return {sid: parse_fred((d / f"{sid}.csv").read_text(), sid) for sid in FRED_SERIES if (d / f"{sid}.csv").exists()}


def load(root: Path = Path(".")) -> pd.DataFrame | None:
    p = root / EVENTS
    return pd.read_parquet(p) if p.exists() else None


def days_since_earnings(ev: pd.DataFrame | None, symbol: str, d) -> int | None:
    """Calendar days since the company's last earnings release as of date d (strictly before d), or None."""
    if ev is None or ev.empty:
        return None
    e = ev[(ev["symbol"] == symbol) & (ev["announce_date"] < pd.Timestamp(d))]
    return int((pd.Timestamp(d) - e["announce_date"].max()).days) if len(e) else None


if __name__ == "__main__":
    from .universe import SYMBOLS
    us = [s for s in SYMBOLS if s.endswith(".us") and not s.split(".")[0] in ("spy", "qqq", "iwm", "dia", "xlk", "xlf", "xle", "xlv", "xly", "xlp", "xli", "xlu", "gld", "tlt")]
    df = fetch_all(us)
    fr = fetch_fred()
    print(f"earnings events: {len(df)} for {df['symbol'].nunique() if len(df) else 0} companies · FRED series: {sorted(fr)}")
