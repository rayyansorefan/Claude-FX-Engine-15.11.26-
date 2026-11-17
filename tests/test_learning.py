import json
import numpy as np, pandas as pd
from fxengine.learn import review as LR
from fxengine.live import db as DB


def _seed(conn, n_trades, delta, rule="A2_breakeven_at_1R", start="2026-10-01", exits=None):
    """n finished trades, each with a FROZEN row and a rule row = frozen + delta (+ small noise), on distinct pair-days."""
    rng = np.random.default_rng(0)
    for i in range(n_trades):
        day = pd.Timestamp(start, tz="UTC") + pd.Timedelta(days=i // 2)
        rid = f"r{i}"
        pair = "EURUSD" if i % 2 else "GBPUSD"
        conn.execute("INSERT INTO setups VALUES(?,?,?,?,?,?,?,?)", (rid, str(day), str(day), pair, "asia_breakout", "H1", str(day.date()), json.dumps(dict(pair=pair))))
        base = float(rng.choice([-1.1, 1.9, -1.1]))
        conn.execute("INSERT INTO shadow VALUES(?,?,?)", (rid, "FROZEN", base))
        conn.execute("INSERT INTO shadow VALUES(?,?,?)", (rid, rule, base + delta + float(rng.normal(0, 0.05))))
    conn.commit()


def _exits_json(tmp_path, rule, passes=True):
    p = tmp_path / "exits.json"
    p.write_text(json.dumps(dict(summary=dict(passes=passes, best_on_first_half=rule))))
    return p


def test_nothing_is_promoted_on_too_little_evidence(tmp_path):
    c = DB.connect(tmp_path / "e.db")
    _seed(c, 20, 0.5)
    assert LR.decide(c, pd.Timestamp("2026-11-20", tz="UTC"), _exits_json(tmp_path, "A2_breakeven_at_1R")) == []
    assert DB.kv_get(c, "champion_exit") is None


def test_promotion_needs_both_live_and_history_evidence(tmp_path):
    c = DB.connect(tmp_path / "e.db")
    _seed(c, 80, 0.4)
    assert LR.decide(c, pd.Timestamp("2026-11-20", tz="UTC"), _exits_json(tmp_path, "A2_breakeven_at_1R", passes=False)) == []      # history disagrees
    assert LR.decide(c, pd.Timestamp("2026-11-20", tz="UTC"), _exits_json(tmp_path, "B2_trail_1R_behind_peak")) == []               # history chose another rule
    msgs = LR.decide(c, pd.Timestamp("2026-11-20", tz="UTC"), _exits_json(tmp_path, "A2_breakeven_at_1R"))
    assert msgs and "promoted" in msgs[0] and DB.kv_get(c, "champion_exit") == "A2_breakeven_at_1R"


def test_a_noisy_or_negative_rule_is_never_promoted(tmp_path):
    c = DB.connect(tmp_path / "e.db")
    _seed(c, 80, -0.3)
    assert LR.decide(c, pd.Timestamp("2026-11-20", tz="UTC"), _exits_json(tmp_path, "A2_breakeven_at_1R")) == []


def test_champion_is_rolled_back_when_it_underperforms_and_changes_are_rate_limited(tmp_path):
    c = DB.connect(tmp_path / "e.db")
    DB.kv_set(c, "champion_exit", "A2_breakeven_at_1R"); DB.kv_set(c, "champion_since", "2026-10-01")
    _seed(c, 60, -0.4)
    msgs = LR.decide(c, pd.Timestamp("2026-11-20", tz="UTC"))
    assert msgs and "rolled back" in msgs[0] and DB.kv_get(c, "champion_exit") is None
    _seed2 = LR.decide(c, pd.Timestamp("2026-11-21", tz="UTC"), _exits_json(tmp_path, "A2_breakeven_at_1R"))
    assert _seed2 == []                                                                 # 14-day cool-off after a rollback


def test_shadow_replay_gives_one_row_per_rule_and_frozen_matches_the_ledger(tmp_path):
    from fxengine.data import store
    c = DB.connect(tmp_path / "e.db")
    idx = pd.date_range("2026-11-10 08:00", periods=60, freq="5min", tz="UTC")
    px = np.r_[np.full(6, 1.1000), np.linspace(1.1000, 1.1032, 6), np.linspace(1.1032, 1.0968, 8), np.full(40, 1.0968)]
    m5 = pd.DataFrame(dict(bid_o=px, bid_h=px + 0.0004, bid_l=px - 0.0004, bid_c=px, ask_o=px + 0.0001, ask_h=px + 0.0005, ask_l=px - 0.0003, ask_c=px + 0.0001), index=idx)
    store.merge_save("EURUSD", "M5", m5, tmp_path / "c")
    rec = dict(pair="EURUSD", direction="long", type="trend_pullback", tf="H1", created=str(idx[2]), expires=str(idx[40]), entry=1.1001, stop=1.0980, target=1.1043,
               entry_kind="stop", score=1.0, run_id="r1", reason="t")
    c.execute("INSERT INTO setups VALUES('r1',?,?,?,?,?,?,?)", (rec["created"], rec["expires"], "EURUSD", "trend_pullback", "H1", "2026-11-10", json.dumps(rec)))
    c.execute("INSERT INTO outcomes(run_id,reason,net_r,fill,exit,resolved_at) VALUES('r1','STOP',-1.1,1.1002,1.098,'x')")
    c.commit()
    assert LR.fill_shadow(c, tmp_path / "c") == 1 and LR.fill_shadow(c, tmp_path / "c") == 0     # idempotent
    rows = dict(c.execute("SELECT rule, net_r FROM shadow WHERE run_id='r1'").fetchall())
    assert "FROZEN" in rows and len(rows) == 1 + len(LR.RULES)
    assert max(rows[k] for k in LR.RULES) > rows["FROZEN"] + 0.5            # at least one protective rule rescues the reversal


def test_live_replay_applies_the_exit_rule_stored_in_the_setup_and_alerts_once(tmp_path):
    from fxengine.data import store
    from fxengine.live import loop as L, messages as M
    idx = pd.date_range("2026-11-10 08:00", periods=60, freq="5min", tz="UTC")
    px = np.r_[np.full(6, 1.1000), np.linspace(1.1000, 1.1032, 6), np.linspace(1.1032, 1.0968, 8), np.full(40, 1.0968)]
    m5 = pd.DataFrame(dict(bid_o=px, bid_h=px + 0.0004, bid_l=px - 0.0004, bid_c=px, ask_o=px + 0.0001, ask_h=px + 0.0005, ask_l=px - 0.0003, ask_c=px + 0.0001), index=idx)
    store.merge_save("EURUSD", "M5", m5, tmp_path / "c")
    rec = dict(pair="EURUSD", direction="long", type="trend_pullback", tf="H1", created=str(idx[2]), expires=str(idx[40]), entry=1.1001, stop=1.0980, target=1.1043,
               entry_kind="stop", score=1.0, run_id="r1", reason="t")
    frozen, _ = L.replay(rec, tmp_path / "c")
    ruled, _ = L.replay(dict(rec, exit_rule="A2_breakeven_at_1R"), tmp_path / "c")
    assert frozen.outcome.net_r < -0.9 and ruled.outcome.net_r > frozen.outcome.net_r + 0.5
    adj = [e for e in ruled.events if e["to"] == "ADJUSTED"]
    assert adj and "stop moved" in M.protected(dict(rec, exit_rule="A2"), adj[0]["detail"]).lower()
