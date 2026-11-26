import json
import pandas as pd
from fxengine.learn import scorecard as SC
from fxengine.live import db as DB, loop, messages as M


def _fill(conn, typ, results, start=0):
    for i, r in enumerate(results):
        rid = f"{typ}-{start + i}"
        rec = dict(pair="GBPUSD", type=typ, tf="H1", direction="long", created=f"2026-11-{1 + (start + i) % 28:02d} 10:00+00:00", expires="2026-12-30 16:00+00:00", entry=1.31, stop=1.308, target=1.314,
                   stop_pips=20.0, lots_for_20gbp_risk=0.01, score=1.0)
        DB.add_setup(conn, rid, rec)
        conn.execute("INSERT INTO outcomes(run_id,reason,net_r,fill,exit,resolved_at) VALUES(?,?,?,?,?,?)", (rid, "TARGET" if r > 0 else "STOP", r, 1.31, 1.31, "2026-11-20T12:00:00+00:00"))
    conn.commit()


def test_status_rules_are_strict_and_a_few_trades_never_switch_anything_off(tmp_path):
    conn = DB.connect(str(tmp_path / "e.db"))
    _fill(conn, "few_bad", [-1.1] * 12)                                        # 12 straight losses: still only LEARNING
    _fill(conn, "mid_bad", [-1.1, -1.0, 0.5, -1.2, -0.9] * 4)                   # 20 trades, clearly poor: WEAK (warning only), not suspended
    _fill(conn, "dead", [-1.1, -1.0, -1.2, -0.9, 0.2, -1.1] * 6)                # 36 trades, range below zero: SUSPENDED
    _fill(conn, "great", [1.9, 1.8, 2.0, 1.7, -1.0, 1.9] * 6)                   # 36 trades, range above zero: CONFIRMED
    _fill(conn, "coin", [1.9, -1.1, 1.8, -1.0, -1.2, 1.7] * 6)                  # 36 trades, range spans zero: NEUTRAL
    sc = SC.scorecard(conn)
    assert sc["few_bad"]["status"] == "LEARNING" and sc["mid_bad"]["status"] == "WEAK" and sc["dead"]["status"] == "SUSPENDED"
    assert sc["great"]["status"] == "CONFIRMED" and sc["coin"]["status"] == "NEUTRAL"
    assert SC.suspended(conn) == {"dead"}
    lines = SC.summary_lines(conn)
    assert len(lines) == 3 and "SCORECARD" in lines[0] and "1 confirmed" in lines[2] and "1 suspended" in lines[2]


def test_a_suspended_strategy_is_still_published_and_scored_but_not_taken_in_the_account(tmp_path):
    conn = DB.connect(str(tmp_path / "e.db"))
    _fill(conn, "dead", [-1.1, -1.0, -1.2, -0.9, 0.2, -1.1] * 6)
    now = pd.Timestamp("2026-12-01 10:00", tz="UTC")
    PX = {"GBPUSD": 1.3126, "EURGBP": 0.86, "AUDUSD": 0.65, "NZDUSD": 0.60}

    def cand(typ, pair):
        return dict(pair=pair, direction="long", type=typ, tf="H1", entry_kind="stop", entry=1.31, stop=1.308, target=1.314, created=str(now), expires=str(now + pd.Timedelta(hours=6)),
                    stop_pips=20.0, lots_for_20gbp_risk=0.01, score=2.0, note="UNPROVEN")
    out = loop.publish(conn, {}, lambda e, t: True, [cand("dead", "GBPUSD"), cand("fresh_strategy", "EURGBP")], now, px=PX)
    recs = {r["type"]: json.loads(r["record"]) for r in conn.execute("SELECT type, record FROM setups WHERE run_id LIKE 'live-%'")}
    assert len(out) == 2                                                                   # both still published (research untouched)
    assert recs["dead"]["suspended"] is True and recs["dead"]["lots_account"] == 0.0
    assert recs["fresh_strategy"].get("suspended") is None and recs["fresh_strategy"]["lots_account"] >= 0.01
    assert "probation" in M.new(recs["dead"]) and len(M.new(recs["dead"]).split("\n")) <= 3


def test_dashboard_shows_the_scorecard_and_the_weekly_note_is_three_lines(tmp_path, monkeypatch):
    from tests.test_live_dashboard import _store
    from fxengine.dashboard import build as B
    monkeypatch.chdir(tmp_path)
    _store(tmp_path / "data" / "candles")
    conn = DB.connect(str(tmp_path / "data" / "engine.db"))
    _fill(conn, "E1_strength", [1.9, -1.1, -1.0] * 6)
    html = B.build(root=tmp_path / "data" / "candles", out=None, now=pd.Timestamp("2026-12-01 10:00", tz="UTC"))
    assert "Strategy scorecard" in html and "95% range" in html and "probation" in html
