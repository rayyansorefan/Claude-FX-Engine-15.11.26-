import json, threading, urllib.request, urllib.error
from datetime import date
import pytest
from fxengine.bets import paper as P, paper_serve as S, dashboard as D

TODAY = date(2026, 11, 20)
FX_CSV = ("Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A,PSH,PSD,PSA,B365>2.5,B365<2.5,P>2.5,P<2.5\n"
          "E0,21/11/2026,15:00,Arsenal,Chelsea,3.00,3.40,2.40,2.50,3.40,3.20,1.90,1.95,1.90,1.95\n"
          "E0,21/11/2026,17:30,Spurs,Fulham,1.80,-,4.50,,,,,,,\n"
          "E0,01/11/2026,15:00,Old,Match,2.0,3.0,3.0,2.0,3.0,3.0,,,,\n")
RES_CSV = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\nE0,21/11/2026,Arsenal,Chelsea,2,1,H\nE0,21/11/2026,Spurs,Fulham,0,0,D\n"


def fx(i=0):
    return P.parse_fixtures(FX_CSV)[i]


def test_parse_fixtures_handles_blanks_and_dashes():
    f = P.parse_fixtures(FX_CSV)
    assert len(f) == 3 and f[0]["id"] == "E0|2026-11-21|Arsenal|Chelsea" and f[0]["b365"] == [3.0, 3.4, 2.4]
    assert f[1]["b365"][1] is None and f[1]["ps"] == [None, None, None]


def test_qualifies_only_when_bet365_beats_the_sharp_price_by_3pc():
    q = P.qualifies(fx(0))
    assert {(r, m, s) for r, m, s, _ in q} >= {("V1P", "1X2", "H"), ("V1", "1X2", "H")}
    assert all(s != "A" for _, _, s, _ in q) and P.qualifies(fx(1)) == []        # no Pinnacle price -> nothing auto-placed


def test_place_validates_and_tracks_virtual_cash():
    c = P.connect(":memory:")
    bid = P.place(c, fx(0), "1X2", "H", 10.0, today=TODAY)
    assert bid and P.available(c) == 90.0
    for args, msg in [((fx(0), "1X2", "H", 5.0), "already"), ((fx(0), "1X2", "D", 0.1), "Minimum"), ((fx(0), "1X2", "D", 500.0), "Not enough"),
                      ((fx(2), "1X2", "H", 1.0), "already been played"), ((fx(1), "1X2", "D", 1.0), "No Bet365 price")]:
        with pytest.raises(ValueError, match=msg):
            P.place(c, *args, today=TODAY)
    assert P.available(c) == 90.0


def test_settlement_pays_correctly_and_state_curve():
    c = P.connect(":memory:")
    P.place(c, fx(0), "1X2", "H", 10.0, today=TODAY)          # Arsenal win at 3.00 -> +20
    P.place(c, fx(0), "OU", "U25", 5.0, today=TODAY)          # 3 goals -> under loses -5
    P.place(c, fx(1), "1X2", "A", 4.0, today=TODAY)           # draw -> lose -4
    n = P.settle(c, P.parse_results(RES_CSV, "E0"))
    s = P.state(c, TODAY)
    assert n == 3 and s["n_settled"] == 3 and s["won"] == 1 and s["equity"] == 111.0 and s["curve"][-1] == 111.0 and s["available"] == 111.0
    assert abs(s["roi"] - 11 / 19) < 1e-3


def test_tick_places_auto_bets_once_and_settles_later():
    c = P.connect(":memory:")
    def get(url):
        if "fixtures" in url:
            return 200, FX_CSV.encode()
        return 200, RES_CSV.encode()
    r1 = P.tick(c, get, today=TODAY)
    assert r1["fixtures"] == 2 and r1["auto_placed"] >= 2 and r1["settled"] == 0           # the 01/11 fixture is in the past -> dropped
    assert P.tick(c, get, today=TODAY)["auto_placed"] == 0                                 # no duplicates
    r3 = P.tick(c, get, today=date(2026, 11, 22))
    assert r3["settled"] >= 2 and P.state(c, today=date(2026, 11, 22))["n_settled"] >= 2


def test_tick_survives_a_dead_network():
    c = P.connect(":memory:")
    def boom(url):
        raise OSError("down")
    out = P.tick(c, boom, today=TODAY)
    assert out["auto_placed"] == 0 and out["notes"]


def test_dashboard_shows_paper_panel_with_buttons_and_stays_scriptless_without_it():
    c = P.connect(":memory:")
    P.tick(c, lambda u: (200, FX_CSV.encode()), today=TODAY)
    h = D.render(None, paper=P.state(c, TODAY))
    assert "PAPER" in h and "Paper trading" in h and 'onclick="bet(this)"' in h and "Nothing is ever sent" in h
    assert "<script src" not in D.render(None) and "https://" not in D.render(None)


