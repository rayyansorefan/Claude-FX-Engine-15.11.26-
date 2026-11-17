import json
import numpy as np, pandas as pd
from fxengine.data import store
from fxengine.live import scan as sc
from fxengine.live.sizing import lots_for_risk, gbp_per_pip_per_lot
from fxengine.dashboard import build as db
from test_setups import synth

PX = {"GBPUSD": 1.25, "USDJPY": 150.0, "USDCHF": 0.9, "USDCAD": 1.35, "GBPJPY": 190.0}


def test_sizing():
    lots, pips = lots_for_risk("EURUSD", 1.1000, 1.0985, PX)         # 15 pips, $10/pip/lot -> GBP 8/pip/lot
    assert abs(pips - 15.0) < 1e-6 and abs(lots - 0.16) < 0.011
    assert gbp_per_pip_per_lot("EURGBP", PX) == 10.0
    assert gbp_per_pip_per_lot("USDJPY", PX) > 0 and gbp_per_pip_per_lot("USDCAD", PX) > 0


def _store(tmp):
    for i, s in enumerate(sc.PAIRS):
        m5 = synth(40000, seed=50 + i)
        m5.index = pd.date_range("2025-06-01", periods=len(m5), freq="5min", tz="UTC")
        px = {"JPY": 150.0, "": 1.1}
        store.merge_save(s, "M5", m5, tmp)
        from fxengine.data.resample import resample
        for tf in ("H1", "H4"):
            store.merge_save(s, tf, resample(m5, tf, base="M5"), tmp)
    return m5.index[-1] + pd.Timedelta(minutes=5)


def test_scan_stale_returns_no_candidates_and_fresh_works(tmp_path):
    end = _store(tmp_path)
    stale = sc.scan(tmp_path, now=end + pd.Timedelta(days=3))
    assert stale["status"] == "STALE" and stale["candidates"] == []
    fresh = sc.scan(tmp_path, now=end)
    assert fresh["status"] == "OK" and len(fresh["candidates"]) <= 5
    for c in fresh["candidates"]:
        assert "UNPROVEN" in c["note"]


def test_dashboard_builds_without_and_with_research_files(tmp_path, monkeypatch):
    end = _store(tmp_path)
    monkeypatch.chdir(tmp_path)
    out = db.build(root=tmp_path, out=tmp_path / "d" / "index.html", now=end)
    html = open(out).read()
    assert "Reliability" in html and "no edge found" in html and "data age" in html


def test_journal_analytics_and_panel(tmp_path):
    from fxengine.dashboard import journal as J
    rows = []
    for i in range(12):
        rows.append(dict(opened=f"2026-11-{10 + i // 6} {8 + i % 6}:00", closed=f"2026-11-{10 + i // 6} {9 + i % 6}:00", pair="EURUSD",
                         direction="long", lots=0.1, entry=1.1, exit=1.1, pnl_gbp=(20 if i % 3 == 0 else -9), run_id=("r%d" % i if i % 2 else ""), note=""))
    p = tmp_path / "j.csv"; pd.DataFrame(rows).to_csv(p, index=False)
    a = J.analyse(J.load(p))
    assert a["n"] == 12 and a["n_off"] == 6 and 0 < a["on_plan"] < 1 and a["worst_streak"] >= 2
    assert "Plan adherence" in J.panel(J.load(p)) and "No trades logged" in J.panel(None)


def test_server_rebuilds_on_every_request(tmp_path, monkeypatch):
    import threading, urllib.request
    from fxengine.dashboard import serve
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(serve.STATE, "cache", 0)                         # legacy mode: rebuild synchronously on every request
    _store(tmp_path / "data" / "candles")
    srv = serve.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}/")
        a = r.read().decode()
        assert r.headers["Cache-Control"] == "no-store" and "FX ENGINE" in a
        # new data appears -> the next refresh shows it (no cached page)
        (tmp_path / "data" / "journal.csv").write_text("opened,closed,pair,direction,lots,entry,exit,pnl_gbp,run_id,note\n"
                                                       "2026-11-10 08:00,2026-11-10 09:00,EURUSD,long,0.1,1,1,50,,x\n")
        b = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        assert "£2,550" in b and "£2,550" not in a
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/secret")
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()


def test_dashboard_shows_setups_from_the_ledger_not_a_scan_file(tmp_path, monkeypatch):
    import json
    from fxengine.dashboard.build import build
    from fxengine.live import db as DB
    monkeypatch.chdir(tmp_path)
    _store(tmp_path / "data" / "candles")
    (tmp_path / "data" / "latest_scan.json").write_text(json.dumps({"candidates": [dict(pair="GBPUSD", type="E1_strength", tf="H1", direction="short",
        entry_kind="stop", entry=1.3, stop=1.31, target=1.28, created="2025-06-03 09:00+00:00", expires="2025-06-03 15:00+00:00", stop_pips=100, lots_for_20gbp_risk=0.02, score=1)]}))
    conn = DB.connect(str(tmp_path / "data" / "engine.db"))
    rec = dict(pair="EURUSD", type="E1_strength", tf="H1", direction="long", entry_kind="stop", entry=1.1010, stop=1.0990, target=1.1030,
               created="2025-06-03 09:00+00:00", expires="2025-06-03 15:00+00:00", stop_pips=20.0, lots_for_20gbp_risk=0.1, score=2.0,
               reason="Strength gap z=+1.7\nStop 2 ATR", invalidation=1.0995)
    DB.add_setup(conn, "live-1", rec)
    conn.execute("INSERT INTO events VALUES('live-1',0,'t',NULL,'PUBLISHED','p')"); conn.execute("INSERT INTO events VALUES('live-1',1,'t','PUBLISHED','TRIGGERED','f')"); conn.commit()
    html = build(root=tmp_path / "data" / "candles", out=None, now=pd.Timestamp("2025-06-03 10:00", tz="UTC"))
    assert "EURUSD" in html and "Strength gap" in html and "class='trade " in html and "UNPROVEN" in html
    assert "<span class='state'>PENDING</span>" in html or "<span class='state'>OPEN</span>" in html   # one complete card per trade
    assert "GBPUSD</span><span class='dir short'>" not in html          # the stale scan file is ignored once a ledger exists
    assert "Strategies tested" in html and "Seven strategy ideas" not in html


