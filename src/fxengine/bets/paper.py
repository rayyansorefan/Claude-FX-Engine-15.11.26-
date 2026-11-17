"""PAPER betting ledger. Every bet here is hypothetical: a row in a local SQLite file with a virtual bankroll. Nothing is ever sent to Bet365 or any
bookmaker, no login, no credentials. Upcoming matches + Bet365/Pinnacle prices come from football-data.co.uk's free fixtures.csv; results from its season CSVs.
Stdlib + numpy only (the VM has ~200 MB spare).  tick() = fetch fixtures, auto-place qualifying paper bets, settle finished ones."""
from __future__ import annotations
import csv, io, json, sqlite3, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from . import odds as O

DB = Path("data/bets/paper.db")
TIPS_URL = "https://raw.githubusercontent.com/rayyansorefan/Claude-FX-Engine-15.11.26-/betting-wip/docs/tips.jsonl"   # public repo: the tipster's picks
STRATS = ("V1", "V1P", "TIPSTER", "MANUAL")              # each gets its OWN virtual bankroll, so the comparison is fair
STRAT_NOTE = {"V1": "Option 2: the value checker as an automatic rule (Shin margin removal)", "V1P": "Option 2 with plain margin removal",
              "TIPSTER": "Option 1: Claude's researched picks", "MANUAL": "Your own clicks"}
START = 100.0                # virtual bankroll in £
AUTO_STAKE = 2.0             # flat paper stake per automatic bet (2% of the starting £100)
MIN_STAKE = 0.5
HORIZON_DAYS = 7             # only auto-bet matches kicking off within a week
EDGE = 0.03                  # V1: Bet365 price at least 3% better than the sharp (Pinnacle, margin-removed) fair price
FIXTURES_URL = "https://football-data.co.uk/fixtures.csv"
RESULT_URL = "https://football-data.co.uk/mmz4281/{s}/{d}.csv"
SCHEMA = """
CREATE TABLE IF NOT EXISTS bets(id INTEGER PRIMARY KEY, placed_at TEXT, source TEXT, rule TEXT, div TEXT, date TEXT, home TEXT, away TEXT, market TEXT, sel TEXT,
  odds REAL, stake REAL, status TEXT DEFAULT 'open', pnl REAL, settled_at TEXT, p REAL, note TEXT, UNIQUE(div, date, home, away, market, sel, rule));
CREATE TABLE IF NOT EXISTS fixtures(id TEXT PRIMARY KEY, date TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS tips(id TEXT PRIMARY KEY, json TEXT, status TEXT, detail TEXT, updated TEXT);
"""


def connect(path=DB) -> sqlite3.Connection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(path), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    have = {r[1] for r in c.execute("PRAGMA table_info(bets)")}
    for col, typ in (("p", "REAL"), ("note", "TEXT")):              # older ledgers: add the new columns in place, keep every bet
        if col not in have:
            c.execute(f"ALTER TABLE bets ADD COLUMN {col} {typ}")
    c.commit()
    return c


def _f(x):
    try:
        v = float(str(x).strip())
        return v if v == v and v > 1.0 else None            # odds must be > 1; blanks, '-', NaN -> None
    except (TypeError, ValueError):
        return None


