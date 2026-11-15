"""Dukascopy free M1 history (BID + ASK candles) -> store as M1. Run from the user's own machine.
Polite: 1 worker, spaced requests, backoff on 429, resumable (skips days already stored).
Format (UNVERIFIED against live files until first Mac run): daily file per side,
LZMA-compressed 24-byte big-endian records: uint32 secs-from-00:00UTC, open, close, low, high
(uint32, price*1e5; *1e3 for JPY pairs), float32 volume. URL month is 0-based."""
from __future__ import annotations
import lzma, struct, time, logging
import pandas as pd
import requests
from . import store

log = logging.getLogger("duka")
BASE = "https://datafeed.dukascopy.com/datafeed"
REC = struct.Struct(">IIIIIf")


def divisor(symbol: str) -> float:
    return 1e3 if symbol.endswith("JPY") else 1e5


def decode_day(raw: bytes, day: pd.Timestamp, symbol: str, side: str) -> pd.DataFrame:
    """raw = compressed bytes. Returns columns {side}_o/h/l/c, volume; index = M1 open time UTC."""
    if not raw:
        return pd.DataFrame()
    data = lzma.decompress(raw)
    n = len(data) // REC.size
    if n == 0:
        return pd.DataFrame()
    rows = [REC.unpack_from(data, i * REC.size) for i in range(n)]
    d = divisor(symbol)
    base = pd.Timestamp(day).normalize()
    idx = [base + pd.Timedelta(seconds=r[0]) for r in rows]
    df = pd.DataFrame({f"{side}_o": [r[1] / d for r in rows], f"{side}_c": [r[2] / d for r in rows],
                       f"{side}_l": [r[3] / d for r in rows], f"{side}_h": [r[4] / d for r in rows],
                       "volume": [r[5] for r in rows]}, index=pd.DatetimeIndex(idx))
    return df


def url(symbol, day, side):
    return f"{BASE}/{symbol}/{day.year}/{day.month - 1:02d}/{day.day:02d}/{side.upper()}_candles_min_1.bi5"


def get(sess, u, retries=6):
    wait = 5
    for _ in range(retries):
        r = sess.get(u, timeout=30)
        if r.status_code == 200:
            return r.content
        if r.status_code == 404:
            return b""
        if r.status_code == 429 or r.status_code >= 500:
            log.warning("HTTP %s, backing off %ss", r.status_code, wait)
            time.sleep(wait)
            wait = min(wait * 2, 300)
            continue
        r.raise_for_status()
    raise RuntimeError(f"gave up on {u}")


def fetch_day(sess, symbol, day) -> pd.DataFrame:
    bid = decode_day(get(sess, url(symbol, day, "bid")), day, symbol, "bid")
    ask = decode_day(get(sess, url(symbol, day, "ask")), day, symbol, "ask")
    if bid.empty or ask.empty:
        return pd.DataFrame()
    out = bid.drop(columns="volume").join(ask.drop(columns="volume"), how="inner")
    out["volume"] = bid["volume"]
    out.index = out.index.tz_localize("UTC")
    return out[["bid_o", "bid_h", "bid_l", "bid_c", "ask_o", "ask_h", "ask_l", "ask_c", "volume"]]


def download(symbols, start, end, root=store.ROOT, pause=0.6, save_every=15):
    sess = requests.Session()
    sess.headers["User-Agent"] = "fx-research/0.1"
    for sym in symbols:
        have = store.load(sym, "M1", root)
        done_days = set(have.index.normalize().unique()) if len(have) else set()
        buf, n = [], 0
        for day in pd.date_range(start, end, freq="D", tz="UTC"):
            if day.dayofweek == 5 or day in done_days:   # Saturday: no trading
                continue
            df = fetch_day(sess, sym, day)
            time.sleep(pause)
            if len(df):
                buf.append(df)
            n += 1
            if len(buf) >= save_every:
                store.merge_save(sym, "M1", pd.concat(buf), root)
                buf = []
                log.info("%s up to %s", sym, day.date())
        if buf:
            store.merge_save(sym, "M1", pd.concat(buf), root)
        log.info("%s done", sym)
