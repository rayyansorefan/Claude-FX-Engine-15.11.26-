import json
from pathlib import Path
import numpy as np, pandas as pd
import pytest
from fxengine.stocks import backtest as B, costs as C, data as D, indicators as I, run as R, strategies as S, universe as U
from fxengine.stocks.strategies import Sig


def _series(n=1500, seed=0, vol=0.015, drift=0.0, start="2012-01-02"):
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, vol, n)
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.003, n))
    hi, lo = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n))), np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame(dict(open=o, high=hi, low=lo, close=c, volume=1e6), index=idx)


def _panel(k=30, n=1500, seed=0, **kw):
    return {f"s{i}.us": _series(n, seed + i, **kw) for i in range(k)}


def test_stooq_csv_parse_and_junk():
    t = "Date,Open,High,Low,Close,Volume\n2024-01-02,10,11,9,10.5,1000\n2024-01-03,10.5,11,10,0,5\n2024-01-04,10.6,11,10,10.8,\n"
    d = D.parse(t)
    assert len(d) == 2 and d.index[0] == pd.Timestamp("2024-01-02") and d["close"].iloc[1] == 10.8       # the zero-close bar is dropped
    assert D.parse("No data").empty and D.parse("").empty and D.parse("<html>blocked</html>").empty


def test_costs_uk_stamp_duty_is_buy_only_and_etfs_are_exempt():
    b, s = C.side_costs("uk", "stressed")
    assert b - s == pytest.approx(0.005) and C.side_costs("uk_etf", "stressed")[0] == C.side_costs("uk_etf", "stressed")[1]
    assert C.net_return(0.0, "uk", "stressed") < -0.01 and C.net_return(0.03, "us", "gross") == pytest.approx(0.03)
    assert U.kind("vod.uk") == "uk" and U.kind("isf.uk") == "uk_etf" and U.kind("spy.us") == "us_etf" and U.kind("aapl.us") == "us"


def test_rsi_extremes_and_no_lookahead_in_indicators():
    assert I.rsi(pd.Series(np.arange(1, 60.0)), 2).iloc[-1] == 100.0 and I.rsi(pd.Series(np.arange(60, 1, -1.0)), 2).iloc[-1] == pytest.approx(0.0, abs=1e-9)
    d = _series(400, 1)
    full, cut = I.sma(d["close"], 50), I.sma(d["close"].iloc[:300], 50)
    assert np.allclose(full.iloc[:300].dropna(), cut.dropna())


def test_trade_timing_signal_at_close_enter_next_open_exit_next_open():
    n = 12
    o = np.arange(100, 100.0 + n)
    ent, ex = np.zeros(n, bool), np.zeros(n, bool)
    ent[2] = ex[5] = True
    assert B.swing_trades(o, Sig(ent, ex, 10), np.zeros(n + 1, int)) == [(2, 3, 6)]
    assert B.swing_trades(o, Sig(ent, np.zeros(n, bool), 4), np.zeros(n + 1, int)) == [(2, 3, 7)]                  # time stop
    e2 = np.zeros(n, bool); e2[9] = True
    assert B.swing_trades(o, Sig(e2, np.zeros(n, bool), 10), np.zeros(n + 1, int)) == []                            # still open at the end: not scored


def test_bars_with_probable_data_errors_drop_the_trade():
    d = _series(600, 5)
    d.iloc[320:, :4] *= 2.0                                                                                       # an unadjusted 2x jump at bar 320
    sig = S.Sig(np.isin(np.arange(600), [300]), np.zeros(600, bool), 40)
    assert B.trades_for("x.us", d, sig).empty                                                                      # the trade holds across the jump -> dropped


@pytest.mark.parametrize("rule", list(S.BAR_RULES))
def test_signals_never_use_future_prices(rule):
    d = _series(900, 2)
    base = S.BAR_RULES[rule](d)
    d2 = d.copy()
    d2.iloc[600:, :4] *= np.random.default_rng(9).uniform(0.7, 1.4, size=(300, 4))                                 # rewrite the future
    chg = S.BAR_RULES[rule](d2)
    assert (base.entry[:600] == chg.entry[:600]).all() and (base.exit[:600] == chg.exit[:600]).all()


def test_momentum_ranking_uses_only_the_past():
    p = _panel(25, 700, 3)
    a = S.momentum_entries(p)
    q = {s: d.copy() for s, d in p.items()}
    for d in q.values():
        d.iloc[500:, :4] *= 1.5
    b = S.momentum_entries(q)
    cut = 480
    assert all((a[s][:cut] == b[s][:cut]).all() for s in p)


def _run(panel, tmp_path, hold_days=365):
    rows = []
    for s, d in panel.items():
        rows.append(d.reset_index().rename(columns={"index": "date"}).assign(symbol=s))
    pq = tmp_path / "prices.parquet"
    pd.concat(rows).to_parquet(pq)
    return R.main(pq, tmp_path / "res", tmp_path / "trials.jsonl")


