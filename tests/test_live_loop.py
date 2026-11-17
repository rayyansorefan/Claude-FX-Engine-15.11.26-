import numpy as np, pandas as pd
from fxengine.data import store
from fxengine.data.resample import resample
from fxengine.live import loop, db as DB, messages as M
from fxengine.audit.run import audit_text

T0 = pd.Timestamp("2025-06-03 08:00", tz="UTC")     # a Tuesday


def make_store(tmp, n_flat=60, n_ramp=40, n_after=20):
    px = np.r_[np.full(n_flat, 1.1000), np.linspace(1.1000, 1.1060, n_ramp), np.full(n_after, 1.1060)]
    idx = pd.date_range(T0, periods=len(px), freq="5min", tz="UTC")
    o = np.r_[px[0], px[:-1]]
    d = pd.DataFrame({"bid_o": o, "bid_h": np.maximum(o, px) + 1e-5, "bid_l": np.minimum(o, px) - 1e-5, "bid_c": px,
                      "ask_o": o + 3e-5, "ask_h": px + 3e-5, "ask_l": px + 3e-5, "ask_c": px + 3e-5, "volume": 1.0}, index=idx)
    store.merge_save("EURUSD", "M5", d, tmp)
    store.merge_save("EURUSD", "H1", resample(d, "H1", base="M5"), tmp)
    return d


def cand(created):
    return dict(pair="EURUSD", direction="long", type="E1_strength", tf="H1", entry_kind="stop", entry=1.1010, stop=1.0990,
                target=1.1030, created=str(created), expires=str(created + pd.Timedelta(hours=6)), stop_pips=20.0,
                lots_for_20gbp_risk=0.1, score=2.0, note="UNPROVEN")


class Bag:
    def __init__(self): self.msgs = []
    def __call__(self, env, text): self.msgs.append(text); return True


def test_full_lifecycle_alerts_once_and_restart_safe(tmp_path):
    d = make_store(tmp_path)
    now = d.index[-1] + pd.Timedelta(minutes=6)
    now = now.replace(hour=11, minute=0) if False else now
    conn = DB.connect(str(tmp_path / "e.db"))
    bag = Bag()
    created = d.index[40] + pd.Timedelta(minutes=5)
    for _ in range(3):
        st = loop.run_cycle(conn, {}, now, send=bag, root=tmp_path, refresh_fn=lambda: None, scan_fn=lambda: [cand(created)])
        assert st == "OK"
    kinds = [m.split(" ·")[0] for m in bag.msgs]
    assert kinds == ["🟢 NEW", "▶️ TRIGGERED", "✅ TARGET HIT"], kinds         # each exactly once, in order
    assert all(len(m.split("\n")) <= 3 for m in bag.msgs)
    # restart: new connection, same db -> no duplicate alerts
    conn2 = DB.connect(str(tmp_path / "e.db"))
    loop.run_cycle(conn2, {}, now, send=bag, root=tmp_path, refresh_fn=lambda: None, scan_fn=lambda: [cand(created)])
    assert len(bag.msgs) == 3
    out = conn.execute("SELECT * FROM outcomes").fetchall()
    assert len(out) == 1 and out[0]["reason"] == "TARGET" and out[0]["net_r"] > 0
    assert conn.execute("SELECT COUNT(*) FROM events WHERE to_state='RESOLVED'").fetchone()[0] == 1
    txt = audit_text(conn, now)
    assert len(txt.split("\n")) == 5 and "lifecycle gaps 0" in txt


def test_stale_data_fails_loudly_once_and_blocks_publishing(tmp_path):
    d = make_store(tmp_path)
    now = d.index[-1] + pd.Timedelta(minutes=60)
    conn = DB.connect(str(tmp_path / "e.db"))
    bag = Bag()
    for _ in range(2):
        st = loop.run_cycle(conn, {}, now, send=bag, root=tmp_path, refresh_fn=lambda: None, scan_fn=lambda: [cand(now)])
    assert st == "STALE" and sum("STALE" in m for m in bag.msgs) == 1
    assert conn.execute("SELECT COUNT(*) FROM setups").fetchone()[0] == 0
    assert conn.execute("SELECT ok FROM cycles ORDER BY ts DESC").fetchone()["ok"] == 0


def test_cap_one_per_pair_and_quiet_publish_hours(tmp_path):
    d = make_store(tmp_path)
    conn = DB.connect(str(tmp_path / "e.db"))
    bag = Bag()
    c1 = cand(T0 + pd.Timedelta(hours=1))
    pub = loop.publish(conn, {}, bag, [c1, dict(c1, entry=1.1011)], T0 + pd.Timedelta(hours=1))
    assert len(pub) == 1                                                   # second EURUSD setup blocked (one active per pair)
    night = loop.publish(conn, {}, bag, [dict(c1, pair="GBPUSD", created=str(T0 + pd.Timedelta(hours=2)))], T0.replace(hour=3))
    assert night == []                                                     # outside 07-20 UTC


