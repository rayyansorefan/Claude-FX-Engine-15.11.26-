import json
import pandas as pd
from fxengine.learn import reinforce as RF
from fxengine.live import db as DB


def _trades(conn, typ, results, start=0):
    for i, r in enumerate(results):
        rid = f"{typ}-{start + i}"
        conn.execute("INSERT INTO setups VALUES(?,?,?,?,?,?,?,?)", (rid, "2026-11-20T09:00:00+00:00", "x", "EURUSD", typ, "H1", "2026-11-20", "{}"))
        conn.execute("INSERT INTO outcomes(run_id,reason,net_r,fill) VALUES(?,?,?,1.0)", (rid, "TARGET" if r > 0 else "STOP", r))
    conn.commit()


def test_history_is_the_starting_point_and_live_results_move_the_weight(tmp_path):
    c = DB.connect(tmp_path / "e.db")
    w0 = RF.weights(c)
    assert abs(w0["asia_breakout"]["w"] - RF.PRIOR["asia_breakout"][0]) < 1e-9 and w0["E1_strength"]["action"] == "NORMAL"      # -0.055 is just under the favoured line
    _trades(c, "asia_breakout", [1.9, 1.9, 1.9, -1.1, 1.9, -1.1])                                                               # a good run lifts it
    _trades(c, "trend_pullback", [-1.1] * 6)                                                                                    # six straight losses on top of -0.15R history pull it down
    w = RF.weights(c)
    assert w["asia_breakout"]["w"] > w0["asia_breakout"]["w"] and w["asia_breakout"]["action"] == "FAVOURED"
    assert w["trend_pullback"]["w"] < w0["trend_pullback"]["w"] and w["trend_pullback"]["action"] == "REDUCED"
    assert RF.size_factor(w, "trend_pullback") == 0.5 and RF.size_factor(w, "asia_breakout") == 1.0


def test_many_live_losses_take_a_strategy_out_of_the_account_but_it_is_reversible(tmp_path):
    c = DB.connect(tmp_path / "e.db")
    _trades(c, "trend_pullback", [-1.1] * 20)
    assert RF.weights(c)["trend_pullback"]["action"] == "NOT TAKEN" and RF.size_factor(RF.weights(c), "trend_pullback") == 0.0
    _trades(c, "trend_pullback", [1.9] * 40, start=100)                                                                        # a recovery brings it back
    assert RF.weights(c)["trend_pullback"]["action"] in ("NORMAL", "FAVOURED")


def test_candidates_are_ordered_by_weight_then_score_and_never_by_a_missing_type(tmp_path):
    c = DB.connect(tmp_path / "e.db")
    w = RF.weights(c)
    cands = [dict(type="trend_pullback", score=9.0), dict(type="E1_strength", score=1.0), dict(type="mystery", score=5.0)]
    assert [x["type"] for x in sorted(cands, key=lambda x: RF.order_key(w, x))] == ["E1_strength", "mystery", "trend_pullback"]


def test_nightly_announces_only_changes_and_logs_them(tmp_path):
    c = DB.connect(tmp_path / "e.db")
    now = pd.Timestamp("2026-11-27 21:20", tz="UTC")
    first = RF.nightly(c, now)                                            # first night: announces the starting position once
    assert len(first) == 1 and first[0].startswith("🧭 REINFORCEMENT")
    _trades(c, "trend_pullback", [-1.1] * 6)
    msgs = RF.nightly(c, now + pd.Timedelta(days=1))
    assert len(msgs) == 1 and "trend_pullback NORMAL → REDUCED" in msgs[0]
    assert RF.nightly(c, now + pd.Timedelta(days=2)) == []                # no change, no message
    assert c.execute("SELECT COUNT(*) FROM learning_log WHERE kind='REINFORCE'").fetchone()[0] == 1


def test_publisher_orders_by_weight_and_halves_reduced_strategies(tmp_path, monkeypatch):
    from fxengine.live import loop as L
    c = DB.connect(tmp_path / "e.db")
    now = pd.Timestamp("2026-11-27 10:00", tz="UTC")
    fake = {"trend_pullback": dict(w=-0.25, action="REDUCED"), "E1_strength": dict(w=-0.03, action="FAVOURED")}
    monkeypatch.setattr(RF, "weights", lambda conn, prior=None: fake)

    def cand(pair, typ, score):
        return dict(pair=pair, type=typ, tf="H1", direction="long", entry_kind="stop", entry=1.1, stop=1.09, target=1.12, created=str(now), expires=str(now + pd.Timedelta(hours=8)),
                    stop_pips=100, lots_for_20gbp_risk=0.2, per_lot_gbp=100.0, score=score, reason="r")
    out = L.publish(c, {}, lambda *a: True, [cand("EURUSD", "trend_pullback", 9.0), cand("GBPUSD", "E1_strength", 1.0)], now, px={p: 1.1 for p in L.SC.PAIRS})
    assert [x["type"] for x in out] == ["E1_strength", "trend_pullback"]                          # weight beats raw score
    tp = next(x for x in out if x["type"] == "trend_pullback")
    assert tp["reinforce"] == "REDUCED" and 0 < tp["lots_account"] <= 0.1 + 1e-9                  # at most half of the 0.2-lot risk size
    fake["trend_pullback"] = dict(w=-0.4, action="NOT TAKEN")
    out2 = L.publish(c, {}, lambda *a: True, [cand("USDJPY", "trend_pullback", 9.0)], now, px={p: 1.1 for p in L.SC.PAIRS})
    assert out2[0]["lots_account"] == 0.0 and out2[0]["suspended"]                                # still published and scored, not taken