def test_a_random_walk_market_produces_no_edge_after_costs(tmp_path):
    res = _run(_panel(40, 2500, 11), tmp_path)
    assert not any(r.get("passes") for r in res["rules"])
    for r in res["rules"]:
        if "roi" in r:
            assert abs(r["roi"]) < 0.006 and r["net_stressed"] < r["roi"]                    # no price edge in a random walk; costs only ever subtract


def test_a_planted_mean_reversion_edge_is_found(tmp_path):
    p = {}
    for i in range(40):
        d = _series(2500, 100 + i, vol=0.012)
        c = d["close"].to_numpy().copy()
        r = np.r_[0, np.diff(np.log(c))]
        for t in range(210, len(r) - 5):                    # after a sharp 2-day drop, bounce +2%/day for 3 days (a real price edge)
            if r[t] + r[t - 1] < -0.025:
                r[t + 1: t + 4] += 0.02
        c2 = 100 * np.exp(np.cumsum(r))
        d = d.assign(close=c2, open=np.r_[c2[0], c2[:-1]], high=c2 * 1.004, low=c2 * 0.996)
        p[f"s{i}.us"] = d
    res = _run(p, tmp_path)
    rsi = next(r for r in res["rules"] if r["rule"] == "RSI2_PULLBACK")
    assert rsi["roi"] > 0.01 and rsi["passes"], rsi


def test_results_files_and_trial_registry_are_written(tmp_path):
    _run(_panel(20, 1800, 4), tmp_path)
    assert (tmp_path / "res" / "stocks.md").exists() and (tmp_path / "res" / "stocks.json").exists()
    assert len((tmp_path / "trials.jsonl").read_text().splitlines()) == 6


def test_scanner_lists_todays_setup_then_tracks_it_through_to_invalidation():
    from fxengine.stocks import scan
    rng = np.random.default_rng(5)
    d = _series(500, 8, vol=0.01, drift=0.0008)                       # a gentle uptrend (RSI2 needs close > 200-day average)
    c = d["close"].to_numpy().copy()
    c[-3:] = c[-4] * np.array([0.975, 0.955, 0.94])                   # three hard down days at the end -> RSI(2) oversold on the last bar
    d = d.assign(close=c, open=np.r_[c[0], c[:-1]], high=c * 1.003, low=c * 0.997)
    panel = {"aaa.us": d}
    rows = scan.run(panel, set(), [])
    s = next(r for r in rows if r["rule"] == "RSI2_PULLBACK")
    assert s["symbol"] == "aaa.us" and s["status"] == "PENDING" and s["proven"] is False and s["invalidation"] is not None
    # two days later: a recovery above the 5-day average -> exit signal; a collapse below the invalidation level -> invalidated
    def extend(closes):
        idx = pd.bdate_range(d.index[-1] + pd.offsets.BDay(1), periods=len(closes))
        e = pd.DataFrame(dict(open=np.r_[c[-1], closes[:-1]], high=np.array(closes) * 1.003, low=np.array(closes) * 0.997, close=closes, volume=1e6), index=idx)
        return pd.concat([d, e])
    up = scan.recheck(s, {"aaa.us": extend([c[-1] * 1.04, c[-1] * 1.07])})
    assert up["status"] == "EXIT SIGNAL" and up["unrealised"] > 0
    down = scan.recheck(s, {"aaa.us": extend([c[-1] * 0.8, c[-1] * 0.7])})
    assert down["status"] == "INVALIDATED"
    again = scan.run(panel, set(), rows)                                # re-running never duplicates a setup
    assert len([r for r in again if r["id"] == s["id"]]) == 1


def test_dashboard_shows_only_real_results_and_the_setups_tab():
    from fxengine.stocks import dashboard as DB
    assert "No results yet" in DB.render(None) and "No setups yet" in DB.render(None) and "<script src" not in DB.render(None)
    res = dict(n_trials=6, symbols=40, window="2012-01-02..2025-01-01", benchmarks=dict(spy_cagr=0.1), rules=[
        dict(rule="RSI2_PULLBACK", n=900, weeks=300, hit_rate=0.55, avg_hold=4.0, gross=0.004, net_normal=0.002, net_stressed=-0.001, roi=0.004, ci95_lo=-0.001, ci95_hi=0.009, mde=0.005,
             challenger_p95=0.001, real_pct=96.0, halves=dict(first=0.005, second=0.003), by_market=dict(US=0.005, UK=0.001), by_year={}, gates=dict(weeks=True, lower_bound=False, beats_random=True, both_halves=True), passes=False, day_trade=False),
        dict(rule="MOM_12_1", n=10, verdict="too few trades")])
    sp = dict(asof="2026-11-17", setups=[dict(id="a", rule="RSI2_PULLBACK", symbol="aapl.us", market="US", signal_date="2026-11-17", close=190.5, invalidation=170.0, strength=95.0,
                                              exit_text="sell the open after a close above its 5-day average", proven=False, status="PENDING")])
    h = DB.render(res, sp)
    assert all(x in h for x in ("STOCKS ENGINE", "NO EDGE FOUND", "AAPL", "UNPROVEN", "Short-term pullback", "too few trades", "Buy &amp; hold SPY"))


