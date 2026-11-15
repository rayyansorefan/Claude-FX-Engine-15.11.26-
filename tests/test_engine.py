import numpy as np, pandas as pd, pytest
from fxengine.engine.costs import CostModel, rollover_nights, pip
from fxengine.engine.tracker import Setup, Bar, Tracker, run_setup, RESOLVED
from fxengine.research import stats, split, trials

TF = pd.Timedelta(minutes=15)
T0 = pd.Timestamp("2025-01-06 08:00", tz="UTC")
FREE = CostModel(stressed=False)


def setup(direction="long", entry=1.1000, stop=1.0990, target=1.1020, kind="limit", **kw):
    d = dict(run_id="r1", symbol="EURUSD", direction=direction, setup_type="t", version="v1",
             created_at=T0, entry=entry, entry_kind=kind, stop=stop, target=target,
             expires_at=T0 + pd.Timedelta(hours=2), max_hold_bars=8)
    d.update(kw)
    return Setup(**d)


def bars(rows):  # rows of (o,h,l,c) bid, starting at T0
    idx = pd.date_range(T0, periods=len(rows), freq="15min")
    return pd.DataFrame(rows, columns=["bid_o", "bid_h", "bid_l", "bid_c"], index=idx)


def test_bar_before_creation_is_ignored():
    # first bar opens at T0 and closes T0+15m: usable. A bar closing <= created_at is not.
    t = Tracker(setup(), FREE)
    assert t.on_bar(Bar(T0 - TF, T0, 1.1, 1.1, 1.0, 1.1)) == []


def test_long_limit_target_with_executable_prices():
    # bar0 dips to entry (ask low = bid low + spread); bar1 rallies to target
    t = run_setup(setup(), bars([(1.1010, 1.1012, 1.0997, 1.1005), (1.1005, 1.1022, 1.1004, 1.1020)]), TF, FREE)
    o = t.outcome
    assert o.reason == "TARGET" and o.fill == 1.1000
    assert o.gross_r == pytest.approx(2.0)
    assert o.net_r < o.gross_r                      # commission is charged
    assert [e["to"] for e in t.events][:2] == ["PUBLISHED", "TRIGGERED"]


def test_spread_matters_long_entry_needs_ask_touch():
    # bid low 1.1000 touches entry on BID, but ask low = 1.1000+0.00003*... > entry => NOT filled when spread>0
    b = bars([(1.1010, 1.1012, 1.1000, 1.1005)])
    assert run_setup(setup(), b, TF, FREE).state == "PUBLISHED"
    assert run_setup(setup(), bars([(1.1010, 1.1012, 1.0996, 1.1005)]), TF, FREE).state != "PUBLISHED"


def test_stop_beats_target_same_bar_and_entry_bar_only_stop():
    t = run_setup(setup(), bars([(1.1010, 1.1030, 1.0985, 1.1005)]), TF, FREE)
    assert t.outcome.reason == "STOP"
    # entry bar that only hits target must NOT resolve at target
    t2 = run_setup(setup(), bars([(1.1010, 1.1030, 1.0997, 1.1025)]), TF, FREE)
    assert t2.outcome is None or t2.outcome.reason != "TARGET"


def test_short_uses_ask_for_exit_and_stop_slippage_stressed():
    s = setup("short", entry=1.1000, stop=1.1010, target=1.0980)
    b = bars([(1.0995, 1.1002, 1.0994, 1.0996), (1.0996, 1.1012, 1.0995, 1.1008)])
    o_free = run_setup(s, b, TF, FREE).outcome
    o_str = run_setup(s, b, TF, CostModel(stressed=True)).outcome
    assert o_free.reason == o_str.reason == "STOP"
    assert o_str.net_r < o_free.net_r < 0


def test_expiry_and_invalidation_and_no_trade_r_is_zero():
    s = setup(expires_at=T0 + pd.Timedelta(minutes=30))
    far = [(1.1050, 1.1060, 1.1040, 1.1055)] * 4
    t = run_setup(s, bars(far), TF, FREE)
    assert t.outcome.reason in ("EXPIRED", "INVALIDATED") and t.outcome.net_r == 0
    inv = setup(invalidation=1.1030)
    t = run_setup(inv, bars([(1.1040, 1.1045, 1.1032, 1.1025)]), TF, FREE)
    assert t.outcome.reason == "INVALIDATED"


