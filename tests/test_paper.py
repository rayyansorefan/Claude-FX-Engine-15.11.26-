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
    assert "<script" not in D.render(None)


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
    assert post("/api/tick", {})[0] == 200 and P.available(c) == 95.0
    srv.shutdown()


def test_fixtures_accept_pinnacle_under_pp_names():
    csv = "Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A,PPH,PPD,PPA\nE0,21/11/2026,15:00,A,B,3.0,3.4,2.4,2.5,3.4,3.2\n"
    f = P.parse_fixtures(csv)[0]
    assert f["ps"] == [2.5, 3.4, 3.2] and any(s == "H" for _, _, s, _ in P.qualifies(f))
