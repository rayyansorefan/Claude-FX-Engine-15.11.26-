"""Light intraday price check for the stocks that matter right now (your paper positions and today's new setups): every 5 minutes on weekdays.
Stdlib only (no pandas) so it costs almost nothing on the small VM. It writes docs/results/stocks_live.json (latest prices, shown on the setup cards) and sends ONE early warning
per stock per day if price trades below its invalid-below level. The rules themselves still decide at the CLOSE: this never changes a status, a trade or a result."""
from __future__ import annotations
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from . import alerts
from .universe import yahoo_symbol

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=1d&interval=5m"
MAX_SYMBOLS = 40


def parse_quote(text: str) -> dict | None:
    """Yahoo chart JSON -> {price, t (UTC epoch), prev_close, currency}, or None."""
    try:
        r = json.loads(text)["chart"]["result"][0]
        m = r["meta"]
        px = m.get("regularMarketPrice")
        if px is None:
            closes = [c for c in r["indicators"]["quote"][0].get("close", []) if c is not None]
            px = closes[-1] if closes else None
        if px is None:
            return None
        return dict(price=float(px), t=int(m.get("regularMarketTime") or 0), prev_close=m.get("chartPreviousClose"), currency=m.get("currency"))
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def watch_list(sp: dict) -> list[dict]:
    """Held paper positions first, then today's new (proven) setups: the symbols whose price you care about right now."""
    held = {p["id"] for p in (sp.get("account") or {}).get("positions", [])}
    rows = [r for r in sp.get("setups", []) if r["id"] in held] + [r for r in sp.get("setups", []) if r["status"] == "PENDING" and r.get("proven") and r["id"] not in held]
    seen, out = set(), []
    for r in rows:
        if r["symbol"] not in seen:
            seen.add(r["symbol"])
            out.append(r)
    return out[:MAX_SYMBOLS]


def _http(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research-script)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, r.read()


def run(sp_path: Path = Path("docs/results/stocks_setups.json"), out: Path = Path("docs/results/stocks_live.json"), get=None, env: dict | None = None, post=None,
        sent_path: Path = alerts.SENT, now: datetime | None = None, pause: float = 0.3) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5 or not Path(sp_path).exists():
        return dict(skipped=True)
    get = get or _http
    sp = json.loads(Path(sp_path).read_text())
    prices, failed = {}, []
    wl = watch_list(sp)
    for r in wl:
        try:
            st, b = get(URL.format(t=yahoo_symbol(r["symbol"])))
            q = parse_quote(b.decode("utf-8", "replace") if isinstance(b, bytes) else b) if st == 200 else None
            if q:
                prices[r["symbol"]] = q
            else:
                failed.append(r["symbol"])
            time.sleep(pause)
        except Exception:
            failed.append(r["symbol"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(asof=now.strftime("%Y-%m-%d %H:%M"), prices=prices, failed=failed)))
    env = alerts.load_env() if env is None else env
    done = set(json.loads(sent_path.read_text())) if sent_path.exists() else set()
    warned = 0
    held = {p["id"] for p in (sp.get("account") or {}).get("positions", [])}
    for r in wl:
        q, lvl = prices.get(r["symbol"]), r.get("invalidation")
        if not q or not lvl or q["price"] >= lvl:
            continue
        key = f"warn|{r['symbol']}|{now:%Y-%m-%d}"
        if key in done:
            continue
        if alerts.send(env, alerts.intraday_warning(r["symbol"], q["price"], lvl, "paper position" if r["id"] in held else "new setup"), post):
            done.add(key)
            warned += 1
    if warned:
        sent_path.parent.mkdir(parents=True, exist_ok=True)
        sent_path.write_text(json.dumps(sorted(done)[-3000:]))
    return dict(symbols=len(wl), prices=len(prices), failed=len(failed), warned=warned)


if __name__ == "__main__":
    print(run())