def test_timeout_and_halfway_event_once():
    s = setup(max_hold_bars=3)
    rows = [(1.1005, 1.1008, 1.0996, 1.1002), (1.1002, 1.1006, 1.0994, 1.1000)] + [(1.1000, 1.1005, 1.0995, 1.1001)] * 4
    t = run_setup(s, bars(rows), TF, FREE)
    assert t.outcome.reason == "TIMEOUT"
    assert sum("HALFWAY" in e["detail"] for e in t.events) == 1


def test_live_incremental_equals_batch_replay():
    rng = np.random.default_rng(1)
    p = 1.1000 + np.cumsum(rng.normal(0, 4e-4, 40))
    rows = [(a, a + 3e-4, a - 3e-4, a + rng.normal(0, 1e-4)) for a in p]
    df = bars(rows)
    for kind in ("limit", "stop"):
        s = setup(kind=kind, expires_at=T0 + pd.Timedelta(hours=9))
        batch = run_setup(s, df, TF, CostModel())
        live = Tracker(s, CostModel())                      # fed bar by bar, as in live
        for ot, r in df.iterrows():
            live.on_bar(Bar(ot, ot + TF, r.bid_o, r.bid_h, r.bid_l, r.bid_c))
        assert batch.events == live.events and batch.outcome == live.outcome


def test_rollover_nights_wednesday_triple_and_weekend():
    mon = pd.Timestamp("2025-01-06 10:00", tz="UTC")
    assert rollover_nights(mon, mon + pd.Timedelta(days=1)) == 1                  # Mon night
    assert rollover_nights(pd.Timestamp("2025-01-08 10:00", tz="UTC"), pd.Timestamp("2025-01-08 23:00", tz="UTC")) == 3   # Wed
    assert rollover_nights(pd.Timestamp("2025-01-11 01:00", tz="UTC"), pd.Timestamp("2025-01-12 23:00", tz="UTC")) == 0   # Sat/Sun


def test_stats_bootstrap_and_gate_b():
    rng = np.random.default_rng(0)
    good = rng.normal(0.3, 1.0, 400)
    assert stats.gate_b(good, 100)["pass"]
    assert not stats.gate_b(good[:50], 100)["pass"]                              # too few setups
    noise = rng.normal(0.0, 1.0, 400)
    assert not stats.gate_b(noise, 100)["pass"]
    # multiple-testing penalty makes a marginal edge fail
    marginal = rng.normal(0.12, 1.0, 400)
    assert stats.gate_b(marginal, 100, n_trials=1)["alpha_used"] > stats.gate_b(marginal, 100, n_trials=50)["alpha_used"]
    assert stats.monte_carlo_drawdown(good, n=200)[1] >= stats.monte_carlo_drawdown(good, n=200)[0]


def test_holdout_hidden_and_opens_once(tmp_path):
    idx = pd.date_range("2026-05-01", "2026-06-01", freq="D", tz="UTC")
    df = pd.DataFrame({"x": 1}, index=idx)
    assert split.research_view(df).index.max() < split.HOLDOUT_START
    log = tmp_path / "log.txt"
    assert len(split.open_holdout(df, "test", log)) > 0
    with pytest.raises(RuntimeError):
        split.open_holdout(df, "again", log)


def test_walk_forward_no_overlap_and_clipped():
    w = split.walk_forward_windows("2023-01-01", "2026-11-01", 180, 30)
    assert all(w[i][2] <= w[i + 1][2] and w[i][1] < w[i][2] for i in range(len(w) - 1))
    assert all(c <= split.HOLDOUT_START for _, _, c in w)
    assert all(w[i][2] - w[i][1] == pd.Timedelta(days=30) for i in range(len(w)))


def test_trial_registry(tmp_path):
    reg = tmp_path / "t.jsonl"
    assert trials.log_trial("a", {"x": 1}, reg=reg) == 1 and trials.log_trial("b", {"x": 2}, reg=reg) == 2
