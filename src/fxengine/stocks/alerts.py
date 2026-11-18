"""Telegram alerts for the Stocks engine (research only: it tells you what the rules flag and what happened to your hypothetical paper trades; it never trades).
Same conventions as the FX engine: at most 3 lines per message, UNPROVEN labels, each event sent ONCE (state kept in data/stocks/alerts_sent.json), settings from .env only.
Credentials: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in ~/stocks/.env (gitignored). Without them nothing is sent and nothing fails.
Messages: new setups to consider at tomorrow's open, exit/invalidation/closed events for the paper account, an intraday warning if price breaks a level, a Friday summary."""
from __future__ import annotations
import json
import os
import urllib.request
from datetime import date
from pathlib import Path

SENT = Path("data/stocks/alerts_sent.json")
MAX_NEW = 5                                   # new-setup alerts per night (the strongest, one per stock); the rest are on the dashboard
MAX_PER_RUN = 12                              # hard cap on messages in one run
PREFIX = "📈 STOCKS"


def load_env(path: Path = Path(".env")) -> dict:
    out = {k: v for k, v in os.environ.items() if k.startswith("TELEGRAM_")}
    if path.exists():
        for ln in path.read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def send(env: dict, text: str, post=None) -> bool:
    tok, chat = env.get("TELEGRAM_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return False
    try:
        if post is not None:
            return bool(post(f"https://api.telegram.org/bot{tok}/sendMessage", {"chat_id": chat, "text": text}))
        req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=json.dumps({"chat_id": chat, "text": text}).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except Exception:
        return False


def _name(rule: str) -> str:
    from .strategies import INFO
    return INFO.get(rule, (rule,))[0]


def _t(sym: str) -> str:
    return sym.split(".")[0].upper()


def _lines(*ls: str) -> str:
    out = [x for x in ls if x][:3]
    return "\n".join(out)


def new_setup(r: dict, held: dict | None, rank_note: str = "") -> str:
    adr = f" · {r['home'].upper()} company via US listing" if r.get("home") and r["home"].lower() != str(r.get("market", "")).lower() else ""
    flt = " · filter ✓ (candidate)" if r.get("cand_ok") is True else ""
    why = (r.get("why") or [r["exit_text"]])[0]
    inv = f"invalid below {r['invalidation']:,.2f}" if r.get("invalidation") else "no fixed level"
    sz = f"Paper: ~{held['shares']:g} shares (£{held['cost']:,.0f}, £20 risk)" if held else "Paper account: taken at the open if cash allows"
    return _lines(f"🟢 NEW · {_t(r['symbol'])} ({r['market']}{adr}) · {_name(r['rule'])} · {'PASSED RESEARCH' if r.get('proven') else 'UNPROVEN'}{flt}",
                  f"{why} Last close {r['close']:,.2f}; {inv}.", f"{sz}. Check it is on Revolut first.")


def attention(r: dict) -> str:
    head = {"EXIT SIGNAL": "🟡 SELL at the next open", "INVALIDATED": "🔴 INVALIDATED: sell at the next open", "TIME STOP": "⏱ TIME LIMIT: sell at the next open"}.get(r["status"], r["status"])
    un = f"{r['unrealised'] * 100:+.1f}% since entry" if r.get("unrealised") is not None else ""
    return _lines(f"{head} · {_t(r['symbol'])} · {_name(r['rule'])}", f"{r.get('detail', '')} {un}".strip(), "Hypothetical paper trade; the rule decides, you trade yourself.")


def closed_trade(c: dict) -> str:
    sign = "✅" if c["pnl"] > 0 else "❌"
    return _lines(f"{sign} CLOSED · {_t(c['symbol'])} · {c['pnl']:+.0f} GBP ({c['r']:+.1f}R) · {c['pct'] * 100:+.1f}%", f"{_name(c['rule'])}; in {c['entry_date']}, out {c['exit_date']}.", "Hypothetical, before costs.")


def intraday_warning(sym: str, price: float, level: float, kind: str) -> str:
    return _lines(f"⚠️ {_t(sym)} is trading below its invalid-below level ({kind})", f"Now {price:,.2f}, level {level:,.2f}. The rules decide at the CLOSE, so nothing has changed yet.", "Early warning only.")


def weekly(sp: dict) -> str:
    a = (sp.get("account") or {}).get("tiles") or {}
    fw = sp.get("forward") or {}
    n = sum(v["n"] for v in fw.values())
    return _lines(f"{PREFIX} · week: paper balance £{a.get('balance', 2500):,.0f} ({a.get('week', 0):+.0f} this week, {a.get('alltime', 0):+.0f} all time)",
                  f"{a.get('n_open', 0)} open · {a.get('wins', 0)} won / {a.get('losses', 0)} lost · forward test: {n} closed trades tracked.", "Research only; nothing here is advice.")


def build(sp: dict, asof: str, today: date | None = None, rank: dict | None = None) -> list[tuple[str, str]]:
    """The messages (key, text) this scan would send, before de-duplication."""
    out: list[tuple[str, str]] = []
    ac = sp.get("account") or {}
    held = {p["id"]: p for p in ac.get("positions", [])}
    rank = rank or {}
    for r in sp.get("setups", []):
        if r["status"] in ("EXIT SIGNAL", "INVALIDATED", "TIME STOP") and r["id"] in held:
            out.append((f"attn|{r['id']}|{r['status']}", attention(r)))
    for c in ac.get("closed", []):
        if c["exit_date"] == asof:
            out.append((f"closed|{c['id']}|{c['exit_date']}", closed_trade(c)))
    cand = [r for r in sp.get("setups", []) if r["status"] == "PENDING" and r.get("proven")]
    cand.sort(key=lambda r: (-rank.get(r["rule"], 0.0), -r.get("strength", 0.0)))
    seen, news = set(), []
    for r in cand:
        if r["symbol"] in seen:
            continue
        seen.add(r["symbol"])
        news.append(r)
    for r in news[:MAX_NEW]:
        out.append((f"new|{r['id']}", new_setup(r, held.get(r["id"]))))
    extra = len(news) - MAX_NEW
    t = today or date.fromisoformat(asof)
    brief = _lines(f"{PREFIX} · {asof}: {len(news)} stock(s) flagged by rules that passed research" + (f" (top {MAX_NEW} sent, {extra} more on the dashboard)" if extra > 0 else ""),
                   f"{len(held)} paper position(s) open, balance £{(ac.get('tiles') or {}).get('balance', 2500):,.0f}.", "Open the Stocks tab for everything. Research only.")
    out.append((f"brief|{asof}", brief))
    if t.weekday() == 4:
        out.append((f"weekly|{t.isocalendar()[0]}-{t.isocalendar()[1]}", weekly(sp)))
    return out


def run(sp_path: Path = Path("docs/results/stocks_setups.json"), res_path: Path = Path("docs/results/stocks.json"), env: dict | None = None, post=None, sent_path: Path = SENT, today: date | None = None) -> dict:
    env = load_env() if env is None else env
    if not (env.get("TELEGRAM_TOKEN") and env.get("TELEGRAM_CHAT_ID")):
        return dict(configured=False, sent=0)
    sp = json.loads(Path(sp_path).read_text())
    rank = {r["rule"]: r["roi"] for r in json.loads(Path(res_path).read_text())["rules"] if "roi" in r} if Path(res_path).exists() else {}
    done = set(json.loads(sent_path.read_text())) if sent_path.exists() else set()
    sent = failed = 0
    for key, text in build(sp, sp["asof"], today, rank):
        if key in done or sent >= MAX_PER_RUN:
            continue
        assert text.count("\n") <= 2, "a Telegram message may have at most 3 lines"
        if send(env, text, post):
            done.add(key)
            sent += 1
        else:
            failed += 1
    sent_path.parent.mkdir(parents=True, exist_ok=True)
    sent_path.write_text(json.dumps(sorted(done)[-3000:]))
    return dict(configured=True, sent=sent, failed=failed)


def test_message(env: dict | None = None) -> bool:
    return send(load_env() if env is None else env, _lines(f"{PREFIX} · test message", "Alerts are connected. You will get new setups, sell signals and a Friday summary.", "Research only: nothing here is advice."))


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        print("test message sent" if test_message() else "NOT sent: check TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in ~/stocks/.env")
    else:
        print(run())
