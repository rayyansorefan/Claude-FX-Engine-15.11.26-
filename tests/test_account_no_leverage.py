import pandas as pd
from fxengine.live import account as A

PX = {"GBPUSD": 1.3126, "EURGBP": 0.86, "AUDUSD": 0.65, "NZDUSD": 0.60, "USDJPY": 150.0}


def test_value_of_a_lot_in_pounds_for_each_base_currency():
    assert abs(A.per_lot_gbp("GBPUSD", PX) - 100000) < 1e-6
    assert abs(A.per_lot_gbp("USDJPY", PX) - 100000 / 1.3126) < 1e-6
    assert abs(A.per_lot_gbp("EURGBP", PX) - 86000) < 1e-6
    assert abs(A.per_lot_gbp("AUDUSD", PX) - 100000 * 0.65 / 1.3126) < 1e-6
    assert A.per_lot_gbp("EURJPY", {}) is None


def test_lots_never_exceed_what_the_free_cash_can_buy():
    assert A.affordable_lots(0.05, 100000, 2500) == 0.02          # 0.05 lots = £5,000 > £2,500: capped to 0.02 lots (£2,000)
    assert A.affordable_lots(0.01, 100000, 2500) == 0.01          # small enough already
    assert A.affordable_lots(0.05, 100000, 900) == 0.0            # cannot afford even 0.01 lot (£1,000)
    assert A.affordable_lots(0.05, 100000, 0) == 0.0 and A.affordable_lots(0.05, None, 2500) == 0.0


def _s(i, pair, created, end, lots, net_r=None):
    return dict(run_id=i, pair=pair, created=created, end=end, lots=lots, net_r=net_r)


def test_replay_never_holds_more_than_the_balance_and_frees_cash_when_a_trade_ends():
    s = [_s("a", "GBPUSD", "2026-11-18 08:00", "2026-11-18 12:00", 0.05, net_r=1.0),      # takes 0.02 lots (£2,000)
         _s("b", "EURGBP", "2026-11-18 09:00", None, 0.05),                              # only £500 free: EURGBP lot = £86,000: cannot afford
         _s("c", "GBPUSD", "2026-11-18 13:00", None, 0.05)]                                # a ended: cash is free again (+ a's profit)
    r = A.replay(s, PX)
    assert r["a"]["taken"] and r["a"]["lots"] == 0.02 and abs(r["a"]["scale"] - 0.4) < 1e-9
    assert not r["b"]["taken"] and "no free cash" in r["b"]["why"]
    assert r["c"]["taken"] and r["c"]["lots"] == 0.02
    for i, d in r.items():                                           # at no point more than balance+profit in positions
        assert d["value"] <= A.ACCOUNT + 20.0 * 1.0 * 0.4 + 1e-6


def test_replay_keeps_a_decision_stored_at_publish_time():
    s = [dict(_s("x", "GBPUSD", "2026-11-18 08:00", None, 0.05), lots_account=0.02, per_lot=100000)]
    assert A.replay(s, PX)["x"]["lots"] == 0.02


def test_publish_caps_new_setups_at_free_cash_and_keeps_publishing_what_it_cannot_afford(tmp_path):
    import json
    from fxengine.live import db as DB, loop, messages as M
    conn = DB.connect(str(tmp_path / "e.db"))
    now = pd.Timestamp("2026-11-18 11:00", tz="UTC")

    def c(pair, score):
        return dict(pair=pair, direction="long", type="E1_strength", tf="H1", entry_kind="stop", entry=1.1010, stop=1.0990, target=1.1030, created=str(now), expires=str(now + pd.Timedelta(hours=6)),
                    stop_pips=20.0, lots_for_20gbp_risk=0.05, score=score, note="UNPROVEN")
    out = loop.publish(conn, {}, lambda e, t: True, [c("GBPUSD", 2.0), c("EURGBP", 1.0)], now, px=PX)
    recs = {r["pair"]: json.loads(r["record"]) for r in conn.execute("SELECT pair, record FROM setups")}
    assert recs["GBPUSD"]["lots_account"] == 0.02 and abs(recs["GBPUSD"]["per_lot_gbp"] - 100000) < 1                # £5,000 wanted -> £2,000 held
    assert recs["EURGBP"]["lots_account"] == 0.0 and len(out) == 2                                                    # £86,000 per lot: cannot afford, still published and scored
    assert "NOT AFFORDABLE" in M.new(recs["EURGBP"]) and "no leverage" in M.new(recs["GBPUSD"]) and len(M.new(recs["GBPUSD"]).split("\n")) <= 3
    # without prices the old behaviour is kept (never blocks publishing)
    conn2 = DB.connect(str(tmp_path / "e2.db"))
    loop.publish(conn2, {}, lambda e, t: True, [c("GBPUSD", 2.0)], now)
    assert "lots_account" not in json.loads(conn2.execute("SELECT record FROM setups").fetchone()["record"])