def test_server_places_paper_bets_over_http_and_rejects_non_json():
    c = P.connect(":memory:")
    P.place  # noqa
    c.execute("INSERT INTO fixtures VALUES(?,?,?)", (fx(0)["id"], "2999-01-01", json.dumps({**fx(0), "date": "2999-01-01"})))
    c.commit()
    srv = S.ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(c, tick_fn=lambda cn: dict(fixtures=0, auto_placed=0, settled=0, notes=[])))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    def post(path, body, ctype="application/json"):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": ctype})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    assert "PAPER" in urllib.request.urlopen(base + "/").read().decode()
    hub = urllib.request.urlopen(base + "/hub").read().decode()
    assert "FX Engine" in hub and "Bookie Engine" in hub and ":8787/" in hub and "__FXPORT__" not in hub
    assert post("/api/bet", dict(id=fx(0)["id"], market="1X2", sel="H", stake=5))[0] == 200
    assert post("/api/bet", dict(id=fx(0)["id"], market="1X2", sel="H", stake=5))[0] == 400            # duplicate
    assert post("/api/bet", dict(id=fx(0)["id"], market="1X2", sel="D", stake="abc"))[0] == 400
    assert post("/api/bet", dict(id="nope", market="1X2", sel="H", stake=1))[0] == 404
    assert post("/api/bet", dict(id=fx(0)["id"], market="1X2", sel="D", stake=1), ctype="text/plain")[0] == 415
    import http.server
    class Up(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"<html>FXPAGE-OK</html>")
        def log_message(self, *a): pass
    up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Up); threading.Thread(target=up.serve_forever, daemon=True).start()
    S.FX_HOST[0], S.FX_PORT[0] = "127.0.0.1", up.server_address[1]
    assert "FXPAGE-OK" in urllib.request.urlopen(base + "/fx").read().decode()                  # relayed, same-origin
    S.FX_PORT[0] = 1                                                                            # nothing there -> friendly message, not a crash
    assert "FX dashboard not reachable" in urllib.request.urlopen(base + "/fx").read().decode()
    up.shutdown()
    assert "setInterval" in urllib.request.urlopen(base + "/hub").read().decode() and "refreshes every 60s" in urllib.request.urlopen(base + "/hub").read().decode()
    assert post("/api/tick", {})[0] == 200 and P.available(c) == 95.0
    srv.shutdown()


def test_fixtures_accept_pinnacle_under_pp_names():
    csv = "Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A,PPH,PPD,PPA\nE0,21/11/2026,15:00,A,B,3.0,3.4,2.4,2.5,3.4,3.2\n"
    f = P.parse_fixtures(csv)[0]
    assert f["ps"] == [2.5, 3.4, 3.2] and any(s == "H" for _, _, s, _ in P.qualifies(f))


def test_live_page_refreshes_itself_but_the_static_file_does_not():
    c = P.connect(":memory:")
    live = D.render(None, paper=P.state(c, TODAY), auto=60)
    assert "setInterval" in live and "60000" in live and "refreshes every 60s" in live and "tagName===&#x27;INPUT&#x27;" not in live
    assert "setInterval" not in D.render(None, paper=P.state(c, TODAY)) and "setInterval" not in D.render(None)
    assert "setInterval" in S.page(c)                                  # the server's own page uses the default 60s


FX_PS = ("Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A,PPH,PPD,PPA\n"
         "E0,21/11/2026,15:00,Arsenal,Chelsea,3.00,3.40,2.40,2.50,3.40,3.20\n"
         "E0,22/11/2026,14:00,Manchester United,Liverpool,2.20,3.60,3.30,2.30,3.60,3.30\n")


def _db_with_fixtures():
    c = P.connect(":memory:")
    for f in P.parse_fixtures(FX_PS):
        c.execute("INSERT INTO fixtures VALUES(?,?,?)", (f["id"], f["date"], json.dumps(f)))
    c.commit()
    return c


def test_check_bet_prices_against_the_sharp_fair_price():
    f = P.parse_fixtures(FX_PS)[0]
    good = P.check_bet(f, "H")                                   # Bet365 3.00 vs Pinnacle 2.50 -> clearly better
    assert good["ok"] and good["tone"] == "good" and good["edge"] > 0.15 and good["per10"] > 1.5
    poor = P.check_bet(f, "A", 2.20)
    assert poor["tone"] == "crit" and poor["edge"] < 0 and "paying" in poor["verdict"]
    assert not P.check_bet(f, "O25")["ok"] and not P.check_bet(P.parse_fixtures(FX_CSV)[1], "H")["ok"] and not P.check_bet(f, "H", 0.5)["ok"]


def test_each_strategy_has_its_own_virtual_100():
    c = _db_with_fixtures()
    f = P.parse_fixtures(FX_PS)[0]
    P.place(c, f, "1X2", "D", 100.0, rule="MANUAL", today=TODAY)         # manual spends everything
    assert P.available(c, "MANUAL") == 0.0 and P.available(c, "V1") == 100.0
    P.place(c, f, "1X2", "H", 2.0, rule="V1", source="auto", today=TODAY)  # ...but V1 still has its own cash
    with pytest.raises(ValueError, match="Not enough"):
        P.place(c, f, "1X2", "A", 1.0, rule="MANUAL", today=TODAY)