def test_market_closed_and_message_format():
    assert loop.market_closed(pd.Timestamp("2025-06-07 12:00", tz="UTC")) and not loop.market_closed(pd.Timestamp("2025-06-03 12:00", tz="UTC"))
    assert "UNPROVEN" in M.new(cand(T0)) and len(M.halfway(cand(T0), "HOLD", "x").split("\n")) == 2


def test_failed_send_is_retried(tmp_path):
    d = make_store(tmp_path)
    now = d.index[-1] + pd.Timedelta(minutes=6)
    conn = DB.connect(str(tmp_path / "e.db"))
    state = {"up": False, "got": []}
    def flaky(env, text):
        if state["up"]: state["got"].append(text)
        return state["up"]
    created = d.index[40] + pd.Timedelta(minutes=5)
    loop.run_cycle(conn, {}, now, send=flaky, root=tmp_path, refresh_fn=lambda: None, scan_fn=lambda: [cand(created)])
    assert conn.execute("SELECT COUNT(*) FROM alerts WHERE ok=0").fetchone()[0] >= 2
    state["up"] = True
    loop.run_cycle(conn, {}, now, send=flaky, root=tmp_path, refresh_fn=lambda: None, scan_fn=lambda: [])
    assert conn.execute("SELECT COUNT(*) FROM alerts WHERE ok=0").fetchone()[0] == 0 and len(state["got"]) >= 2


def test_freshness_uses_oldest_pair_and_stale_threshold(tmp_path):
    d = make_store(tmp_path)
    # a second pair that stopped 30 minutes earlier makes the whole feed stale, even though EURUSD is fresh
    store.merge_save("GBPUSD", "M5", d.iloc[:-6], tmp_path)
    now = d.index[-1] + pd.Timedelta(minutes=6)
    assert loop.data_age_min(tmp_path, now) > 30
    conn = DB.connect(str(tmp_path / "e.db"))
    bag = Bag()
    assert loop.run_cycle(conn, {}, now, send=bag, root=tmp_path, refresh_fn=lambda: None, scan_fn=lambda: []) == "STALE"
    # 10 minutes old is fine (threshold 12 min, so one slow fetch does not flip STALE/RECOVERED)
    store.merge_save("GBPUSD", "M5", d, tmp_path)
    assert loop.run_cycle(conn, {}, d.index[-1] + pd.Timedelta(minutes=15), send=bag, root=tmp_path, refresh_fn=lambda: None, scan_fn=lambda: []) == "OK"


def test_error_alerts_at_three_then_every_three_hours_and_recovery(tmp_path):
    make_store(tmp_path)
    conn = DB.connect(str(tmp_path / "e.db"))
    bag = Bag()
    now = T0 + pd.Timedelta(hours=2)

    def boom():
        raise RuntimeError("OANDA HTTP 401")
    for _ in range(loop.ERR_ALERT_EVERY * 2):
        loop.run_cycle(conn, {}, now, send=bag, root=tmp_path, refresh_fn=boom)
    errs = [m for m in bag.msgs if "ENGINE ERROR" in m or "TOKEN REJECTED" in m]
    assert len(errs) == 3 and "x3" in errs[0] and "set_token.sh" in errs[0] and "x72" in errs[-1]
    loop.run_cycle(conn, {}, now, send=bag, root=tmp_path, refresh_fn=lambda: None, scan_fn=lambda: [])
    assert any("RECOVERED" in m for m in bag.msgs)
    assert conn.execute("SELECT status FROM cycles ORDER BY rowid DESC LIMIT 1").fetchone()["status"] == "OK"


