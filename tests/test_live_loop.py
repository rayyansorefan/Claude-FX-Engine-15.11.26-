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