def test_tips_are_matched_fuzzily_placed_at_the_current_price_and_never_twice():
    c = _db_with_fixtures()
    tips = [dict(id="t1", date="2026-11-21", home="Arsenal FC", away="Chelsea", market="1X2", sel="H", p=0.45, min_odds=2.8, why="form"),
            dict(id="t2", date="2026-11-22", home="Man United", away="Liverpool FC", market="1X2", sel="H", p=0.4, min_odds=2.5, why="home"),   # price 2.20 < 2.5
            dict(id="t3", date="2026-11-21", home="Nobody", away="Nowhere", market="1X2", sel="D", p=0.3, min_odds=3.0, why="x")]
    r = P.ingest_tips(c, tips, TODAY)
    assert r == dict(placed=1, waiting=2, expired=0)
    b = c.execute("SELECT * FROM bets").fetchall()
    assert len(b) == 1 and b[0]["rule"] == "TIPSTER" and b[0]["odds"] == 3.0 and b[0]["p"] == 0.45 and b[0]["note"] == "form" and b[0]["source"] == "tip"
    assert P.ingest_tips(c, tips, TODAY)["placed"] == 0 and c.execute("SELECT COUNT(*) FROM bets").fetchone()[0] == 1
    assert P.ingest_tips(c, tips, date(2026, 11, 23))["expired"] == 2                                 # past kick-off: unmatched / price never reached
    st = {t["id"]: t["status"] for t in P.state(c, date(2026, 11, 23))["tips"]}
    assert st == {"t1": "placed", "t2": "expired", "t3": "expired"}


def test_old_ledgers_are_upgraded_in_place(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    o = sqlite3.connect(db)
    o.executescript("CREATE TABLE bets(id INTEGER PRIMARY KEY, placed_at TEXT, source TEXT, rule TEXT, div TEXT, date TEXT, home TEXT, away TEXT, market TEXT, sel TEXT, odds REAL, stake REAL, status TEXT DEFAULT 'open', pnl REAL, settled_at TEXT, UNIQUE(div,date,home,away,market,sel,rule));"
                    "INSERT INTO bets(placed_at,source,rule,div,date,home,away,market,sel,odds,stake) VALUES('x','manual','MANUAL','E0','2026-11-21','A','B','1X2','H',2.0,5.0);")
    o.commit(); o.close()
    c = P.connect(db)
    assert {"p", "note"} <= {r[1] for r in c.execute("PRAGMA table_info(bets)")} and c.execute("SELECT COUNT(*) FROM bets").fetchone()[0] == 1


def _row(rule, n, roi, lo=None):
    return dict(rule=rule, n=n, roi=roi, lo=lo)


def test_scoreboard_refuses_to_name_a_winner_on_too_little_evidence():
    assert "Too early: no" in P.scoreboard_verdict([_row("V1", 0, None), _row("TIPSTER", 0, None)])
    assert "Too early to call" in P.scoreboard_verdict([_row("V1", 40, 0.2), _row("TIPSTER", 150, -0.05)])
    assert "No strategy has a proven profit" in P.scoreboard_verdict([_row("V1", 150, 0.05, -0.03), _row("TIPSTER", 150, -0.05, -0.1)])
    assert "whole 95% range is above zero" in P.scoreboard_verdict([_row("V1", 150, 0.08, 0.01), _row("TIPSTER", 150, -0.05, -0.1)])


def test_strategy_stats_gives_a_range_only_with_enough_bets():
    def b(i, won): return dict(id=i, rule="V1", stake=2.0, pnl=(4.0 if won else -2.0), status="won" if won else "lost", settled_at=f"2026-11-{i % 28 + 1:02d}T10:00")
    few = P.strategy_stats([b(i, i % 3 == 0) for i in range(10)], [], "V1")
    many = P.strategy_stats([b(i, i % 3 == 0) for i in range(60)], [], "V1")
    assert few["lo"] is None and many["lo"] is not None and many["lo"] < many["roi"] < many["hi"] and many["equity"] == round(100 + many["pnl"], 2)


def test_dashboard_has_the_new_tabs_and_the_server_checks_bets():
    c = _db_with_fixtures()
    h = D.render(None, paper=P.state(c, TODAY))
    assert all(x in h for x in ("Scoreboard", "Check a bet", "Tipster picks", "Which makes more money?", 'id="ck-match"', "Arsenal v Chelsea"))
    assert S.api_check(c, dict(id="E0|2026-11-21|Arsenal|Chelsea", sel="H", price="3.0"))[1]["tone"] == "good"
    assert S.api_check(c, dict(id="nope", sel="H"))[0] == 404 and S.api_check(c, dict(id="E0|2026-11-21|Arsenal|Chelsea", sel="H", price="abc"))[0] == 400