def test_scan_result_is_persisted_and_new_alert_carries_reason_and_cancel(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = make_store(tmp_path)
    now = d.index[-1] + pd.Timedelta(minutes=6)
    conn = DB.connect(str(tmp_path / "e.db"))
    bag = Bag()
    c = dict(cand(d.index[40] + pd.Timedelta(minutes=5)), invalidation=1.0995, reason="Strength gap z=+1.7\nStop 2 ATR")
    loop.run_cycle(conn, {}, now, send=bag, root=tmp_path, refresh_fn=lambda: None, scan_fn=lambda: dict(candidates=[c], status="OK"))
    import json
    assert json.load(open(tmp_path / "data" / "latest_scan.json"))["candidates"][0]["pair"] == "EURUSD"
    new = [m for m in bag.msgs if m.startswith("🟢 NEW")][0]
    assert "Strength gap" in new and "cancel if close <= 1.09950" in new and "UNPROVEN" in new and len(new.split("\n")) == 3


def test_halfway_advice_uses_only_bars_closed_at_the_event(tmp_path):
    d = make_store(tmp_path)
    c = dict(cand(d.index[40] + pd.Timedelta(minutes=5)), run_id="x")
    conn = DB.connect(str(tmp_path / "e.db"))
    DB.add_setup(conn, "x", c)
    t, m5 = loop.replay(c, tmp_path)
    at = d.index[60]
    a_event, _ = loop.advice(t, m5, at)
    a_now, _ = loop.advice(t, m5, m5.index[-1] + pd.Timedelta(minutes=5))
    assert a_event in ("HOLD", "EXIT") and a_now in ("HOLD", "EXIT")
    assert loop.advice(t, m5, at) == loop.advice(t, m5.iloc[:70], at)       # later bars change nothing


def test_401_alert_says_exactly_what_to_do_and_audit_reports_longest_silence(tmp_path):
    from fxengine.live import messages as M, db as DB
    from fxengine.audit.run import audit_text
    t = M.engine_error(3, 'RuntimeError: OANDA HTTP 401: {"errorMessage":"Insufficient authorization"}')
    assert "TOKEN REJECTED" in t and "set_token.sh" in t and "Do not create a token anywhere else" in t
    assert "401" not in M.engine_error(3, "KeyError: x") and "ENGINE ERROR" in M.engine_error(3, "KeyError: x")
    conn = DB.connect(str(tmp_path / "e.db"))
    now = pd.Timestamp("2026-11-16 20:00", tz="UTC")
    for ts in ("2026-11-16 12:00", "2026-11-16 12:05", "2026-11-16 17:05", "2026-11-16 17:10"):        # a 5-hour silence
        conn.execute("INSERT INTO cycles VALUES(?,?,?,?,?,?)", (str(pd.Timestamp(ts, tz="UTC")), 1, "OK", 0.5, 1.0, ""))
    conn.commit()
    txt = audit_text(conn, now)
    assert "longest silence 24h 300 min" in txt and len(txt.split("\n")) == 5


def test_halfway_warning_is_sent_as_halfway_not_as_a_second_triggered(tmp_path):
    """Regression (Tue 17 Nov, EURGBP): the halfway event carries to_state TRIGGERED and was sent as a duplicate 'TRIGGERED'."""
    px = np.r_[np.full(60, 1.1000), np.linspace(1.1000, 1.1016, 8), np.linspace(1.1016, 1.1000, 10), np.full(20, 1.1000)]
    idx = pd.date_range(T0, periods=len(px), freq="5min", tz="UTC")
    o = np.r_[px[0], px[:-1]]
    d = pd.DataFrame({"bid_o": o, "bid_h": np.maximum(o, px) + 1e-5, "bid_l": np.minimum(o, px) - 1e-5, "bid_c": px,
                      "ask_o": o + 3e-5, "ask_h": px + 3e-5, "ask_l": px + 3e-5, "ask_c": px + 3e-5, "volume": 1.0}, index=idx)
    store.merge_save("EURUSD", "M5", d, tmp_path)
    store.merge_save("EURUSD", "H1", resample(d, "H1", base="M5"), tmp_path)
    now = d.index[-1] + pd.Timedelta(minutes=6)
    conn = DB.connect(str(tmp_path / "e.db"))
    bag = Bag()
    c = dict(cand(d.index[40] + pd.Timedelta(minutes=5)), stop=1.0990, target=1.1050, entry=1.1010)     # 0.5R adverse = ~1.1001
    for _ in range(3):
        loop.run_cycle(conn, {}, now, send=bag, root=tmp_path, refresh_fn=lambda: None, scan_fn=lambda: [c])
    heads = [m.split(" ·")[0] for m in bag.msgs]
    assert heads == ["🟢 NEW", "▶️ TRIGGERED", "⚠️ HALFWAY"], heads               # exactly ONE triggered, then the halfway warning
    assert "Advice:" in bag.msgs[2] and "HOLD" in bag.msgs[2] + "EXIT"
    assert all(len(m.split("\n")) <= 3 for m in bag.msgs)


def test_main_loop_survives_a_full_iteration_with_the_real_call_signatures(monkeypatch, tmp_path):
    """Regression: a NameError in main() crashed the loop on startup, was invisible to the import pre-check, and was only caught by the deploy rollback."""
    import inspect
    from fxengine.live import loop as L, schedule
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(L, "load_env", lambda: {"OANDA_TOKEN": "x"})
    monkeypatch.setattr(L, "run_cycle", lambda conn, env, now: "OK")
    monkeypatch.setattr(L, "ping", lambda *a, **k: None)
    seen = []
    real_sig = inspect.signature(schedule.daily_jobs)
    monkeypatch.setattr(schedule, "daily_jobs", lambda *a, **k: seen.append(real_sig.bind(*a, **k)))      # raises TypeError on a wrong call

    class Stop(Exception):
        pass

    def stop(_):
        raise Stop()
    monkeypatch.setattr(L.time, "sleep", stop)
    import pytest
    with pytest.raises(Stop):
        L.main()
    assert len(seen) == 1