def _date(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            pass
    return None


def season_of(d: date) -> str:
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def parse_fixtures(text: str) -> list[dict]:
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        d = _date(r.get("Date"))
        if not d or not r.get("HomeTeam") or not r.get("AwayTeam"):
            continue
        dv, h, a = (r.get("Div") or "").strip(), r["HomeTeam"].strip(), r["AwayTeam"].strip()
        out.append(dict(id=f"{dv}|{d.isoformat()}|{h}|{a}", div=dv, date=d.isoformat(), time=(r.get("Time") or "").strip(), home=h, away=a,
                        b365=[_f(r.get("B365H")), _f(r.get("B365D")), _f(r.get("B365A"))],
                        ps=[_f(r.get("PSH") or r.get("PPH")), _f(r.get("PSD") or r.get("PPD")), _f(r.get("PSA") or r.get("PPA"))],   # Pinnacle: PS* or the newer PP* names
                        ou=[_f(r.get("B365>2.5")), _f(r.get("B365<2.5"))], psou=[_f(r.get("P>2.5")), _f(r.get("P<2.5"))]))
    return out


def price(fix: dict, market: str, sel: str):
    if market == "1X2" and sel in "HDA" and len(sel) == 1:
        return fix["b365"]["HDA".index(sel)]
    if market == "OU" and sel in ("O25", "U25"):
        return fix["ou"][0 if sel == "O25" else 1]
    return None


def qualifies(fix: dict) -> list[tuple]:
    """Automatic paper bets: V1 (Shin margin removal, as in the research) and V1P (plain proportional removal, to test the Shin worry).
    Returns [(rule, market, sel, odds)]."""
    res = []
    for rule, fn in (("V1", O.fair_probs_shin), ("V1P", O.fair_probs)):
        if all(fix["b365"]) and all(fix["ps"]):
            fair = fn(*fix["ps"])
            for i, sel in enumerate("HDA"):
                if fair is not None and fix["b365"][i] * fair[i] - 1.0 >= EDGE:
                    res.append((rule, "1X2", sel, fix["b365"][i]))
        if all(fix["ou"]) and all(fix["psou"]):
            fair = fn(*fix["psou"])
            for i, sel in enumerate(("O25", "U25")):
                if fair is not None and fix["ou"][i] * fair[i] - 1.0 >= EDGE:
                    res.append((rule, "OU", sel, fix["ou"][i]))
    return res


def available(c, rule: str | None = None) -> float:
    """Virtual cash free to stake = start + settled profit - stakes tied up in open bets. With `rule`, that strategy's own £100."""
    w, a = ("AND rule=?", (rule,)) if rule else ("", ())
    pnl = c.execute(f"SELECT COALESCE(SUM(pnl),0) FROM bets WHERE status!='open' {w}", a).fetchone()[0]
    open_ = c.execute(f"SELECT COALESCE(SUM(stake),0) FROM bets WHERE status='open' {w}", a).fetchone()[0]
    return round(START + pnl - open_, 2)


def place(c, fix: dict, market: str, sel: str, stake: float, rule="MANUAL", source="manual", today: date | None = None, p: float | None = None, note: str | None = None) -> int:
    """Record a PAPER bet. Raises ValueError with a plain-English reason if it cannot be recorded."""
    today = today or date.today()
    o = price(fix, market, sel)
    if o is None:
        raise ValueError("No Bet365 price for that pick.")
    if not isinstance(stake, (int, float)) or stake != stake or stake < MIN_STAKE:
        raise ValueError(f"Minimum paper stake is £{MIN_STAKE:.2f}.")
    if date.fromisoformat(fix["date"]) < today:
        raise ValueError("That match has already been played.")
    if stake > available(c, rule) + 1e-9:
        raise ValueError(f"Not enough virtual cash (£{available(c, rule):.2f} free).")
    try:
        cur = c.execute("INSERT INTO bets(placed_at,source,rule,div,date,home,away,market,sel,odds,stake,p,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (datetime.now(timezone.utc).isoformat(timespec="seconds"), source, rule, fix["div"], fix["date"], fix["home"], fix["away"], market, sel, o, round(float(stake), 2), p, note))
    except sqlite3.IntegrityError:
        raise ValueError("You already have that exact paper bet.")
    c.commit()
    return cur.lastrowid


def check_bet(fix: dict, sel: str, price_: float | None = None) -> dict:
    """OPTION 2, the value checker: is this Bet365 price better than the sharp (Pinnacle, margin-removed) fair price? Read-only: records nothing."""
    if sel not in ("H", "D", "A"):
        return dict(ok=False, error="The checker prices Home / Draw / Away only (no sharp price exists for other bets in the free data).")
    i = "HDA".index(sel)
    ps = fix.get("ps") or []
    if not (len(ps) == 3 and all(ps)):
        return dict(ok=False, error="No Pinnacle price for this match in the free data yet, so there is nothing sharp to compare with.")
    b = price_ if price_ else (fix["b365"][i] if fix.get("b365") else None)
    if not b or b <= 1.0:
        return dict(ok=False, error="Enter Bet365's price (a decimal number above 1, e.g. 2.40).")
    fs, fp = O.fair_probs_shin(*ps)[i], O.fair_probs(*ps)[i]
    es, ep = b * fs - 1.0, b * fp - 1.0
    best, worst = max(es, ep), min(es, ep)
    if worst >= EDGE:
        verdict, tone = "GOOD VALUE: beats the sharp fair price by 3% or more on both methods", "good"
    elif best >= 0:
        verdict, tone = "BORDERLINE: roughly a fair price, no clear edge", "warn"
    else:
        verdict, tone = f"POOR VALUE: you are paying about {abs(ep) * 100:.1f}% over the sharp fair price", "crit"
    mg = O.overround(*fix["b365"]) if fix.get("b365") and all(fix["b365"]) else None
    return dict(ok=True, verdict=verdict, tone=tone, price=round(b, 3), fair_odds=round(1 / fp, 3), fair_odds_shin=round(1 / fs, 3), edge=round(ep, 4), edge_shin=round(es, 4),
                per10=round(10 * ep, 2), bet365_margin=(round(mg, 4) if mg is not None else None),
                note="Assumes Pinnacle's price is the truth. It is a strong guide, not a guarantee. Check the live Bet365 price yourself; this never places a bet.")


def _norm(t: str) -> str:
    import re
    t = re.sub(r"[^a-z0-9 ]", "", str(t).lower())
    return " ".join(w for w in t.split() if w not in ("fc", "afc", "cf", "sc", "the"))


def same_team(a: str, b: str) -> bool:
    import difflib
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a)) or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def ingest_tips(c, tips: list[dict], today: date | None = None) -> dict:
    """OPTION 1, the tipster: each tip is placed as a PAPER bet at the CURRENT Bet365 price once its match is in the fixtures file and the price is
    at least the tip's minimum. Tips whose match never shows up, or whose price never reaches the minimum, expire (and are shown as such)."""
    today = today or date.today()
    out = dict(placed=0, waiting=0, expired=0)
    for t in tips:
        try:
            tid, d = str(t["id"]), date.fromisoformat(t["date"])
            market, sel, home, away = t.get("market", "1X2"), t["sel"], t["home"], t["away"]
            floor, stake = float(t.get("min_odds", 1.01)), float(t.get("stake", AUTO_STAKE))
        except (KeyError, TypeError, ValueError):
            continue
        row = c.execute("SELECT status FROM tips WHERE id=?", (tid,)).fetchone()
        if row and row["status"] in ("placed", "expired"):
            continue
        status, detail = "waiting", "waiting for the match to appear in the free fixtures file"
        for r in c.execute("SELECT json FROM fixtures WHERE date=?", (d.isoformat(),)).fetchall():
            f = json.loads(r["json"])
            if same_team(f["home"], home) and same_team(f["away"], away):
                o = price(f, market, sel)
                if o is None:
                    detail = "match found but no Bet365 price for that pick"
                elif o < floor:
                    detail = f"match found; Bet365 price {o:.2f} is below your minimum {floor:.2f}"
                else:
                    try:
                        place(c, f, market, sel, stake, rule="TIPSTER", source="tip", today=today, p=t.get("p"), note=str(t.get("why", ""))[:400])
                        status, detail = "placed", f"paper bet placed at {o:.2f}"
                    except ValueError as e:
                        status, detail = ("placed", "already placed") if "already" in str(e) else ("waiting", str(e))
                break
        if status != "placed" and d < today:
            status, detail = "expired", detail if "below" in detail else "the match was never found in the free fixtures file, or the price never reached the minimum"
        c.execute("INSERT OR REPLACE INTO tips VALUES(?,?,?,?,?)", (tid, json.dumps(t), status, detail, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        out["placed" if status == "placed" else "expired" if status == "expired" else "waiting"] += 1
    c.commit()
    return out


def strategy_stats(settled: list[dict], open_: list[dict], rule: str) -> dict:
    """Scoreboard row for one strategy: its own £100 bankroll, results, and a plain 95% range for its return per £1."""
    mine = [b for b in settled if b["rule"] == rule]
    mine.sort(key=lambda b: (b["settled_at"] or "", b["id"]))
    n = len(mine)
    staked = sum(b["stake"] for b in mine)
    pnl = sum(b["pnl"] for b in mine)
    eq, curve = START, [START]
    for b in mine:
        eq += b["pnl"]; curve.append(round(eq, 2))
    r = [b["pnl"] / b["stake"] for b in mine]
    lo = hi = None
    if n >= 30:
        m = sum(r) / n
        sd = (sum((x - m) ** 2 for x in r) / (n - 1)) ** 0.5
        lo, hi = m - 1.96 * sd / n ** 0.5, m + 1.96 * sd / n ** 0.5
    o = [b for b in open_ if b["rule"] == rule]
    return dict(rule=rule, note=STRAT_NOTE.get(rule, ""), n=n, won=sum(b["status"] == "won" for b in mine), staked=round(staked, 2), pnl=round(pnl, 2),
                roi=(round(pnl / staked, 4) if staked else None), lo=lo, hi=hi, equity=round(START + pnl, 2), curve=curve,
                open=len(o), at_risk=round(sum(b["stake"] for b in o), 2))


def scoreboard_verdict(rows: list[dict], need: int = 100) -> str:
    """Plain-English answer to 'which makes more money?', refusing to name a winner on too little evidence."""
    live = [r for r in rows if r["n"] > 0 and r["rule"] != "MANUAL"]
    if not live:
        return "Too early: no automatic or tipster bet has settled yet. Nothing can be said about which is better."
    short = [r["rule"] for r in live if r["n"] < need]
    top = max(live, key=lambda r: r["roi"] if r["roi"] is not None else -9)
    if short:
        return (f"Too early to call: {', '.join(short)} {'has' if len(short) == 1 else 'have'} fewer than {need} settled bets. "
                f"Currently ahead: {top['rule']} at {top['roi'] * 100:+.1f}% per £1, but that is mostly luck at this size.")
    sig = [r for r in live if r["lo"] is not None and r["lo"] > 0]
    if sig:
        best = max(sig, key=lambda r: r["roi"])
        return f"{best['rule']} is ahead at {best['roi'] * 100:+.1f}% per £1 and its whole 95% range is above zero. Promising, but confirm on more bets before any real money."
    return f"No strategy has a proven profit yet. {top['rule']} leads at {top['roi'] * 100:+.1f}% per £1, but its 95% range still includes losing money."


def parse_results(text: str, div: str) -> dict:
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        d = _date(r.get("Date"))
        try:
            hg, ag = int(float(r["FTHG"])), int(float(r["FTAG"]))
        except (KeyError, TypeError, ValueError):
            continue
        if d and r.get("HomeTeam") and r.get("AwayTeam") and r.get("FTR"):
            out[f"{div}|{d.isoformat()}|{r['HomeTeam'].strip()}|{r['AwayTeam'].strip()}"] = (r["FTR"].strip(), hg, ag)
    return out


def settle(c, results: dict) -> int:
    n = 0
    for b in c.execute("SELECT * FROM bets WHERE status='open'").fetchall():
        res = results.get(f"{b['div']}|{b['date']}|{b['home']}|{b['away']}")
        if not res:
            continue
        ftr, hg, ag = res
        won = (ftr == b["sel"]) if b["market"] == "1X2" else ((hg + ag) > 2.5 if b["sel"] == "O25" else (hg + ag) < 2.5)
        pnl = round(b["stake"] * (b["odds"] - 1.0), 2) if won else -b["stake"]
        c.execute("UPDATE bets SET status=?, pnl=?, settled_at=? WHERE id=?", ("won" if won else "lost", pnl, datetime.now(timezone.utc).isoformat(timespec="seconds"), b["id"]))
        n += 1
    c.commit()
    return n


def _http(url):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "research-script"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read()


def tick(c, get=None, today: date | None = None) -> dict:
    """One cycle. Never raises for network problems: a failed fetch is reported in the result and the old data stays."""
    get = get or _http
    today = today or date.today()
    out = dict(fixtures=0, auto_placed=0, settled=0, tips=None, notes=[])
    try:
        st, body = get(FIXTURES_URL)
        if st == 200:
            fx = [f for f in parse_fixtures(body.decode("latin-1")) if f["date"] >= today.isoformat()]
            c.execute("DELETE FROM fixtures")
            c.executemany("INSERT OR REPLACE INTO fixtures(id,date,json) VALUES(?,?,?)", [(f["id"], f["date"], json.dumps(f)) for f in fx])
            c.commit()
            out["fixtures"] = len(fx)
            horizon = (today + timedelta(days=HORIZON_DAYS)).isoformat()
            for f in sorted(fx, key=lambda f: f["date"]):
                if f["date"] > horizon:
                    continue
                for rule, market, sel, _ in qualifies(f):
                    if available(c, rule) < AUTO_STAKE:
                        break
                    try:
                        place(c, f, market, sel, AUTO_STAKE, rule=rule, source="auto", today=today)
                        out["auto_placed"] += 1
                    except ValueError:
                        pass                                      # already placed this exact bet
        else:
            out["notes"].append(f"fixtures: HTTP {st}")
    except Exception as e:
        out["notes"].append(f"fixtures: {type(e).__name__}")
    try:                                                    # the tipster's picks (public file in the repo); a missing file just means no tips yet
        st, body = get(TIPS_URL)
        if st == 200:
            tips = []
            for ln in body.decode("utf-8", "replace").splitlines():
                try:
                    tips.append(json.loads(ln))
                except ValueError:
                    pass
            out["tips"] = ingest_tips(c, tips, today)
    except Exception as e:
        out["notes"].append(f"tips: {type(e).__name__}")
    try:
        need = {(season_of(date.fromisoformat(b["date"])), b["div"]) for b in c.execute("SELECT date,div FROM bets WHERE status='open' AND date<=?", (today.isoformat(),))}
        results = {}
        for s, dv in sorted(need):
            st, body = get(RESULT_URL.format(s=s, d=dv))
            if st == 200:
                results.update(parse_results(body.decode("latin-1"), dv))
        out["settled"] = settle(c, results)
    except Exception as e:
        out["notes"].append(f"results: {type(e).__name__}")
    c.execute("INSERT OR REPLACE INTO meta VALUES('last_tick', ?)", (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
    c.commit()
    return out


def state(c, today: date | None = None) -> dict:
    """Everything the dashboard shows, from the ledger only."""
    today = today or date.today()
    bets = [dict(r) for r in c.execute("SELECT * FROM bets ORDER BY id DESC").fetchall()]
    settled = sorted([b for b in bets if b["status"] != "open"], key=lambda b: (b["settled_at"] or "", b["id"]))
    eq, curve = START, [START]
    for b in settled:
        eq += b["pnl"]
        curve.append(round(eq, 2))
    staked = sum(b["stake"] for b in settled)
    by_rule = {}
    for b in settled:
        r = by_rule.setdefault(b["rule"], dict(n=0, staked=0.0, pnl=0.0, won=0))
        r["n"] += 1; r["staked"] += b["stake"]; r["pnl"] += b["pnl"]; r["won"] += b["status"] == "won"
    fx = [json.loads(r["json"]) for r in c.execute("SELECT json FROM fixtures WHERE date>=? ORDER BY date, id LIMIT 80", (today.isoformat(),))]
    lt = c.execute("SELECT v FROM meta WHERE k='last_tick'").fetchone()
    open_b = [b for b in bets if b["status"] == "open"]
    rules = list(STRATS) + sorted({b["rule"] for b in bets} - set(STRATS))
    board = [strategy_stats(settled, open_b, r) for r in rules]
    tips = [dict(json.loads(r["json"]), status=r["status"], detail=r["detail"]) for r in c.execute("SELECT * FROM tips ORDER BY json_extract(json,'$.date') DESC, id LIMIT 60")]
    return dict(board=board, verdict=scoreboard_verdict(board), tips=tips, start=START, equity=round(eq, 2), available=available(c), open=[b for b in bets if b["status"] == "open"], settled=list(reversed(settled)),
                curve=curve, n_settled=len(settled), won=sum(b["status"] == "won" for b in settled), staked=round(staked, 2),
                roi=(round((eq - START) / staked, 4) if staked else None), by_rule=by_rule, fixtures=fx, last_tick=lt[0] if lt else None,
                min_stake=MIN_STAKE, auto_stake=AUTO_STAKE)
