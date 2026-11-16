import numpy as np, pandas as pd, pytest
from fxengine.calendar import NY
from fxengine.data.daily import daily_bars_ny
from fxengine.data import rates as R
from fxengine.engine.costs import CostModel
from fxengine.engine.tracker import Setup, track_arrays, bar_arrays
from fxengine.setups import v3
from fxengine.backtest import run_batch3 as B3

FIVE = pd.Timedelta(minutes=5)


def synth_m5(start="2024-01-01", end="2025-08-01", seed=0, drift=0.0, price=1.10):
    """M5 bid/ask candles only while the FX market is open (Sun 17:00 NY -> Fri 17:00 NY, Dec 25 / Jan 1 closed)."""
    idx = pd.date_range(start, end, freq="5min", tz="UTC")
    t = idx.tz_convert(NY)
    d, h = t.day_of_week, t.hour
    closed = (d == 5) | ((d == 4) & (h >= 17)) | ((d == 6) & (h < 17)) | ((t.month == 12) & (t.day == 25)) | ((t.month == 1) & (t.day == 1))
    idx = idx[~np.asarray(closed)]
    rng = np.random.default_rng(seed)
    c = price + np.cumsum(rng.normal(drift, 6e-5, len(idx)))
    o = np.r_[c[0], c[:-1]]
    hi, lo = np.maximum(o, c) + 2e-5, np.minimum(o, c) - 2e-5
    return pd.DataFrame({"bid_o": o, "bid_h": hi, "bid_l": lo, "bid_c": c, "ask_o": o + 1.2e-4, "ask_h": hi + 1.2e-4,
                         "ask_l": lo + 1.2e-4, "ask_c": c + 1.2e-4, "volume": 1.0}, index=idx)


def test_daily_bars_close_at_17_new_york_in_winter_and_summer():
    d = daily_bars_ny(synth_m5())
    ny_close = d.close_time.dt.tz_convert(NY)
    assert (ny_close.dt.hour == 17).all() and (ny_close.dt.minute == 0).all()
    assert set(ny_close.dt.day_of_week) <= {0, 1, 2, 3, 4}                      # Mon..Fri closes only
    assert (d.close_time > d.index.to_series()).all() and d.index.is_monotonic_increasing
    # a summer and a winter bar both exist and both close 17:00 NY although UTC hours differ
    assert {21, 22} <= set(d.close_time.dt.hour)


def test_daily_bars_drop_forming_day_and_ohlc_correct():
    m5 = synth_m5()
    cut = m5.iloc[: len(m5) - 40]                       # chop mid-day: the forming bucket must not appear
    full, part = daily_bars_ny(m5), daily_bars_ny(cut)
    assert part.close_time.max() <= cut.index[-1] + FIVE
    row = full.iloc[10]
    sl = m5[(m5.index >= full.index[10]) & (m5.index < row.close_time)]
    assert row.bid_o == sl.bid_o.iloc[0] and row.bid_c == sl.bid_c.iloc[-1] and row.bid_h == sl.bid_h.max() and row.bid_l == sl.bid_l.min()


def test_rates_parse_gap_report_and_publication_lag():
    csv = "DATE,IR3TIB01USM156N\n2024-01-01,5.30\n2024-02-01,.\n2024-03-01,5.25\n"
    s = R.parse_fred(csv)
    assert len(s) == 2 and s.iloc[0] == 5.30                                         # '.' (missing) is dropped
    df = pd.DataFrame({c: s for c in R.SERIES})
    rep = R.gap_report(df, "2024-01-01", "2024-03-01")
    assert rep["USD"]["missing_months"] == ["2024-02"]
    times = pd.DatetimeIndex(["2024-02-10", "2024-02-20", "2024-04-20"], tz="UTC")
    known = R.rates_known_at(df, times)
    assert np.isnan(known["USD"].iloc[0])                                            # Jan value not yet known on 10 Feb (45d lag)
    assert known["USD"].iloc[1] == 5.30 and known["USD"].iloc[2] == 5.25            # Jan known by 20 Feb; Mar known by 20 Apr
    assert (R.pair_diff("EURUSD", known.assign(EUR=known.USD + 1.5)).iloc[1] == pytest.approx(1.5))