def test_live_pnl_panel_numbers_and_charts_tab(tmp_path, monkeypatch):
    from fxengine.live import db as DB
    monkeypatch.chdir(tmp_path)
    end = _store(tmp_path / "data" / "candles")
    now = end + pd.Timedelta(minutes=3)
    c = DB.connect("data/engine.db")
    for i, (reason, r) in enumerate([("TARGET", 1.9), ("STOP", -1.1), ("EXPIRED", 0.0)]):
        rec = dict(pair="EURUSD", direction="long", type="E1_strength", tf="H1", created=str(now - pd.Timedelta(hours=5 - i)),
                   expires=str(now), entry=1.1, stop=1.09, target=1.12, entry_kind="stop", stop_pips=100, lots_for_20gbp_risk=.1, score=1.0)
        DB.add_setup(c, f"r{i}", rec)
        c.execute("INSERT INTO events VALUES(?,?,?,?,?,?)", (f"r{i}", 0, rec["created"], None, "PUBLISHED", "published"))
        c.execute("INSERT INTO outcomes(run_id,reason,net_r,fill,exit,resolved_at) VALUES(?,?,?,?,?,?)", (f"r{i}", reason, r, 1.1, 1.1, str(now - pd.Timedelta(minutes=30 + i))))
    c.commit()
    html = db.build(root=tmp_path / "data" / "candles", out=None, now=now)
    assert "Live profit &amp; loss" in html
    assert "+£16" in html                                     # (1.9 - 1.1) R x £20 = +£16 realised today
    assert "£2,516" in html                                   # hypothetical balance
    assert "1 · 1" in html and "50% win rate" in html
    assert "expired or invalidated without a trade 1" in html
    assert "All pairs at a glance" in html and "pickPair" in html and "To PDH" in html
    lv = json.loads(html.split("id='lv'>")[1].split("</script>")[0])
    assert {x["k"] for x in lv["EURUSD"]} >= {"PDH", "PDL", "DO"}


def test_top_bar_shows_uptime_and_next_cycle(tmp_path, monkeypatch):
    from fxengine.live import db as DB
    monkeypatch.chdir(tmp_path)
    end = _store(tmp_path / "data" / "candles")
    now = pd.Timestamp("2026-11-17 10:02", tz="UTC")                       # a Tuesday: market open
    c = DB.connect("data/engine.db")
    for i in range(10):
        c.execute("INSERT INTO cycles VALUES(?,?,?,?,?,?)", (str(now - pd.Timedelta(minutes=5 * (i + 1))), 1 if i != 3 else 0, "OK" if i != 3 else "STALE", 1.0, 2.0, ""))
    c.commit()
    html = db.build(root=tmp_path / "data" / "candles", out=None, now=now)
    assert "uptime 90.0% (9 of 10 cycles, 7d)" in html and "next cycle 10:05 UK" in html
    sat = db.build(root=tmp_path / "data" / "candles", out=None, now=pd.Timestamp("2026-11-21 12:00", tz="UTC"))
    assert "market opens Sun 22:00 UK" in sat


def test_server_never_makes_a_visitor_wait_for_a_rebuild(monkeypatch):
    """Stale-while-revalidate: the last finished page is served instantly even while a (slow) rebuild runs."""
    import threading, time, urllib.request
    from fxengine.dashboard import serve
    gate = threading.Event()
    built = []

    def slow_build(out=None, banner="", **kw):
        built.append(1)
        if len(built) > 1:
            gate.wait(5)                                                   # the rebuild is slow (e.g. waiting on the price-file lock)
        return f"<html><body>PAGE v{len(built)}</body></html>"
    monkeypatch.setattr(serve, "build", slow_build)
    monkeypatch.setitem(serve.STATE, "cache", 1)
    monkeypatch.setitem(serve.STATE, "html", None)
    monkeypatch.setitem(serve.STATE, "building", False)
    monkeypatch.setitem(serve.STATE, "built", 0.0)
    srv = serve.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    get = lambda: urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3).read().decode()
    try:
        first = get()                                                      # nothing built yet: instant "building" page, no blocking
        assert "Building the dashboard" in first
        for _ in range(50):                                                # the background build finishes
            if "PAGE v1" in get():
                break
            time.sleep(0.05)
        time.sleep(1.2)                                                    # cache is now stale -> triggers a slow background rebuild
        t0 = time.time()
        page = get()
        assert "PAGE v1" in page and time.time() - t0 < 1.0                # served the OLD page immediately
        assert "Page built" in page
        gate.set()
        for _ in range(60):
            if "PAGE v2" in get():
                break
            time.sleep(0.05)
        assert "PAGE v2" in get()
    finally:
        gate.set()
        srv.shutdown()
