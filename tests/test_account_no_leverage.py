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