def test_full_live_cycle_with_a_real_scan_result_publishes_with_the_cap_and_alerts_cleanly(tmp_path):
    """The exact path the live loop takes at the market open: scan() -> run_cycle -> publish -> alert. Uses the real scanner on synthetic candles for ALL pairs."""
    import json
    from test_live_dashboard import _store
    from fxengine.live import db as DB, loop, scan as SC, messages as M
    end = _store(tmp_path / "c")
    now = end + pd.Timedelta(minutes=3)
    res = SC.scan(tmp_path / "c", now=now)
    assert isinstance(res["px"], dict) and {"GBPUSD", "EURGBP", "AUDUSD", "NZDUSD"} <= set(res["px"])
    json.dumps(res)                                                                       # the scan result is saved as JSON by the loop: must serialise
    for cnd in res["candidates"]:
        assert cnd["per_lot_gbp"] is None or cnd["per_lot_gbp"] > 0
    # force a candidate through publish -> alert exactly as the loop does, at a publish hour
    t = pd.Timestamp("2026-11-23 10:00", tz="UTC")
    cnd = dict(pair="GBPUSD", direction="long", type="E1_strength", tf="H1", entry_kind="stop", entry=1.31, stop=1.308, target=1.314, created=str(t), expires=str(t + pd.Timedelta(hours=6)),
               stop_pips=20.0, lots_for_20gbp_risk=0.06, score=2.0, note="UNPROVEN", per_lot_gbp=None)
    conn = DB.connect(str(tmp_path / "e.db"))
    out = loop.publish(conn, {}, lambda e, tx: True, [cnd], t, px=res["px"])
    rec = json.loads(conn.execute("SELECT record FROM setups").fetchone()["record"])
    assert len(out) == 1 and 0 < rec["lots_account"] <= 0.06 and rec["lots_account"] * rec["per_lot_gbp"] <= 2500.0
    msg = M.new(rec)
    assert len(msg.split("\n")) <= 3 and "no leverage" in msg


def test_one_alert_of_each_kind_per_setup_even_if_a_replay_shifts_the_event_numbers(tmp_path):
    """Audit finding: duplicate NEW/TRIGGERED alerts for one setup. Dedupe used the event number only; now a hard rule per (setup, kind)."""
    from fxengine.live import db as DB, loop
    conn = DB.connect(str(tmp_path / "e.db"))
    sent = []
    send = lambda env, text: sent.append(text) or True
    c = dict(run_id="r1", expires="2026-11-23 16:00+00:00")
    now = pd.Timestamp("2026-11-23 10:00", tz="UTC")
    loop._alert(conn, {}, send, c, 0, "NEW", "new", now, now)
    loop._alert(conn, {}, send, c, 1, "TRIGGERED", "trig", now, now)
    loop._alert(conn, {}, send, c, 2, "TRIGGERED", "trig again (event numbers shifted by a replay)", now, now)
    loop._alert(conn, {}, send, c, 3, "NEW", "new again", now, now)
    assert sent == ["new", "trig"]                                                       # the owner is messaged once per kind
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM alerts ORDER BY idx")]
    assert kinds == ["NEW", "TRIGGERED", "SUPPRESSED-TRIGGERED", "SUPPRESSED-NEW"]        # and the attempt is recorded for the investigation
    assert conn.execute("SELECT COUNT(*) FROM alerts WHERE kind IN ('NEW','TRIGGERED') GROUP BY run_id, kind HAVING COUNT(*)>1").fetchone() is None


