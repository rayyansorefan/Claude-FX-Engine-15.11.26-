"""OANDA fxTrade PRACTICE read-only candle fetcher (bid+ask). Only GET /v3/instruments/*/candles.
No account, order or trade endpoints are called anywhere. Only COMPLETE candles are kept.
Run from the user's machine. Token in .env as OANDA_TOKEN (never committed)."""
from __future__ import annotations
import time, logging
import pandas as pd
import requests
from . import store

log = logging.getLogger("oanda")
HOST = "https://api-fxpractice.oanda.com"
COLS = ["bid_o", "bid_h", "bid_l", "bid_c", "ask_o", "ask_h", "ask_l", "ask_c", "volume"]


def instrument(symbol: str) -> str:
    return f"{symbol[:3]}_{symbol[3:]}"


def parse_candles(payload: dict) -> pd.DataFrame:
    rows = []
    for c in payload.get("candles", []):
        if not c.get("complete"):
            continue                                  # never use a forming candle
        b, a = c["bid"], c["ask"]
        rows.append((pd.Timestamp(c["time"]).tz_convert("UTC").floor("s"),
                     float(b["o"]), float(b["h"]), float(b["l"]), float(b["c"]),
                     float(a["o"]), float(a["h"]), float(a["l"]), float(a["c"]), float(c["volume"])))
    if not rows:
        return pd.DataFrame(columns=COLS, index=pd.DatetimeIndex([], tz="UTC"))
    df = pd.DataFrame(rows, columns=["t"] + COLS).set_index("t").sort_index()
    return df[~df.index.duplicated(keep="last")]


def get_page(sess, token, symbol, gran, start, count=5000, retries=5):
    params = {"granularity": gran, "price": "BA", "from": start.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"), "count": count}
    wait = 2
    for _ in range(retries):
        r = sess.get(f"{HOST}/v3/instruments/{instrument(symbol)}/candles", params=params,
                     headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            log.warning("HTTP %s, retry in %ss", r.status_code, wait)
            time.sleep(wait)
            wait *= 2
            continue
        raise RuntimeError(f"OANDA HTTP {r.status_code}: {r.text[:200]}")   # 401 => bad token
    raise RuntimeError("OANDA: gave up after retries")


def download(token, symbols, gran, start, root=store.ROOT, pause=0.2):
    sess = requests.Session()
    now = pd.Timestamp.now(tz="UTC")
    for sym in symbols:
        have = store.load(sym, gran, root)
        want = pd.Timestamp(start, tz="UTC")
        # resume after the last stored candle, but BACKFILL from `start` if history begins later
        if len(have) and have.index.min() <= want + pd.Timedelta(days=7):
            t = have.index.max() + pd.Timedelta(seconds=1)
        else:
            t = want
        total = 0
        while t < now:
            df = parse_candles(get_page(sess, token, sym, gran, t))
            if df.empty:
                break
            store.merge_save(sym, gran, df, root)
            total += len(df)
            if df.index[-1] <= t:
                break
            t = df.index[-1] + pd.Timedelta(seconds=1)
            time.sleep(pause)
        log.info("%s %s +%d rows", sym, gran, total)