def test_carry_is_earned_or_paid_by_sign_and_old_model_unchanged():
    m5 = synth_m5("2024-03-04", "2024-03-20", price=1.10)
    arr = bar_arrays(m5)
    t0 = m5.index[10] + FIVE

    def setup(direction, carry):
        e = float(m5.bid_c.iloc[10])
        sgn = 1 if direction == "long" else -1
        return Setup("x", "EURUSD", direction, "t", "v", t0, e, "stop", e - sgn * 0.02, e + sgn * 0.5, t0 + pd.Timedelta(hours=72),
                     3000, carry_annual=carry)
    cm = CostModel(False)
    earn = track_arrays(setup("long", +0.03), arr, FIVE, cm, 10, 4000)
    pay = track_arrays(setup("long", -0.03), arr, FIVE, cm, 10, 4000)
    assert earn.outcome.cost_r < pay.outcome.cost_r and earn.outcome.net_r > pay.outcome.net_r
    # without carry_annual the old adverse-swap model applies (cost is positive)
    old = track_arrays(setup("long", None), arr, FIVE, cm, 10, 4000)
    assert old.outcome.cost_r > 0


def test_signals_causal_and_sane():
    d = v3.prep(daily_bars_ny(synth_m5(drift=0.0)))
    k = len(d) - 120
    full, cut = v3.tsmom_signals(d), v3.tsmom_signals(v3.prep(daily_bars_ny(synth_m5(drift=0.0)).iloc[: k + 1]))
    a = full[full.pos <= k - 1].reset_index(drop=True)                               # the last row of `cut` has no future for exit_at
    b = cut[cut.pos <= k - 1].reset_index(drop=True)
    assert len(a) > 2
    pd.testing.assert_frame_equal(a.drop(columns="exit_at"), b.drop(columns="exit_at"), check_dtype=False)
    long = full.direction == "long"
    assert (full.stop[long] < full.entry[long]).all() and (full.stop[~long] > full.entry[~long]).all()
    assert d.close_time.iloc[full.pos].dt.tz_convert(NY).dt.day_of_week.eq(4).all()  # only Friday closes


def test_carry_signal_needs_agreement_and_threshold():
    d = v3.prep(daily_bars_ny(synth_m5(drift=1e-6)))
    up = pd.Series(2.0, index=d.index)
    s_up = v3.carry_mom_signals(d, up)
    assert (s_up.direction == "long").all() and (s_up.carry_annual > 0).all()        # uptrend + positive carry => long, earns carry
    assert len(v3.carry_mom_signals(d, pd.Series(0.5, index=d.index))) == 0         # below the 1.0pp threshold => nothing
    dn = v3.carry_mom_signals(d, pd.Series(-2.0, index=d.index))
    assert (dn.direction == "short").all() if len(dn) else True                       # downtrend + negative diff => short


def test_run_experiment_end_to_end_and_challenger():
    syms = ["EURUSD", "GBPUSD"]
    m5s = {s: synth_m5(seed=i, drift=0.0) for i, s in enumerate(syms)}
    frames = {s: v3.prep(daily_bars_ny(m)) for s, m in m5s.items()}
    sigs = {s: v3.tsmom_signals(frames[s]) for s in syms}
    df, pool = B3.run_experiment("E6_tsmom_daily", frames, m5s, sigs)
    assert len(df) > 3 and df.triggered.mean() > 0.8
    assert len(pool["stressed"]) > 5 and set(pool) == {"stressed", "normal", "measured"}
    res = B3.M.summarise(df, pool, 12)
    assert res["stressed"]["scored"] > 3 and res["measured"]["exp_r"] is not None
