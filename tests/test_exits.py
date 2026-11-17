import numpy as np, pandas as pd
from fxengine.backtest import run_exits as X, run_m5 as M
from fxengine.engine.tracker import Setup, bar_arrays


def _arr(rows):
    idx = pd.date_range("2026-01-05 10:00", periods=len(rows), freq="5min", tz="UTC")
    return bar_arrays(pd.DataFrame(rows, index=idx, columns=["bid_o", "bid_h", "bid_l", "bid_c"])), idx


def _setup(idx):
    return Setup(run_id="x", symbol="EURUSD", direction="long", setup_type="t", version="v", created_at=idx[0] - pd.Timedelta(minutes=5),
                 entry=1.1000, entry_kind="stop", stop=1.0980, target=1.1040, expires_at=idx[0] + pd.Timedelta(hours=5), max_hold_bars=200)


PATH = [(1.0999, 1.1004, 1.0998, 1.1002),      # fills on the stop-entry
        (1.1002, 1.1032, 1.1001, 1.1030),      # runs to about +1.5R and closes there
        (1.1030, 1.1031, 1.0970, 1.0975),      # reverses all the way through the original stop
        (1.0975, 1.0976, 1.0970, 1.0972)]


def _track(rule=None):
    arr, idx = _arr(PATH)
    return M.track_m5(_setup(idx), arr, 0, M.COSTS["stressed"], None if rule is None else X.exit_hook(rule, arr))


def test_frozen_exit_gives_back_everything():
    t = _track()
    assert t.outcome.reason == "STOP" and t.outcome.net_r < -0.9


def test_profit_protecting_rules_save_the_reversal_without_closing_at_market():
    base = _track().outcome.net_r
    for rule in X.RULES:
        t = _track(rule)
        assert t.outcome.net_r > base + 1.0, (rule, t.outcome.net_r)          # exits in profit (or at least near break-even) instead of -1R


def test_rule_never_acts_before_the_trade_has_been_1R_ahead():
    arr, idx = _arr([(1.0999, 1.1004, 1.0998, 1.1002), (1.1002, 1.1010, 1.0970, 1.0975)])
    t = M.track_m5(_setup(idx), arr, 0, M.COSTS["stressed"], X.exit_hook("C2_keep_50pc_of_peak", arr))
    assert t.outcome.reason == "STOP" and t.outcome.net_r < -0.9


def test_no_rule_closes_at_market_and_stops_stay_behind_price():
    for rule in X.RULES:
        t = _track(rule)
        assert t.outcome.reason in ("STOP", "TARGET", "TIMEOUT"), (rule, t.outcome.reason)