def test_stocks_server_renders_and_refreshes_itself(tmp_path, monkeypatch):
    import threading, urllib.request
    from fxengine.stocks import serve
    monkeypatch.chdir(tmp_path)
    serve.AUTO[0] = 60
    srv = serve.ThreadingHTTPServer(("127.0.0.1", 0), serve.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    h = urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/").read().decode()
    srv.shutdown()
    assert "STOCKS ENGINE" in h and "http-equiv='refresh' content='60'" in h and "No results yet" in h


def _yahoo_json(n=300, start="2020-01-02"):
    idx = pd.bdate_range(start, periods=n)
    ts = [int(x.timestamp()) for x in idx]
    px = [100 + i * 0.1 for i in range(n)]
    px[5] = None                                                           # Yahoo leaves holes: they must be dropped
    return json.dumps({"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [{"open": px, "high": px, "low": px, "close": px, "volume": [1000] * n}]}}], "error": None}})


def test_yahoo_json_becomes_the_same_table_as_stooq_csv():
    csv = D.parse_yahoo(_yahoo_json())
    d = D.parse(csv)
    assert len(d) == 299 and d["close"].iloc[0] == 100.0 and csv.startswith("Date,Open,High,Low,Close,Volume")
    assert D.parse_yahoo("{}") == "" and D.parse_yahoo("not json") == "" and D.yahoo_ticker("vod.uk") == "VOD.L" and D.yahoo_ticker("aapl.us") == "AAPL"


def test_downloader_falls_back_to_yahoo_when_stooq_returns_nothing(tmp_path):
    class R:
        def __init__(s, c, t=""): s.status_code, s.content = c, t.encode()
    calls = []
    def get(u):
        calls.append(u)
        return R(200, "") if "stooq" in u else R(200, _yahoo_json())
    df = D.download(tmp_path, symbols=["aapl.us", "vod.uk"], get=get, pause=0)
    assert set(df["symbol"]) == {"aapl.us", "vod.uk"} and any("query1.finance.yahoo.com" in u and "VOD.L" in u for u in calls)
    n = len(calls)
    D.download(tmp_path, symbols=["aapl.us", "vod.uk"], get=get, pause=0)             # second run: cached files are reused, only the probe goes out
    assert len(calls) <= n + 1


def _yahoo_json_freq(freq, n):
    idx = pd.date_range("1990-01-01", periods=n, freq=freq)
    ts = [int(x.timestamp()) for x in idx]
    px = [100 + i * 0.1 for i in range(n)]
    return json.dumps({"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [{"open": px, "high": px, "low": px, "close": px, "volume": [1000] * n}]}}], "error": None}})


def test_monthly_bars_are_rejected_and_a_cached_monthly_file_is_refetched(tmp_path):
    monthly, daily = _yahoo_json_freq("MS", 400), _yahoo_json()
    assert not D.is_daily(D.parse(D.parse_yahoo(monthly))) and D.is_daily(D.parse(D.parse_yahoo(daily)))

    class R:
        def __init__(s, c, t=""): s.status_code, s.content = c, t.encode()
    state = {"bad": True}

    def get(u):
        if "stooq" in u:
            return R(200, "")
        return R(200, monthly if state["bad"] else daily)
    with pytest.raises(SystemExit):                                        # only monthly data on offer -> nothing is accepted
        D.download(tmp_path, symbols=["aapl.us"], get=get, pause=0)
    (tmp_path / "raw").mkdir(exist_ok=True)
    (tmp_path / "raw" / "aapl.us.csv").write_text(D.parse_yahoo(monthly))  # a monthly file left in the cache by the old code
    for m in (tmp_path / "raw").glob("*.missing"):
        m.unlink()
    state["bad"] = False
    df = D.download(tmp_path, symbols=["aapl.us"], get=get, pause=0)       # the cached monthly file is not trusted; a daily one replaces it
    assert D.is_daily(df.set_index("date"))


def test_yahoo_request_uses_explicit_dates():
    assert "period1=" in D.YAHOO and "period2={now}" in D.YAHOO and "range=max" not in D.YAHOO


def test_only_a_real_404_is_remembered_and_other_failures_are_retried(tmp_path):
    class R:
        def __init__(s, c, t=""): s.status_code, s.content = c, t.encode()
    mode = {"m": "bad"}

    def get(u):
        if "stooq" in u:
            return R(200, "")
        return R(200, "{}") if mode["m"] == "bad" else R(200, _yahoo_json())
    with pytest.raises(SystemExit):
        D.download(tmp_path, symbols=["aapl.us"], get=get, pause=0)
    assert not list((tmp_path / "raw").glob("*.missing"))                  # an unusable reply leaves no stamp
    mode["m"] = "good"
    assert len(D.download(tmp_path, symbols=["aapl.us"], get=get, pause=0)) > 250      # so the next run tries again and succeeds
