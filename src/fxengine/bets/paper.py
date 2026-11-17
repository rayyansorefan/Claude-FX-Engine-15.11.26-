"""PAPER betting ledger. Every bet here is hypothetical: a row in a local SQLite file with a virtual bankroll. Nothing is ever sent to Bet365 or any
bookmaker, no login, no credentials. Upcoming matches + Bet365/Pinnacle prices come from football-data.co.uk's free fixtures.csv; results from its season CSVs.
Stdlib + numpy only (the VM has ~200 MB spare).  tick() = fetch fixtures, auto-place qualifying paper bets, settle finished ones."""
from __future__ import annotations
import csv, io, json, sqlite3, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from . import odds as O

DB = Path("data/bets/paper.db")
START = 100.0                # virtual bankroll in £
AUTO_STAKE = 2.0             # flat paper stake per automatic bet (2% of the starting £100)
MIN_STAKE = 0.5
HORIZON_DAYS = 7             # only auto-bet matches kicking off within a week
EDGE = 0.03                  # V1: Bet365 price at least 3% better than the sharp (Pinnacle, margin-removed) fair price
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
RESULT_URL = "https://www.football-data.co.uk/mmz4281/{s}/{d}.csv"
SCHEMA = """
CREATE TABLE IF NOT EXISTS bets(id INTEGER PRIMARY KEY, placed_at TEXT, source TEXT, rule TEXT, div TEXT, date TEXT, home TEXT, away TEXT, market TEXT, sel TEXT,
  odds REAL, stake REAL, status TEXT DEFAULT 'open', pnl REAL, settled_at TEXT, UNIQUE(div, date, home, away, market, sel, rule));
CREATE TABLE IF NOT EXISTS fixtures(id TEXT PRIMARY KEY, date TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""


def connect(path=DB) -> sqlite3.Connection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(path), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
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
                        ps=[_f(r.get("PSH")), _f(r.get("PSD")), _f(r.get("PSA"))],
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


def available(c) -> float:
    """Virtual cash free to stake = start + settled profit - stakes tied up in open bets."""
    pnl = c.execute("SELECT COALESCE(SUM(pnl),0) FROM bets WHERE status!='open'").fetchone()[0]
    open_ = c.execute("SELECT COALESCE(SUM(stake),0) FROM bets WHERE status='open'").fetchone()[0]
    return round(START + pnl - open_, 2)


def place(c, fix: dict, market: str, sel: str, stake: float, rule="MANUAL", source="manual", today: date | None = None) -> int:
    """Record a PAPER bet. Raises ValueError with a plain-English reason if it cannot be recorded."""
    today = today or date.today()
    o = price(fix, market, sel)
    if o is None:
        raise ValueError("No Bet365 price for that pick.")
    if not isinstance(stake, (int, float)) or stake != stake or stake < MIN_STAKE:
        raise ValueError(f"Minimum paper stake is £{MIN_STAKE:.2f}.")
    if date.fromisoformat(fix["date"]) < today:
        raise ValueError("That match has already been played.")
    if stake > available(c) + 1e-9:
        raise ValueError(f"Not enough virtual cash (£{available(c):.2f} free).")
    try:
        cur = c.execute("INSERT INTO bets(placed_at,source,rule,div,date,home,away,market,sel,odds,stake) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (datetime.now(timezone.utc).isoformat(timespec="seconds"), source, rule, fix["div"], fix["date"], fix["home"], fix["away"], market, sel, o, round(float(stake), 2)))
    except sqlite3.IntegrityError:
        raise ValueError("You already have that exact paper bet.")
    c.commit()
    return cur.lastrowid


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
    out = dict(fixtures=0, auto_placed=0, settled=0, notes=[])
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
                    if available(c) < AUTO_STAKE:
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
    return dict(start=START, equity=round(eq, 2), available=available(c), open=[b for b in bets if b["status"] == "open"], settled=list(reversed(settled)),
                curve=curve, n_settled=len(settled), won=sum(b["status"] == "won" for b in settled), staked=round(staked, 2),
                roi=(round((eq - START) / staked, 4) if staked else None), by_rule=by_rule, fixtures=fx, last_tick=lt[0] if lt else None,
                min_stake=MIN_STAKE, auto_stake=AUTO_STAKE)