def test_a_401_from_oanda_alerts_the_owner_at_once_then_at_most_every_six_hours(tmp_path):
    from test_live_loop import make_store, Bag
    from fxengine.live import db as DB, loop
    d = make_store(tmp_path)
    now = d.index[-1] + pd.Timedelta(minutes=6)
    conn = DB.connect(str(tmp_path / "e.db"))
    bag = Bag()

    def boom():
        raise RuntimeError("401 Client Error: Unauthorized for url: https://api-fxpractice.oanda.com/...")
    loop.run_cycle(conn, {}, now, send=bag, root=tmp_path, refresh_fn=boom, scan_fn=lambda: [])
    assert len(bag.msgs) == 1 and "OANDA TOKEN REJECTED" in bag.msgs[0]                       # first 401: told at once (before: only after 3 in a row)
    loop.run_cycle(conn, {}, now + pd.Timedelta(minutes=5), send=bag, root=tmp_path, refresh_fn=boom, scan_fn=lambda: [])
    assert len(bag.msgs) == 1                                                                  # not spammed every 5 minutes
    loop.run_cycle(conn, {}, now + pd.Timedelta(hours=7), send=bag, root=tmp_path, refresh_fn=boom, scan_fn=lambda: [])
    assert len(bag.msgs) == 2                                                                  # reminded after 6 hours
    def other():
        raise RuntimeError("503 service unavailable")
    c2 = DB.connect(str(tmp_path / "e2.db")); b2 = Bag()
    for i in range(2):
        loop.run_cycle(c2, {}, now + pd.Timedelta(minutes=5 * i), send=b2, root=tmp_path, refresh_fn=other, scan_fn=lambda: [])
    assert b2.msgs == []                                                                       # other errors keep the 3-in-a-row rule


def test_fx_page_says_so_when_the_account_view_cannot_be_built(tmp_path, monkeypatch):
    from test_live_dashboard import _store
    from fxengine.dashboard import build as B
    from fxengine.live import db as DB
    monkeypatch.chdir(tmp_path)
    _store(tmp_path / "data" / "candles")
    conn = DB.connect(str(tmp_path / "data" / "engine.db"))
    rec = dict(pair="EURUSD", type="E1_strength", tf="H1", direction="long", entry_kind="stop", entry=1.1, stop=1.09, target=1.12, created="2025-06-03 08:00+00:00", expires="2025-06-03 15:00+00:00",
               stop_pips=100, lots_for_20gbp_risk=0.1, score=1.0)
    DB.add_setup(conn, "r0", rec)
    conn.execute("INSERT INTO events VALUES('r0',0,'2025-06-03 08:00+00:00',NULL,'PUBLISHED','p')"); conn.commit()
    import shutil
    shutil.rmtree(tmp_path / "data" / "candles" / "GBPUSD")                                    # a price file goes missing
    html = B.build(root=tmp_path / "data" / "candles", out=None, now=pd.Timestamp("2025-06-03 10:00", tz="UTC"))
    assert "ACCOUNT VIEW UNAVAILABLE" in html


def test_a_crash_while_sending_leaves_a_record_and_the_message_goes_out_exactly_once(tmp_path):
    """Audit F1 secondary path: the old code sent first and recorded after, so a kill in between meant a resend after restart."""
    from fxengine.live import db as DB, loop
    conn = DB.connect(str(tmp_path / "e.db"))
    c = dict(run_id="r1", expires="2026-11-23 16:00+00:00")
    now = pd.Timestamp("2026-11-23 10:00", tz="UTC")
    delivered = []

    def dies(env, text):
        raise KeyboardInterrupt                                                          # process killed during the send
    try:
        loop._alert(conn, {}, dies, c, 0, "NEW", "new setup", now, now)
    except KeyboardInterrupt:
        pass
    assert conn.execute("SELECT ok FROM alerts WHERE run_id='r1'").fetchone()["ok"] == 0                   # recorded before the send
    ok_send = lambda env, text: delivered.append(text) or True
    loop.retry_unsent(conn, {}, ok_send, now)                                           # restart: unsent rows are retried
    loop.retry_unsent(conn, {}, ok_send, now)
    assert delivered == ["new setup"] and conn.execute("SELECT ok FROM alerts WHERE run_id='r1'").fetchone()["ok"] == 1
