"""Monitor progress toward decision thresholds."""
import pytest
from fxengine.learn import monitor as MON, scorecard as SCORE


def test_progress_empty(conn):
    """No trades yet."""
    prog = MON.progress(conn)
    assert prog == {}


def test_progress_accumulating(conn):
    """Strategies accumulating trades, tracking to thresholds."""
    # Add 12 trades to asia_breakout
    for i in range(12):
        conn.execute("INSERT INTO setups(day,type,pair,record) VALUES(?,?,?,'{}')", ("2026-01-01", "asia_breakout", "EURUSD"))
        setup_id = conn.lastrowid
        conn.execute("INSERT INTO outcomes(run_id,reason,net_r) VALUES(?,?,?)", (f"live-asia_breakout-EURUSD-202601011000", "TARGET", -0.1))

    prog = MON.progress(conn)
    asia = prog["asia_breakout"]
    assert asia["n"] == 12
    assert asia["to_judge"] == 3  # Need 15 for LEARNING → JUDGMENT
    assert asia["to_decide"] == 18  # Need 30 for decision
    assert asia["current_status"] == "LEARNING"


def test_progress_at_decision_point(conn):
    """At 30 trades, decision point is reached."""
    # Add 30 trades to trend_pullback
    for i in range(30):
        net_r = 0.05 if i < 20 else -0.15  # 20 wins, 10 losses = positive mean
        conn.execute("INSERT INTO setups(day,type,pair,record) VALUES(?,?,?,'{}')", ("2026-01-01", "trend_pullback", "GBPUSD"))
        conn.execute("INSERT INTO outcomes(run_id,reason,net_r) VALUES(?,?,?)", (f"live-trend_pullback-GBPUSD-{i:04d}", "TARGET", net_r))

    prog = MON.progress(conn)
    trend = prog["trend_pullback"]
    assert trend["n"] == 30
    assert trend["to_judge"] == 0
    assert trend["to_decide"] == 0
    assert trend["current_status"] in ("NEUTRAL", "CONFIRMED")


def test_summary_text_no_trades(conn):
    """Summary when no trades yet."""
    text = MON.summary_text(conn)
    assert "No live trades yet" in text or "Learning begins at 15 trades" in text


def test_summary_text_mixed(conn):
    """Summary with multiple strategies at different stages."""
    # 10 trades to strategy A (before judgment)
    for i in range(10):
        conn.execute("INSERT INTO setups(day,type,pair,record) VALUES(?,?,?,'{}')", ("2026-01-01", "asia_breakout", "EURUSD"))
        conn.execute("INSERT INTO outcomes(run_id,reason,net_r) VALUES(?,?,?)", (f"a{i}", "TARGET", 0.0))

    # 25 trades to strategy B (approaching decision)
    for i in range(25):
        net_r = 0.1 if i < 15 else -0.1
        conn.execute("INSERT INTO setups(day,type,pair,record) VALUES(?,?,?,'{}')", ("2026-01-01", "trend_pullback", "GBPUSD"))
        conn.execute("INSERT INTO outcomes(run_id,reason,net_r) VALUES(?,?,?)", (f"b{i}", "TARGET", net_r))

    text = MON.summary_text(conn)
    assert "LEARNING PIPELINE PROGRESS" in text
    assert "asia_breakout" in text
    assert "trend_pullback" in text
    assert "need" in text  # "need X more"
