"""Free daily OHLCV from Stooq (no key). The build sandbox cannot reach it: run on the VM:  python -m fxengine.stocks.data  -> data/stocks/prices.parquet
Every raw file is cached, a rerun only fetches what is missing or older than --refresh hours, a missing symbol never stops the run, and a quality report is written."""
from __future__ import annotations
import io, json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from .universe import SYMBOLS

URL = "https://stooq.com/q/d/l/?s={s}&i=d"
BAD_MOVE = 0.45                    # |daily close-to-close move| above this is treated as a probable data error (unadjusted split etc.)


def parse(text: str) -> pd.DataFrame:
    """Stooq CSV -> DataFrame indexed by date with open/high/low/close/volume; empty if there is no usable data."""
    t = (text or "").strip()
    if not t.lower().startswith("date"):
        return pd.DataFrame()
    d = pd.read_csv(io.StringIO(t))
    d.columns = [c.strip().lower() for c in d.columns]
    if not {"date", "open", "high", "low", "close"} <= set(d.columns):
        return pd.DataFrame()
    if "volume" not in d:
        d["volume"] = np.nan
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    for c in ("open", "high", "low", "close", "volume"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["date", "open", "high", "low", "close"])
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)].drop_duplicates("date").sort_values("date")
    return d.set_index("date")[["open", "high", "low", "close", "volume"]]


def quality(sym: str, d: pd.DataFrame) -> dict:
    ret = d["close"].pct_change().abs()
    gaps = d.index.to_series().diff().dt.days
    return dict(symbol=sym, rows=int(len(d)), first=str(d.index.min().date()), last=str(d.index.max().date()), bad_bars=int((ret > BAD_MOVE).sum()),
                zero_volume=round(float((d["volume"].fillna(0) == 0).mean()), 3), max_gap_days=int(gaps.max()) if len(gaps) > 1 else 0)


def download(out=Path("data/stocks"), symbols=SYMBOLS, get=None, pause=0.6, refresh_hours=20, min_rows=250) -> pd.DataFrame:
    import requests
    get = get or (lambda u: requests.get(u, timeout=30, headers={"User-Agent": "research-script"}))
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    frames, report, gaps, quota = [], [], [], False
    for k, sym in enumerate(symbols, 1):
        f, miss = raw / f"{sym}.csv", raw / f"{sym}.missing"
        try:
            fresh = f.exists() and (time.time() - f.stat().st_mtime) < refresh_hours * 3600
            if not fresh and not quota and not (miss.exists() and (time.time() - miss.stat().st_mtime) < 7 * 86400):
                r = get(URL.format(s=sym))
                time.sleep(pause)
                body = r.content.decode("latin-1") if r.status_code == 200 else ""
                if "exceeded the daily hits limit" in body.lower():
                    quota = True
                    print("Stooq daily hit limit reached: rerun tomorrow; everything fetched so far is cached.", flush=True)
                elif r.status_code == 200 and parse(body).shape[0] >= min_rows:
                    f.write_text(body)
                    if miss.exists():
                        miss.unlink()
                else:
                    miss.write_text(f"HTTP {r.status_code}, no usable data")
            if not f.exists():
                gaps.append(f"{sym}: no data"); print(f"[{k}/{len(symbols)}] {sym} no data", flush=True); continue
            d = parse(f.read_text())
            if len(d) < min_rows:
                gaps.append(f"{sym}: only {len(d)} rows"); continue
            d = d.assign(symbol=sym)
            frames.append(d.reset_index())
            report.append(quality(sym, d))
            print(f"[{k}/{len(symbols)}] {sym} {len(d)} rows to {report[-1]['last']}", flush=True)
        except Exception as e:                                   # one bad symbol never stops the run
            gaps.append(f"{sym}: {type(e).__name__}"); print(f"[{k}/{len(symbols)}] {sym} FAILED {type(e).__name__}", flush=True)
    if not frames:
        sys.exit("no stock data downloaded: " + "; ".join(gaps[:5]))
    df = pd.concat(frames, ignore_index=True)
    df.to_parquet(out / "prices.parquet")
    (out / "quality.json").write_text(json.dumps(dict(symbols=report, gaps=gaps), indent=1))
    bad = [r for r in report if r["bad_bars"] > 0]
    print(f"symbols {len(report)}/{len(symbols)} · rows {len(df)} · {df['date'].min():%Y-%m-%d} -> {df['date'].max():%Y-%m-%d} · gaps {len(gaps)} · symbols with suspicious bars {len(bad)}", flush=True)
    return df


if __name__ == "__main__":
    download()
