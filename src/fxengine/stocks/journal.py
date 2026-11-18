"""Your own trades journal (real Revolut trades or practice): log a buy/sell in the dashboard, the engine pairs them (first in, first out), shows the P&L and checks
whether each buy came from a setup the engine had flagged. Local CSV, never uploaded. Research only: it reads what you did, it never places anything."""
from __future__ import annotations
import csv
from datetime import date
from pathlib import Path

PATH = Path("data/stocks/journal.csv")
FIELDS = ["date", "symbol", "side", "price", "qty", "note"]


def add(row: dict, path: Path = PATH) -> dict:
    """Validate and append one trade. Raises ValueError with a plain-English reason."""
    try:
        d = date.fromisoformat(str(row.get("date", "")).strip())
    except ValueError:
        raise ValueError("Enter the date as YYYY-MM-DD.")
    sym = str(row.get("symbol", "")).strip().lower().replace(" ", "")
    if not sym or len(sym) > 12:
        raise ValueError("Enter the stock's ticker, e.g. AAPL or VOD.")
    side = str(row.get("side", "")).strip().lower()
    if side not in ("buy", "sell"):
        raise ValueError("Side must be buy or sell.")
    try:
        price, qty = float(row.get("price")), float(row.get("qty"))
    except (TypeError, ValueError):
        raise ValueError("Price and quantity must be numbers.")
    if price <= 0 or qty <= 0:
        raise ValueError("Price and quantity must be above zero.")
    out = dict(date=d.isoformat(), symbol=sym, side=side, price=price, qty=qty, note=str(row.get("note", ""))[:200])
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(out)
    return out


def load(path: Path = PATH) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for r in csv.DictReader(path.open()):
        try:
            rows.append(dict(date=r["date"], symbol=r["symbol"], side=r["side"], price=float(r["price"]), qty=float(r["qty"]), note=r.get("note", "")))
        except (KeyError, ValueError, TypeError):
            continue
    return sorted(rows, key=lambda r: r["date"])


def pair(rows: list[dict]) -> dict:
    """FIFO pairing per symbol -> closed trades with % and money P&L, plus still-open lots."""
    lots, closed = {}, []
    for r in rows:
        q = lots.setdefault(r["symbol"], [])
        if r["side"] == "buy":
            q.append([r["date"], r["price"], r["qty"]])
            continue
        left = r["qty"]
        while left > 1e-12 and q:
            d0, p0, q0 = q[0]
            take = min(left, q0)
            closed.append(dict(symbol=r["symbol"], bought=d0, sold=r["date"], buy=p0, sell=r["price"], qty=take, pct=r["price"] / p0 - 1, pnl=(r["price"] - p0) * take,
                               days=(date.fromisoformat(r["date"]) - date.fromisoformat(d0)).days))
            q[0][2] -= take
            left -= take
            if q[0][2] <= 1e-12:
                q.pop(0)
    open_ = [dict(symbol=s, bought=l[0], buy=l[1], qty=l[2]) for s, ls in lots.items() for l in ls]
    return dict(closed=closed, open=open_)


def from_setup(trade: dict, setups: list[dict], closed_setups: list[dict] | None = None, window: int = 4) -> str | None:
    """Name of the engine setup this buy matches (same stock, signal within `window` days before the buy), else None."""
    d = date.fromisoformat(trade["bought"])
    for r in list(setups) + list(closed_setups or []):
        if r["symbol"].split(".")[0] == trade["symbol"].split(".")[0].lower() and 0 <= (d - date.fromisoformat(r["signal_date"])).days <= window:
            return r["rule"]
    return None
