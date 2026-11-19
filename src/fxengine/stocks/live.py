"""Live 5-minute job for the paper account (weekdays). Stdlib only, so it costs almost nothing on the small VM. It NEVER trades: it plans the hypothetical paper account.
Each run, for the stocks that matter right now (paper positions + new proven setups):
  1. fetches today's 5-minute prices,
  2. when a market has opened: ENTERS the proven setups from last night at today's real open (same sizing as the nightly account),
     and EXITS positions the rules told to sell, at today's real open,
  3. marks every open position at the live price, works out the live balance,
  4. sends one Telegram message per event (once only) and an early warning if a position breaks its invalid-below level.
Writes docs/results/stocks_live.json. The nightly scan stays the official record and overwrites this plan with the final numbers."""
from __future__ import annotations
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from . import alerts, rates as R
from .sizing import stop_for, shares as size_shares
from . import universe as U
from .universe import yahoo_symbol

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=1d&interval=5m"
MAX_SYMBOLS = 40
SELL = ("EXIT SIGNAL", "INVALIDATED", "TIME STOP")


def parse_quote(text: str) -> dict | None:
    """Yahoo 5-minute chart JSON -> {price, t, prev_close, currency, open, open_date}, or None. `open` = first bar's open of the session shown, `open_date` its LOCAL exchange date."""
    try:
        r = json.loads(text)["chart"]["result"][0]
        m = r["meta"]
        q = r.get("indicators", {}).get("quote", [{}])[0]
        ts, opens, closes = r.get("timestamp") or [], q.get("open") or [], q.get("close") or []
        px = m.get("regularMarketPrice")
        if px is None:
            cs = [c for c in closes if c is not None]
            px = cs[-1] if cs else None
        if px is None:
            return None
        off = int(m.get("gmtoffset") or 0)
        op = od = None
        for t, o in zip(ts, opens):
            if o is not None:
                op, od = float(o), datetime.fromtimestamp(t + off, timezone.utc).strftime("%Y-%m-%d")
                break
        return dict(price=float(px), t=int(m.get("regularMarketTime") or 0), prev_close=m.get("chartPreviousClose"), currency=m.get("currency"), open=op, open_date=od)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _allowed(sym: str) -> bool:
    sym = sym.lower()
    ca, ch = U.allowed_countries(), U.allowed_home()
    return (ca is None or U.country_code(sym) in ca) and (ch is None or U.home_country(sym) in ch)


def watch_list(sp: dict) -> list[dict]:
    """Held paper positions first, then today's new (proven) setups, only in markets/countries you can trade."""
    by_id = {r["id"]: r for r in sp.get("setups", [])}
    held = [by_id[p["id"]] for p in (sp.get("account") or {}).get("positions", []) if p["id"] in by_id]
    new = [r for r in sp.get("setups", []) if r["status"] == "PENDING" and r.get("proven") and _allowed(r["symbol"])]
    seen, out = set(), []
    for r in held + new:
        if r["symbol"] not in seen:
            seen.add(r["symbol"])
            out.append(r)
    return out[:MAX_SYMBOLS]


def plan_live(sp: dict, quotes: dict, rates: dict, rank: dict | None = None, today: str | None = None) -> dict:
    """Pure function: nightly state + live quotes -> the live plan. No I/O. With `today` (UTC date), a market's open only counts if its session IS today: a market that has not opened yet shows yesterday's session and must not trade."""
    acct = sp.get("account") or {}
    by_id = {r["id"]: r for r in sp.get("setups", [])}
    positions = acct.get("positions", [])
    balance = float(acct.get("balance", 2500.0))
    cash = balance - sum(p["value"] for p in positions)
    exits, entries, held_out, skipped = [], [], [], []
    live_pos, sym_held = [], set()
    for p in positions:
        row, q = by_id.get(p["id"], {}), quotes.get(p["symbol"])
        sym_held.add(p["symbol"])
        if not q:
            live_pos.append(dict(p, live=False))
            continue
        day = q["open_date"] or ""
        if today and day != today:
            q = dict(q, open=None)                                       # that market's session is not today's yet: no exit at an old open
        if row.get("status") in SELL and q["open"] is not None and day > p["entry_date"]:
            val = p["shares"] * R.gbp(rates, p["symbol"], q["open"], day)
            cash += val
            exits.append(dict(id=p["id"], symbol=p["symbol"], rule=p["rule"], status=row["status"], price=q["open"], date=day, value=round(val, 2), pnl=round(val - p["cost"], 2),
                              r=round((val - p["cost"]) / 20.0, 2), pct=round(val / p["cost"] - 1, 4), entry_date=p["entry_date"], exit_date=day))
            continue
        val = p["shares"] * R.gbp(rates, p["symbol"], q["price"], day or "9999")
        live_pos.append(dict(p, live=True, price=q["price"], value=round(val, 2), floating=round(val - p["cost"], 2), t=q["t"]))
    cands = [r for r in sp.get("setups", []) if r["status"] == "PENDING" and r.get("proven") and r["symbol"] in quotes and r["id"] not in {p["id"] for p in positions} and _allowed(r["symbol"])]
    rank = rank or {}
    cands.sort(key=lambda r: (-rank.get(r["rule"], 0.0), -r.get("strength", 0.0)))
    equity = balance
    for r in cands:
        q = quotes[r["symbol"]]
        day = q["open_date"]
        if q["open"] is None or not day or r["signal_date"] >= day or (today and day != today):
            continue                                                     # market not open yet, or the signal is from today's own session
        if r["symbol"] in sym_held or any(e["symbol"] == r["symbol"] for e in entries):
            skipped.append(dict(id=r["id"], symbol=r["symbol"], why="already held through another setup"))
            continue
        stop, nostop = stop_for(r.get("invalidation"), q["open"])
        ep = R.gbp(rates, r["symbol"], q["open"], day)
        sh, why = size_shares(ep, R.gbp(rates, r["symbol"], stop, day), equity, cash)
        if why:
            skipped.append(dict(id=r["id"], symbol=r["symbol"], why=why))
            continue
        cost = sh * ep
        cash -= cost
        val = sh * R.gbp(rates, r["symbol"], q["price"], day)
        entries.append(dict(id=r["id"], symbol=r["symbol"], rule=r["rule"], date=day, price=q["open"], shares=round(sh, 4), cost=round(cost, 2), value=round(val, 2), floating=round(val - cost, 2),
                            stop=round(stop, 4), nostop=nostop))
    mv = sum(p.get("value", 0) for p in live_pos) + sum(e["value"] for e in entries)
    live_balance = round(cash + mv, 2)
    floating = round(sum(p.get("floating", 0) for p in live_pos) + sum(e["floating"] for e in entries), 2)
    return dict(entries=entries, exits=exits, positions=live_pos, skipped=skipped, cash=round(cash, 2), balance=live_balance, nightly_balance=round(balance, 2), floating=floating,
                date=max([q["open_date"] for q in quotes.values() if q.get("open_date")] or [""]))


def messages(plan: dict) -> list[tuple[str, str]]:
    out = []
    for e in plan["entries"]:
        out.append((f"live-in|{e['id']}", alerts.entered(e)))
    for x in plan["exits"]:
        out.append((f"live-out|{x['id']}|{x['date']}", alerts.sold(x)))
    return out


def _http(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research-script)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, r.read()


def run(sp_path: Path = Path("docs/results/stocks_setups.json"), out: Path = Path("docs/results/stocks_live.json"), get=None, env: dict | None = None, post=None,
        sent_path: Path = alerts.SENT, now: datetime | None = None, pause: float = 0.3, raw: Path = Path("data/stocks/raw"), res_path: Path = Path("docs/results/stocks.json")) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5 or not Path(sp_path).exists():
        return dict(skipped=True)
    get = get or _http
    sp = json.loads(Path(sp_path).read_text())
    quotes, failed = {}, []
    wl = watch_list(sp)
    for r in wl:
        try:
            st, b = get(URL.format(t=yahoo_symbol(r["symbol"])))
            q = parse_quote(b.decode("utf-8", "replace") if isinstance(b, bytes) else b) if st == 200 else None
            if q:
                quotes[r["symbol"]] = q
            else:
                failed.append(r["symbol"])
            time.sleep(pause)
        except Exception:
            failed.append(r["symbol"])
    rank = {}
    if Path(res_path).exists():
        rank = {x["rule"]: x["roi"] for x in json.loads(Path(res_path).read_text()).get("rules", []) if "roi" in x}
    plan = plan_live(sp, quotes, R.load(raw), rank, today=now.strftime("%Y-%m-%d"))
    plan["day_ok"] = plan["date"] == now.strftime("%Y-%m-%d")           # only trust the plan if it is about today's session
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(asof=now.strftime("%Y-%m-%d %H:%M"), prices=quotes, failed=failed, plan=plan)))
    env = alerts.load_env() if env is None else env
    done = set(json.loads(sent_path.read_text())) if sent_path.exists() else set()
    sent = 0
    if plan["day_ok"]:
        for key, text in messages(plan):
            if key not in done and alerts.send(env, text, post):
                done.add(key)
                sent += 1
        held = {p["id"] for p in plan["positions"]}
        for r in wl:
            q, lvl = quotes.get(r["symbol"]), r.get("invalidation")
            if not q or not lvl or q["price"] >= lvl or r["id"] not in held:
                continue
            key = f"warn|{r['symbol']}|{now:%Y-%m-%d}"
            if key not in done and alerts.send(env, alerts.intraday_warning(r["symbol"], q["price"], lvl, "paper position"), post):
                done.add(key)
                sent += 1
    if sent:
        sent_path.parent.mkdir(parents=True, exist_ok=True)
        sent_path.write_text(json.dumps(sorted(done)[-3000:]))
    return dict(symbols=len(wl), prices=len(quotes), failed=len(failed), entries=len(plan["entries"]), exits=len(plan["exits"]), sent=sent, balance=plan["balance"])


if __name__ == "__main__":
    print(run())
