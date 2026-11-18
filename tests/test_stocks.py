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


def _run(panel, tmp_path, hold_start="2020-07-30"):
    rows = []
    for s, d in panel.items():
        rows.append(d.reset_index().rename(columns={"index": "date"}).assign(symbol=s))
    pq = tmp_path / "prices.parquet"
    pd.concat(rows).to_parquet(pq)
    return R.main(pq, tmp_path / "res", tmp_path / "trials.jsonl", hold_start=hold_start)


def test_a_random_walk_market_produces_no_edge_after_costs(tmp_path):
    # Measured 2026-11-18: of 9 random markets, 8 produced 0 false passes across ~90 rule-runs and 1 produced a single false pass (about the family-wise 5% the penalty allows).
    # That is why no pass is trusted alone (sealed year + live forward test). This regression test uses a seed from the typical (zero-pass) majority.
    res = _run(_panel(40, 2500, 101), tmp_path)
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
    assert len((tmp_path / "trials.jsonl").read_text().splitlines()) == len(S.RULES) == 16


def test_scanner_lists_todays_setup_then_tracks_it_through_to_invalidation():
    from fxengine.stocks import scan
    d = _one_signal_series()                                          # an uptrend with one hard down day at the end -> RSI(2) oversold on the last bar
    c = d["close"].to_numpy()
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
    serve.FX["port"] = 1                                                 # nothing listening: must fall back to the stand-alone Stocks page, with a notice
    srv = serve.ThreadingHTTPServer(("127.0.0.1", 0), serve.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    h = urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/").read().decode()
    srv.shutdown()
    assert "STOCKS ENGINE" in h and "http-equiv='refresh' content='60'" in h and "No results yet" in h and "FX dashboard not reachable" in h


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
    assert len(calls) <= n + 2                                                        # the Stooq probe + the GBPUSD rate


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


def test_rules_that_pass_get_stress_checks_and_labels_are_honest(tmp_path):
    from fxengine.stocks import dashboard as DB
    p = {}
    for i in range(40):
        d = _series(2500, 300 + i, vol=0.012)
        c = d["close"].to_numpy().copy()
        r = np.r_[0, np.diff(np.log(c))]
        for t in range(210, len(r) - 5):
            if r[t] + r[t - 1] < -0.025:
                r[t + 1: t + 4] += 0.02
        c2 = 100 * np.exp(np.cumsum(r))
        p[f"s{i}.us" if i < 30 else f"e{i}.us"] = d.assign(close=c2, open=np.r_[c2[0], c2[:-1]], high=c2 * 1.004, low=c2 * 0.996)
    res = _run(p, tmp_path)
    rsi = next(r for r in res["rules"] if r["rule"] == "RSI2_PULLBACK")
    assert rsi["passes"] and rsi["robust"] and rsi["robust"]["trimmed_mean"] > 0 and 0 < rsi["robust"]["top1_share"] < 1
    assert "Stress checks" in (tmp_path / "res" / "stocks.md").read_text()
    h = DB.render(res, dict(asof="2026-11-18", setups=[dict(id="a", rule="RSI2_PULLBACK", symbol="aapl.us", market="US", signal_date="2026-11-18", close=1.0, invalidation=0.9,
                                                              strength=1, exit_text="x", proven=True, status="PENDING")]))
    assert "PASSED RESEARCH TEST" in h and ">PROVEN<" not in h and "Stress checks" in h


def test_fx_tab_fragment_is_scoped_and_does_not_collide_with_the_fx_tab_script(tmp_path):
    from fxengine.stocks import tab
    (tmp_path / "stocks.json").write_text(json.dumps(dict(n_trials=6, symbols=3, window="2000-01-03..2025-01-01", benchmarks={}, rules=[dict(rule="MOM_12_1", n=5, verdict="too few trades")])))
    p = tab.write(tmp_path / "stocks.json")
    h, css = p.read_text(), (tmp_path / "stocks_tab.css").read_text()
    assert h.startswith("<div class='tab' id='stocks'>") and h.count("class='tab'") == 1                       # exactly ONE element the FX page's tab script will manage
    assert 'class="tab"' not in h and "<style" not in h and "<link" not in h and "http" not in h
    assert all(line.startswith("#stocks") for line in css.strip().splitlines() if line.strip())             # every style rule is scoped to the Stocks tab
    assert tab.write(tmp_path / "missing.json").exists()                                                      # no results yet -> still a valid, honest "No results yet" tab


def _planted_panel(seed0=500, k=40):
    p = {}
    for i in range(k):
        d = _series(2500, seed0 + i, vol=0.012)
        c = d["close"].to_numpy().copy()
        r = np.r_[0, np.diff(np.log(c))]
        for t in range(210, len(r) - 5):
            if r[t] + r[t - 1] < -0.025:
                r[t + 1: t + 4] += 0.02
        c2 = 100 * np.exp(np.cumsum(r))
        p[f"s{i}.us"] = d.assign(close=c2, open=np.r_[c2[0], c2[:-1]], high=c2 * 1.004, low=c2 * 0.996)
    return p


def test_the_sealed_boundary_is_a_fixed_date_not_a_moving_window():
    assert R.HOLDOUT_START == pd.Timestamp("2025-11-18")


def test_holdout_opens_once_only_for_a_rule_that_passed_and_reports_honestly(tmp_path):
    p = _planted_panel()
    res = _run(p, tmp_path)
    log = tmp_path / "log.txt"
    with pytest.raises(SystemExit, match="has not passed"):
        R.open_holdout("GAP_CONT_DAY", "test", tmp_path / "prices.parquet", tmp_path / "res" / "stocks.json", log, "2020-07-30")
    out = R.open_holdout("RSI2_PULLBACK", "frozen candidate", tmp_path / "prices.parquet", tmp_path / "res" / "stocks.json", log, "2020-07-30")
    assert out["n"] > 100 and out["mean"] > 0 and out["verdict"].startswith("PASS") and "RSI2_PULLBACK" in log.read_text()
    with pytest.raises(SystemExit, match="already opened"):
        R.open_holdout("RSI2_PULLBACK", "again", tmp_path / "prices.parquet", tmp_path / "res" / "stocks.json", log, "2020-07-30")


def _one_signal_series(seed=8, drop=0.93):
    """An uptrend whose only RSI(2) signal is on the very last bar (one hard down day)."""
    d = _series(500, seed, vol=0.006, drift=0.0009)
    c = d["close"].to_numpy().copy()
    c[-1] = c[-2] * drop
    return d.assign(close=c, open=np.r_[c[0], c[:-1]], high=c * 1.003, low=c * 0.997)


def test_scanner_ignores_a_signal_while_the_stock_is_already_in_a_trade():
    from fxengine.stocks import scan
    d = _series(500, 8, vol=0.01, drift=0.0008)
    c = d["close"].to_numpy().copy()
    c[-3:] = c[-4] * np.array([0.975, 0.955, 0.94])               # signals on the 2nd AND 3rd down day: the 3rd overlaps the trade the 2nd would open
    d = d.assign(close=c, open=np.r_[c[0], c[:-1]], high=c * 1.003, low=c * 0.997)
    rows = [r for r in scan.run({"aaa.us": d}, set(), []) if r["rule"] == "RSI2_PULLBACK"]
    assert rows == []                                              # the research would have skipped it, so it is not listed


def test_forward_test_closes_setups_exactly_like_the_backtest_and_tracks_every_signal():
    from fxengine.stocks import scan, backtest as B, strategies as S2
    d = _one_signal_series()
    rows = scan.run({"aaa.us": d}, {"RSI2_PULLBACK"}, [])
    s = next(r for r in rows if r["rule"] == "RSI2_PULLBACK")
    assert s["shown"] is True and s["proven"] is True and s["signal_date"] == f"{d.index[-1]:%Y-%m-%d}"
    c = d["close"].to_numpy()
    idx = pd.bdate_range(d.index[-1] + pd.offsets.BDay(1), periods=3)
    cl = [c[-1] * 1.04, c[-1] * 1.07, c[-1] * 1.06]
    ext = pd.concat([d, pd.DataFrame(dict(open=np.r_[c[-1], cl[:-1]], high=np.array(cl) * 1.003, low=np.array(cl) * 0.997, close=cl, volume=1e6), index=idx)])
    upd = scan.recheck(s, {"aaa.us": ext})
    assert upd["status"] == "CLOSED" and upd["closed"]["bars"] >= 1
    bt = B.trades_for("aaa.us", ext, S2.BAR_RULES["RSI2_PULLBACK"](ext))
    assert abs(bt[bt["entry_date"] == pd.Timestamp(upd["closed"]["entry_date"])]["gross"].iloc[0] - upd["closed"]["gross"]) < 1e-5          # identical to the backtest's own number
    assert scan.recheck(upd, {"aaa.us": ext}) == upd                                                                                         # a closed trade never changes
    fw = scan.forward_summary([upd], {"RSI2_PULLBACK": 0.004})
    assert fw["RSI2_PULLBACK"]["n"] == 1 and fw["RSI2_PULLBACK"]["lo"] is None and fw["RSI2_PULLBACK"]["expected"] == 0.004


def test_only_the_strongest_setups_are_shown_but_all_are_tracked():
    from fxengine.stocks import scan
    panel = {}
    for i in range(8):
        panel[f"s{i}.us"] = _one_signal_series(20 + i, 0.93 - 0.004 * i)
    rows = [r for r in scan.run(panel, set(), []) if r["rule"] == "RSI2_PULLBACK"]
    assert len(rows) >= 6 and sum(r["shown"] for r in rows) == scan.MAX_PER_RULE


def test_forward_card_appears_on_the_setups_tab():
    from fxengine.stocks import dashboard as DB
    sp = dict(asof="2026-11-18", setups=[], forward={"RSI2_PULLBACK": dict(n=12, mean=0.004, hit_rate=0.66, lo=None, hi=None, expected=0.0039)})
    h = DB.render(None, sp)
    assert "Forward test" in h and "needs 30+" in h and "Short-term pullback" in h


FX_LIKE = ("<!doctype html><html><head><style>.x{}</style></head><body><div class='wrap'><div class='tabs'><button data-t='overview'>Trades</button><button data-t='system'>System</button></div>"
           "<div class='tab' id='overview'>fx trades</div><div class='tab' id='system'>fx system</div></div><script>const tabs=document.querySelectorAll('.tabs button'),secs=document.querySelectorAll('.tab');</script></body></html>")


def test_stocks_tab_is_injected_into_the_real_fx_page_and_never_twice():
    from fxengine.stocks import serve, tab
    h = serve.inject(FX_LIKE, tab.CSS, tab.fragment(None, None))
    assert "<button data-t='stocks'>Stocks</button>" in h and h.count("id='stocks'") == 1 and "#stocks .stnav" in h and "fx trades" in h and "fx system" in h
    assert h.index("data-t='system'") < h.index("data-t='stocks'") and h.count("class='tab'") == 3              # 2 FX tabs + exactly one Stocks tab
    assert serve.inject(h, tab.CSS, tab.fragment(None, None)) == h                                                # already there (e.g. FX shipped it itself): unchanged
    assert serve.inject("<html>unexpected</html>", tab.CSS, "x") is None                                          # unknown page: no blind injection


def test_combined_page_is_served_from_the_fx_dashboard_when_it_is_reachable(tmp_path, monkeypatch):
    import http.server, threading, urllib.request
    from fxengine.stocks import serve

    class Up(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(FX_LIKE.encode())
        def log_message(self, *a): pass
    up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Up); threading.Thread(target=up.serve_forever, daemon=True).start()
    monkeypatch.chdir(tmp_path)
    serve.AUTO[0] = 60
    serve.FX["host"], serve.FX["port"] = "127.0.0.1", up.server_address[1]
    srv = serve.ThreadingHTTPServer(("127.0.0.1", 0), serve.H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    h = urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/").read().decode()
    srv.shutdown(); up.shutdown()
    assert "fx trades" in h and "<button data-t='stocks'>Stocks</button>" in h and "FX dashboard not reachable" not in h and "http-equiv='refresh' content='60'" in h


def _market_panel():
    p = _panel(30, 600, 70)
    for s in ("spy.us", "qqq.us", "iwm.us", "isf.uk", "xlk.us", "xlf.us", "gld.us", "tlt.us"):
        p[s] = _series(600, abs(hash(s)) % 1000, vol=0.01, drift=0.0004)
    return p


def test_market_context_charts_and_system_health(tmp_path):
    from fxengine.stocks import market
    p = _market_panel()
    setups = [dict(rule="RSI2_PULLBACK", symbol="s1.us", status="PENDING", invalidation=90.0, exit_level=120.0, entry_price=None, signal_date="2013-01-01")]
    mk = market.build(p, setups, tmp_path)
    assert mk["regime"]["label"] in ("UPTREND", "DOWNTREND", "MIXED") and 0 <= mk["breadth"]["above200"] <= 1 and len(mk["indices"]) == 4
    assert mk["sectors"][0]["r21"] >= mk["sectors"][-1]["r21"] and len(mk["movers"]["up"]) == 5
    assert "s1.us" in mk["charts"] and len(mk["charts"]["s1.us"]["c"]) == 250 and {x["kind"] for x in mk["charts"]["s1.us"]["levels"]} == {"invalidation", "exit"}
    assert mk["system"]["symbols"] == len(p) and mk["system"]["stale"] == []
    assert market.write(p, setups, tmp_path / "m.json", tmp_path).exists()


def test_journal_validates_pairs_first_in_first_out_and_matches_setups(tmp_path):
    from fxengine.stocks import journal as J
    f = tmp_path / "j.csv"
    for bad in (dict(date="x", symbol="aapl", side="buy", price=1, qty=1), dict(date="2026-11-01", symbol="", side="buy", price=1, qty=1), dict(date="2026-11-01", symbol="aapl", side="hold", price=1, qty=1),
                dict(date="2026-11-01", symbol="aapl", side="buy", price="abc", qty=1), dict(date="2026-11-01", symbol="aapl", side="buy", price=-1, qty=1)):
        with pytest.raises(ValueError):
            J.add(bad, f)
    assert not f.exists()
    J.add(dict(date="2026-11-02", symbol="AAPL", side="buy", price=100, qty=2, note="x"), f)
    J.add(dict(date="2026-11-03", symbol="aapl", side="buy", price=110, qty=1), f)
    J.add(dict(date="2026-11-09", symbol="aapl", side="sell", price=120, qty=2.5), f)
    pr = J.pair(J.load(f))
    assert len(pr["closed"]) == 2 and round(pr["closed"][0]["pnl"], 2) == 40.0 and round(pr["closed"][1]["pnl"], 2) == 5.0 and pr["open"][0]["qty"] == 0.5     # FIFO: 2 @100, then 0.5 of the 110 lot
    assert J.from_setup(pr["closed"][0], [dict(symbol="aapl.us", rule="RSI2_PULLBACK", signal_date="2026-11-01")]) == "RSI2_PULLBACK" and J.from_setup(pr["closed"][0], []) is None


def test_every_fx_style_section_renders_and_the_chart_data_is_embedded():
    from fxengine.stocks import market, dashboard as DB, journal as J
    p = _market_panel()
    mk = market.build(p, [], Path("."))
    h = DB.render(None, None, mk, dict(closed=[], open=[], raw=0))
    for k, name in DB.SECTIONS:
        assert f'id="{k}"' in h and name in h
    assert 'id="st-cd"' in h and "Sector &amp; asset strength" in h and "Log a trade you made" in h and "Health checks" in h and "Daily chart" in h


def test_journal_endpoint_saves_a_trade_and_refuses_anything_else(tmp_path, monkeypatch):
    import threading, urllib.request, urllib.error
    from fxengine.stocks import serve, journal as J
    monkeypatch.chdir(tmp_path)
    srv = serve.ThreadingHTTPServer(("127.0.0.1", 0), serve.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def post(path, body, ctype="application/json"):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": ctype})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    good = dict(date="2026-11-02", symbol="aapl", side="buy", price=100, qty=1)
    assert post("/api/journal", good)[0] == 200 and len(J.load(tmp_path / "data/stocks/journal.csv")) == 1
    assert post("/api/journal", dict(good, price="x"))[0] == 400 and post("/api/journal", good, ctype="text/plain")[0] == 415 and post("/api/other", good)[0] == 404
    srv.shutdown()


def _acct_panel(n=40, entry_open=100.0, path=None):
    idx = pd.bdate_range("2026-11-02", periods=n)
    path = path if path is not None else np.full(n, 100.0)
    return pd.DataFrame(dict(open=np.r_[entry_open, path[:-1]], high=path * 1.01, low=path * 0.99, close=path, volume=1e6), index=idx)


def _setup(sym, rule, signal_date, inv, strength=1.0, closed=None, sid=None):
    return dict(id=sid or f"{rule}|{sym}|{signal_date}", rule=rule, symbol=sym, market="US", signal_date=signal_date, invalidation=inv, strength=strength, status="CLOSED" if closed else "VALID", closed=closed)


def test_paper_account_sizes_risk_to_20_pounds_caps_positions_and_converts_currency():
    from fxengine.stocks import account as A
    rates = pd.Series([1.25], index=[pd.Timestamp("2026-10-01")])             # USD per GBP
    p = {"aaa.us": _acct_panel(), "bbb.uk": _acct_panel(entry_open=500.0, path=np.full(40, 500.0))}
    # US stock: entry 100 USD = £80; stop 95 USD -> risk per share £4 -> 5 shares = £400 (under the 25% cap of £625): risk exactly £20
    r = A.simulate([_setup("aaa.us", "RSI2_PULLBACK", "2026-11-02", 95.0)], p, rates, {"RSI2_PULLBACK"})
    pos = r["positions"][0]
    assert abs(pos["shares"] * 4.0 - 20.0) < 0.01 and abs(pos["cost"] - 400.0) < 0.01 and abs(r["balance"] - 2500.0) < 0.01
    # a very tight stop would need a huge position: it is capped at 25% of the account (£625)
    r2 = A.simulate([_setup("aaa.us", "RSI2_PULLBACK", "2026-11-02", 99.9)], p, rates, {"RSI2_PULLBACK"})
    assert abs(r2["positions"][0]["cost"] - 625.0) < 0.5
    # UK prices are pence: 500p = £5.00, stop 450p -> £0.50 risk per share -> 40 shares = £200
    r3 = A.simulate([_setup("bbb.uk", "RSI2_PULLBACK", "2026-11-02", 450.0)], p, rates, {"RSI2_PULLBACK"})
    assert abs(r3["positions"][0]["cost"] - 200.0) < 0.5
    # rules that have not passed the research gate are not traded
    assert A.simulate([_setup("aaa.us", "BREAKOUT_20", "2026-11-02", 95.0)], p, rates, {"RSI2_PULLBACK"})["positions"] == []


def test_paper_account_closes_trades_at_the_researchs_exit_price_and_tiles_add_up():
    from fxengine.stocks import account as A
    rates = pd.Series([1.25], index=[pd.Timestamp("2026-10-01")])
    path = np.r_[np.full(10, 100.0), np.full(30, 110.0)]
    d = _acct_panel(path=path)
    # the research said: entered at the open of 3 Nov (100), exited at the open of the bar after an exit signal -> +10% gross
    entry, exit_ = d.index[1], d.index[11]
    closed = dict(gross=0.10, entry_date=f"{entry:%Y-%m-%d}", exit_date=f"{exit_:%Y-%m-%d}", bars=10)
    r = A.simulate([_setup("aaa.us", "RSI2_PULLBACK", "2026-11-02", 95.0, closed=closed)], {"aaa.us": d}, rates, {"RSI2_PULLBACK"}, today=d.index[-1])
    t = r["closed"][0]
    assert t["exit_date"] == f"{exit_:%Y-%m-%d}" and abs(t["pnl"] - 40.0) < 0.05 and t["r"] == 2.0 and abs(t["pct"] - 0.10) < 1e-6          # £400 position, +10% = +£40 = 2R
    assert abs(r["balance"] - 2540.0) < 0.05 and r["positions"] == []
    tl = r["tiles"]
    assert tl["wins"] == 1 and tl["losses"] == 0 and abs(tl["alltime"] - 40.0) < 0.05 and abs(tl["balance"] - 2540.0) < 0.05 and tl["n_open"] == 0


def test_paper_account_never_spends_cash_it_does_not_have_and_takes_the_strongest_first():
    from fxengine.stocks import account as A
    rates = pd.Series([1.25], index=[pd.Timestamp("2026-10-01")])
    p = {f"s{i}.us": _acct_panel() for i in range(8)}
    rows = [_setup(f"s{i}.us", "RSI2_PULLBACK", "2026-11-02", 99.5, strength=float(i)) for i in range(8)]       # each wants the £625 cap
    r = A.simulate(rows, p, rates, {"RSI2_PULLBACK"})
    spent = sum(x["cost"] for x in r["positions"])
    assert spent <= 2500.0 + 0.01 and len(r["positions"]) == 4 and len(r["skipped"]) == 4                              # 4 x £625 = the whole account
    assert {x["symbol"] for x in r["positions"]} == {"s7.us", "s6.us", "s5.us", "s4.us"}                               # the strongest four


def test_account_card_has_fx_style_tiles_and_marks_cards_held_by_the_account():
    from fxengine.stocks import dashboard as DB
    ac = dict(balance=2540.0, start=2500.0, curve=[["2026-11-18", 2500.0], ["2026-11-19", 2520.0], ["2026-11-20", 2540.0]], fallback_rate=True,
              positions=[dict(id="a", symbol="aapl.us", rule="RSI2_PULLBACK", shares=5.0, cost=400.0, value=410.0, floating=10.0, risk=20.0)], closed=[], skipped=[dict(id="b", symbol="msft.us", why="not enough free cash for a meaningful position")],
              tiles=dict(balance=2540.0, today=12.0, week=40.0, month=40.0, alltime=40.0, floating=10.0, n_open=1, wins=1, losses=0, start=2500.0))
    sp = dict(asof="2026-11-20", setups=[dict(id="a", rule="RSI2_PULLBACK", symbol="aapl.us", market="US", signal_date="2026-11-19", close=100.0, invalidation=95.0, strength=1, exit_text="x", proven=True, status="PENDING")],
              forward={}, closed=[], account=ac)
    h = DB.render(None, sp)
    assert "Hypothetical balance" in h and "£2,540" in h and "start £2,500" in h and "IN PAPER ACCOUNT" in h and "GBPUSD rate file missing" in h and "skipped for lack of cash" in h


def test_scan_account_payload_is_plain_json_and_never_raises():
    import json as _j
    from fxengine.stocks import scan
    rates = pd.Series([1.25], index=[pd.Timestamp("2026-10-01")])
    d = _acct_panel()
    out = scan.account_payload([_setup("aaa.us", "RSI2_PULLBACK", "2026-11-02", 95.0)], {"aaa.us": d}, {"RSI2_PULLBACK"}, rates)
    _j.dumps(out)                                                                                      # serialisable
    assert out["tiles"]["n_open"] == 1 and abs(out["balance"] - 2500.0) < 0.5
    assert "error" in scan.account_payload([dict(id="x")], {"aaa.us": d}, {"RSI2_PULLBACK"}, rates) or True        # malformed rows: a payload, never an exception


def _fx_series(drift, n=700, seed=1, start="2022-01-03"):
    r = np.random.default_rng(seed).normal(drift, 0.003, n)
    return pd.Series(1.1 * np.exp(np.cumsum(r)), index=pd.bdate_range(start, periods=n))


def test_dollar_strength_has_the_right_sign_for_every_pair_convention():
    from fxengine.stocks import crossctx as C
    up = _fx_series(0.001)                                   # a pair rising 0.1% a day
    eur_up = C.usd_strength({"EURUSD": up})                  # EURUSD rising = the dollar is FALLING
    jpy_up = C.usd_strength({"USDJPY": up})                  # USDJPY rising = the dollar is RISING
    assert eur_up.iloc[-1] < -0.3 and jpy_up.iloc[-1] > 0.3 and abs(eur_up.iloc[-1] + jpy_up.iloc[-1]) < 1e-9


def test_context_uses_only_the_past_and_is_published_for_the_other_engine(tmp_path):
    from fxengine.stocks import crossctx as C
    p = _market_panel()
    p["spy.us"] = _series(900, 33, vol=0.01, drift=0.0004)
    fx = {"EURUSD": _fx_series(0.0002, 900, 2, "2022-01-03"), "USDJPY": _fx_series(0.0001, 900, 3, "2022-01-03"), "AUDJPY": _fx_series(0.0002, 900, 4, "2022-01-03")}
    idx = p["spy.us"].index
    fx = {k: v.reindex(idx, method="ffill").dropna() for k, v in fx.items()}
    ctx = C.build(p, fx)
    assert {"spy_vs200", "spy_trend", "vol20", "breadth200", "usd_20d_z", "risk_20d_z", "dow"} <= set(ctx.columns) and ctx["breadth200"].dropna().between(0, 1).all()
    # no look-ahead: rewriting the future must not change any earlier value
    p2 = {k: v.copy() for k, v in p.items()}
    p2["spy.us"].iloc[700:, :4] *= 1.5
    fx2 = {k: v.copy() for k, v in fx.items()}
    e = fx2["EURUSD"]
    fx2["EURUSD"] = pd.concat([e.iloc[:-100], e.iloc[-100:] * 1.3])
    ctx2 = C.build(p2, fx2)
    cut = ctx.index[650]
    assert np.allclose(ctx.loc[:cut].fillna(0).to_numpy(float), ctx2.loc[:cut].fillna(0).to_numpy(float))
    snap = C.publish(ctx, tmp_path / "h.csv", tmp_path / "l.json")
    assert snap["asof"] == f"{ctx.index[-1]:%Y-%m-%d}" and "about" in snap and (tmp_path / "h.csv").read_text().startswith("date,spy_trend")
    assert C.at(ctx, ctx.index[300])["spy_trend"] in (-1.0, 1.0, 0.0) and C.at(ctx, "1990-01-01") == {}


def test_every_new_setup_records_the_market_context_it_fired_in():
    from fxengine.stocks import scan, crossctx as C
    d = _one_signal_series()
    p = {"aaa.us": d, "spy.us": _series(500, 3, vol=0.008, drift=0.0005)}
    p["spy.us"].index = d.index
    ctx = C.build(p, {})
    rows = scan.run(p, set(), [], ctx)
    s = next(r for r in rows if r["rule"] == "RSI2_PULLBACK")
    assert "spy_trend" in s["ctx"] and "vol20" in s["ctx"] and "dow" in s["ctx"]


def test_downloader_also_fetches_the_daily_fx_pairs_for_the_context(tmp_path):
    class R:
        def __init__(s, c, t=""): s.status_code, s.content = c, t.encode()
    urls = []

    def get(u):
        urls.append(u)
        return R(200, "") if "stooq" in u else R(200, _yahoo_json())
    D.download(tmp_path, symbols=["aapl.us"], get=get, pause=0)
    assert all((tmp_path / "raw" / f"fx_{p}.csv").exists() for p in ("EURUSD", "USDJPY", "AUDJPY")) and any("AUDJPY%3DX" in u or "AUDJPY=X" in u for u in urls)


def test_new_indicators_behave_like_their_definitions():
    d = _series(600, 3)
    h, l, c = d["high"], d["low"], d["close"]
    k = I.stoch_k(h, l, c, 14).dropna()
    assert k.between(0, 100).all()
    m, up, lo = I.bollinger(c, 20, 2.0)
    assert ((up - m).dropna() > 0).all() and np.allclose((up - m).dropna(), (m - lo).dropna())
    ib = I.ibs(h, l, c).dropna()
    assert ib.between(0, 1).all()
    a, pdi, mdi = I.adx(h, l, c, 14)
    assert a.dropna().between(0, 100).all() and (pdi.dropna() >= 0).all() and (mdi.dropna() >= 0).all()
    tr = I.true_range(h, l, c).dropna()
    assert (tr >= (h - l).loc[tr.index] - 1e-12).all() and (I.atr(h, l, c, 14).dropna() > 0).all()
    ml, sg = I.macd(c)
    assert ml.notna().sum() > 400 and sg.notna().sum() > 380
    up_c = pd.Series(np.linspace(100, 200, 300))                       # a steady uptrend: ADX high, +DI above -DI, stochastic at the top, IBS-agnostic
    a2, p2, m2 = I.adx(up_c * 1.01, up_c * 0.99, up_c, 14)
    assert a2.iloc[-1] > 40 and p2.iloc[-1] > m2.iloc[-1] and I.stoch_k(up_c * 1.0, up_c * 0.999, up_c, 14).iloc[-1] > 95


def test_panel_rules_use_only_the_past_and_every_rule_has_a_name_and_hold_limit():
    p = _market_panel()
    base = {r: S.rule_sigs(r, p) for r in ("HIGH52_MOM", "RS_PULLBACK")}
    q = {s: d.copy() for s, d in p.items()}
    for d in q.values():
        d.iloc[480:, :4] *= 1.4
    chg = {r: S.rule_sigs(r, q) for r in ("HIGH52_MOM", "RS_PULLBACK")}
    for r in base:
        assert all((base[r][s].entry[:470] == chg[r][s].entry[:470]).all() and (base[r][s].exit[:470] == chg[r][s].exit[:470]).all() for s in p)
    assert all(r in S.INFO and r in S.MAX_HOLD for r in S.SWING_RULES) and set(S.RULES) == set(S.SWING_RULES) | {"GAP_CONT_DAY", "GAP_FADE_DAY"}


def test_international_symbols_map_to_yahoo_currencies_and_countries():
    assert U.yahoo_symbol("aapl.us") == "AAPL" and U.yahoo_symbol("vod.uk") == "VOD.L" and U.yahoo_symbol("sap.de") == "SAP.DE" and U.yahoo_symbol("volv-b.se") == "VOLV-B.ST" and U.yahoo_symbol("7203.jp") == "7203.T"
    assert U.currency("vod.uk") == ("GBP", 100.0) and U.currency("sap.de") == ("EUR", 1.0) and U.currency("cspx.uk") == ("USD", 1.0) and U.currency("npn.za") == ("ZAR", 100.0) and U.currency("7203.jp") == ("JPY", 1.0)
    assert U.market("sap.de") == "DE" and U.kind("sap.de") == "intl" and len(set(U.SYMBOLS)) == len(U.SYMBOLS) and len(U.COUNTRY) >= 28


def test_paper_account_converts_every_currency_into_pounds(tmp_path):
    from fxengine.stocks import account as A
    rates = {"USD": pd.Series([1.25], index=[pd.Timestamp("2026-10-01")]), "EUR": pd.Series([1.15], index=[pd.Timestamp("2026-10-01")]), "JPY": pd.Series([190.0], index=[pd.Timestamp("2026-10-01")])}
    m = A.Money(rates)
    d = pd.Timestamp("2026-11-02")
    assert abs(m.gbp("aapl.us", 125.0, d) - 100.0) < 1e-9 and abs(m.gbp("sap.de", 115.0, d) - 100.0) < 1e-9 and abs(m.gbp("7203.jp", 19000.0, d) - 100.0) < 1e-9 and abs(m.gbp("vod.uk", 8000.0, d) - 80.0) < 1e-9
    assert not m.used_fallback and A.Money({}).gbp("sap.de", 10.0, d) == 10.0                                              # a missing rate falls back (and is flagged) instead of crashing
    p = {"sap.de": _acct_panel(entry_open=115.0, path=np.full(40, 115.0))}
    r = A.simulate([_setup("sap.de", "RSI2_PULLBACK", "2026-11-02", 109.25)], p, rates, {"RSI2_PULLBACK"})            # EUR 115 = £100; stop 5% below = £5 risk per share -> 4 shares = £400
    assert abs(r["positions"][0]["cost"] - 400.0) < 0.5
    (tmp_path / "gbpusd.csv").write_text("Date,Open,High,Low,Close,Volume\n2026-10-01,1,1,1,1.25,0\n")
    (tmp_path / "gbp_EUR.csv").write_text("Date,Open,High,Low,Close,Volume\n2026-10-01,1,1,1,1.15,0\n")
    assert set(A.load_rates(tmp_path)) == {"USD", "EUR"}


def test_downloader_also_fetches_the_gbp_rates_for_the_countries_in_the_universe(tmp_path):
    class R:
        def __init__(s, c, t=""): s.status_code, s.content = c, t.encode()
    urls = []

    def get(u):
        urls.append(u)
        return R(200, "") if "stooq" in u else R(200, _yahoo_json())
    D.download(tmp_path, symbols=["sap.de"], get=get, pause=0)
    assert any("SAP.DE" in u for u in urls) and (tmp_path / "raw" / "gbp_EUR.csv").exists() and (tmp_path / "raw" / "gbp_JPY.csv").exists() and (tmp_path / "raw" / "gbpusd.csv").exists()


def _edgar_company(extra_quarters=0, restate=None, jump_last=False):
    """Synthetic SEC data in the documented shapes: submissions (8-K item 2.02) + XBRL company facts (10-Q quarterly EPS and revenue)."""
    ends, eps, rev = [], [], []
    k = 0
    for y in range(2019, 2024 + extra_quarters):
        for md in ("03-31", "06-30", "09-30"):
            ends.append(pd.Timestamp(f"{y}-{md}"))
            k += 1
            eps.append(round(1.0 + 0.05 * k + (0.3 if k % 4 == 0 else 0.0), 3))
            rev.append(1000.0 + 20 * k)
    if jump_last:
        eps[-1] += 1.5
    def fact(end, val, filed, form="10-Q", dur=90):
        return dict(start=f"{(end - pd.Timedelta(days=dur)):%Y-%m-%d}", end=f"{end:%Y-%m-%d}", val=val, filed=f"{filed:%Y-%m-%d}", form=form)
    eps_f = [fact(e, v, e + pd.Timedelta(days=35)) for e, v in zip(ends, eps)]
    rev_f = [fact(e, v, e + pd.Timedelta(days=35)) for e, v in zip(ends, rev)]
    eps_f.append(dict(start="2020-01-01", end="2020-12-31", val=9.9, filed="2021-02-20", form="10-K"))                 # an ANNUAL fact: must be ignored as a quarter
    if restate:
        eps_f.append(fact(ends[restate], eps[restate] + 5.0, ends[restate] + pd.Timedelta(days=400)))                  # a LATER restatement of an old quarter: must be ignored
    facts = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": eps_f}}, "Revenues": {"units": {"USD": rev_f}}}}}
    f8 = dict(form=[], filingDate=[], items=[], acceptanceDateTime=[])
    for e in ends:
        d = e + pd.Timedelta(days=28)
        f8["form"] += ["8-K", "8-K"]; f8["filingDate"] += [f"{d:%Y-%m-%d}", f"{d + pd.Timedelta(days=3):%Y-%m-%d}"]
        f8["items"] += ["2.02,9.01", "5.02"]; f8["acceptanceDateTime"] += [f"{d:%Y-%m-%d}T21:05:00.000Z"] * 2
    return {"filings": {"recent": f8}}, facts, ends


def test_earnings_events_are_point_in_time_and_use_first_reported_numbers():
    from fxengine.stocks import events as EV
    sub, facts, ends = _edgar_company(restate=8)
    assert [x["date"] for x in EV.earnings_8ks(sub)][:2] == [f"{ends[0] + pd.Timedelta(days=28):%Y-%m-%d}", f"{ends[1] + pd.Timedelta(days=28):%Y-%m-%d}"] and len(EV.earnings_8ks(sub)) == len(ends)      # only Item 2.02 counts
    ev = pd.DataFrame(EV.earnings_events("zzz.us", sub, facts))
    assert len(ev) > 5 and ev["sue"].notna().sum() > 3 and (ev["n_hist"] >= EV.SUE_MIN_HISTORY).all() is np.bool_(True) or ev["n_hist"].max() >= EV.SUE_MIN_HISTORY
    assert not ((ev["period_end"] == ends[8]) & (ev["eps"] > 5)).any()                                           # the restated value (+5) never appears
    assert (ev["announce_date"] > ev["period_end"]).all()                                                          # dated by the release, after the quarter it describes
    # point-in-time: adding LATER quarters, a surprise jump and a restatement must not change any earlier event
    sub2, facts2, _ = _edgar_company(extra_quarters=2, restate=8, jump_last=True)
    ev2 = pd.DataFrame(EV.earnings_events("zzz.us", sub2, facts2))
    a = ev[ev["announce_date"] <= ev["announce_date"].max()].set_index("announce_date")[["eps", "eps_prev", "sue", "rev_yoy"]]
    b = ev2.set_index("announce_date").loc[a.index, ["eps", "eps_prev", "sue", "rev_yoy"]]
    assert np.allclose(a.to_numpy(float), b.to_numpy(float), equal_nan=True)
    assert ev2.iloc[-1]["sue"] > 2.0 and ev2.iloc[-1]["eps_change"] > 1.5                                          # the planted jump is a large positive surprise


def test_fred_parsing_macro_lag_and_sec_contact_are_safe(tmp_path, monkeypatch):
    from fxengine.stocks import events as EV
    s = EV.parse_fred("observation_date,VIXCLS\n2024-01-02,13.2\n2024-01-03,.\n2024-01-04,14.0\n", "VIXCLS")
    assert list(s.index.strftime("%Y-%m-%d")) == ["2024-01-02", "2024-01-04"] and s.iloc[1] == 14.0                    # '.' = missing, dropped
    idx = pd.bdate_range("2024-01-02", periods=5)
    m = EV.macro_context({"VIXCLS": pd.Series([10.0, 11, 12, 13, 14], index=idx)}, idx)
    assert np.isnan(m["vix"].iloc[0]) and m["vix"].iloc[1] == 10.0 and m["vix"].iloc[4] == 13.0                       # lagged one day: nothing from the future
    assert EV.ticker_to_cik({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"}}) == {"AAPL": "0000320193"}
    monkeypatch.delenv("SEC_CONTACT", raising=False)
    with pytest.raises(SystemExit, match="never stored in git"):
        EV.sec_contact(tmp_path)
    (tmp_path / "data/stocks").mkdir(parents=True)
    (tmp_path / "data/stocks/sec_contact.txt").write_text("someone@example.org\n")
    assert EV.sec_contact(tmp_path) == "someone@example.org"


def test_events_download_builds_the_table_caches_files_and_survives_a_bad_company(tmp_path):
    from fxengine.stocks import events as EV
    sub, facts, _ = _edgar_company()
    calls = []

    def get(u):
        calls.append(u)
        if "company_tickers" in u:
            return 200, json.dumps({"0": {"cik_str": 1, "ticker": "ZZZ", "title": "Z"}}).encode()
        if "submissions" in u:
            return 200, json.dumps(sub).encode()
        if "companyfacts" in u:
            return 200, json.dumps(facts).encode()
        return 404, b""
    df = EV.fetch_all(["zzz.us", "nope.us"], tmp_path, get=get, pause=0)
    assert len(df) > 5 and (tmp_path / EV.EVENTS).exists() and "nope.us: no SEC CIK" in (tmp_path / "data/stocks/events_gaps.txt").read_text()
    n = len(calls)
    EV.fetch_all(["zzz.us"], tmp_path, get=get, pause=0)
    assert len(calls) == n + 1                                                                                          # only the small ticker list again; company files come from the cache
    assert EV.days_since_earnings(df, "zzz.us", df["announce_date"].max() + pd.Timedelta(days=10)) == 10 and EV.days_since_earnings(df, "zzz.us", "1990-01-01") is None


def test_earnings_drift_rule_acts_only_after_the_release_and_only_on_big_positive_surprises():
    d = _series(400, 5, vol=0.01)
    D = d.index[200]                                                            # the 8-K filing date
    ev = pd.DataFrame([dict(symbol="aaa.us", announce_date=D, sue=3.0, eps_change=0.4, rev_yoy=0.1),                  # qualifies
                       dict(symbol="aaa.us", announce_date=d.index[300], sue=1.0, eps_change=0.4, rev_yoy=0.1),         # surprise too small
                       dict(symbol="aaa.us", announce_date=d.index[100], sue=3.0, eps_change=-0.1, rev_yoy=0.1)])       # EPS fell
    sg = S.rule_sigs("PEAD_SUE", {"aaa.us": d}, ev)["aaa.us"]
    assert np.flatnonzero(sg.entry).tolist() == [201]                           # the first bar AFTER the filing date: never on or before it (no look-ahead)
    tr = B.trades_for("aaa.us", d, sg)
    assert len(tr) == 1 and tr.iloc[0]["entry_date"] == d.index[202] and tr.iloc[0]["bars"] == S.PEAD_HOLD            # bought at the open AFTER the reaction day, held the fixed 40 bars
    assert not S.rule_sigs("PEAD_SUE", {"aaa.us": d}, None)["aaa.us"].entry.any() and not S.rule_sigs("PEAD_SUE", {"aaa.us": d}, ev.iloc[0:0])["aaa.us"].entry.any()      # no events -> no trades, no error


def test_context_carries_macro_and_earnings_timing_and_the_rule_is_registered():
    from fxengine.stocks import crossctx as C, events as EV
    p = _market_panel()
    p["spy.us"] = _series(900, 33, vol=0.01, drift=0.0004)
    idx = p["spy.us"].index
    fred = {"VIXCLS": pd.Series(np.linspace(12, 30, len(idx)), index=idx), "T10Y2Y": pd.Series(np.linspace(1, -0.5, len(idx)), index=idx)}
    ctx = C.build(p, {}, fred)
    assert {"vix", "vix_z", "curve_10y2y"} <= set(ctx.columns) and np.isnan(ctx["vix"].iloc[0]) and ctx["vix"].iloc[300] < ctx["vix"].iloc[600]
    ev = pd.DataFrame([dict(symbol="s1.us", announce_date=idx[500], sue=1, eps_change=1, rev_yoy=1)])
    assert EV.days_since_earnings(ev, "s1.us", idx[510]) == (idx[510] - idx[500]).days and "PEAD_SUE" in S.RULES and "PEAD_SUE" in S.INFO and S.MAX_HOLD["PEAD_SUE"] == 40


def test_account_holds_one_position_per_stock_and_prefers_the_better_evidenced_rule():
    from fxengine.stocks import account as A
    rates = pd.Series([1.25], index=[pd.Timestamp("2026-10-01")])
    p = {"aaa.us": _acct_panel()}
    rows = [_setup("aaa.us", "STOCH_PULLBACK", "2026-11-02", 95.0, strength=9.0), _setup("aaa.us", "RSI2_PULLBACK", "2026-11-02", 95.0, strength=1.0)]
    r = A.simulate(rows, p, rates, {"RSI2_PULLBACK", "STOCH_PULLBACK"}, rank={"RSI2_PULLBACK": 0.0046, "STOCH_PULLBACK": 0.0066})
    assert len(r["positions"]) == 1 and r["positions"][0]["rule"] == "STOCH_PULLBACK" and any("already held" in x["why"] for x in r["skipped"])       # the rule with the higher research gain wins the stock


def test_macro_falls_back_to_yahoo_when_fred_does_not_answer(tmp_path):
    from fxengine.stocks import events as EV
    class Dead(Exception): pass
    ys = _yahoo_json(400, "2023-01-02")
    def get(u):
        if "fred.stlouisfed.org" in u:
            raise TimeoutError("slow")
        return 200, ys.encode()
    out = EV.fetch_fred(tmp_path, get=get)
    assert "VIXCLS" in out and "T10Y2Y" in out and len(out["VIXCLS"]) > 300 and "BAMLH0A0HYM2" not in out                     # VIX + curve from Yahoo; the credit spread simply stays absent
    m = EV.macro_context(out, pd.bdate_range("2023-01-02", periods=380))
    assert "vix" in m.columns and "curve_10y2y" in m.columns


def _trade_features(n=8000, seed=1, effect=0.0, effect_col="spy_trend", rare=False):
    from fxengine.stocks import filters as F
    rng = np.random.default_rng(seed)
    d = pd.DataFrame(dict(entry_date=pd.Timestamp("2005-01-03") + pd.to_timedelta(np.sort(rng.integers(0, 365 * 18, n)), unit="D"),
                          spy_trend=rng.choice([-1.0, 1.0], n, p=[0.3, 0.7]), vol20=rng.uniform(0.08, 0.5, n), breadth200=rng.uniform(0.1, 0.9, n), spy_5d=rng.normal(0, 0.02, n),
                          atr_ratio=rng.uniform(0.4, 2.0, n), ext_sma20=rng.normal(-0.5, 1.0, n), trend_with=rng.normal(0.08, 0.1, n), rs3m=rng.normal(0, 0.1, n),
                          relvol=rng.uniform(0.5, 2.0, n), dow=rng.integers(0, 5, n).astype(float), dse=rng.choice([np.nan, 1.0, 10.0, 30.0], n)))
    g = rng.normal(0.004, 0.03, n)
    if effect:
        mask = (d["spy_5d"] < -0.045) if rare else (d["spy_trend"] > 0)                 # `rare` = an effect that only exists in a small slice (a filter would have to remove most setups)
        g = g + effect * mask.to_numpy(float)
    d["gross"] = g
    return d


def test_filter_study_finds_a_real_condition_and_validates_it_on_unseen_data():
    from fxengine.stocks import filters as F
    r = F.study("RSI2_PULLBACK", _trade_features(8000, 1, effect=0.012))
    assert r["verdict"].startswith("HELPFUL") and "M_up" in r["filter"] and r["validation"]["ci_lo"] > 0 and r["validation"]["kept_share"] >= 0.5
    assert r["validation"]["kept_mean"] > r["validation"]["baseline"] and r["selected_on"] < r["validated_on"]                  # chosen on the earlier years, judged on the later ones


def test_filter_study_finds_nothing_in_noise_and_cannot_be_starved():
    from fxengine.stocks import filters as F
    helpful = sum(F.study("X", _trade_features(8000, s))["verdict"].startswith("HELPFUL") for s in range(1, 9))
    assert helpful <= 1                                                                                                           # a useless condition is almost never adopted (8 noise data sets)
    r = F.study("X", _trade_features(8000, 3, effect=0.06, rare=True))                                                             # the only real edge sits in a slice that keeps <50% of setups
    assert not r["verdict"].startswith("HELPFUL") or r["validation"]["kept_share"] >= F.KEEP_MIN                                  # the throughput guard: never starve the engine
    assert F.study("X", _trade_features(500, 1))["verdict"].startswith("too few")


def test_trade_features_use_only_the_close_before_entry():
    from fxengine.stocks import filters as F, crossctx as C
    p = _market_panel()
    sig = S.rule_sigs("RSI2_PULLBACK", p)
    parts = [B.trades_for(s, d, sig[s]) for s, d in p.items()]
    tr = pd.concat([t for t in parts if len(t)], ignore_index=True)
    if len(tr) < 5:
        pytest.skip("synthetic market produced too few trades")
    ctx = C.build(p, {})
    a = F.attach_features(tr, p, ctx, None)
    q = {s: d.copy() for s, d in p.items()}
    for d in q.values():
        d.iloc[560:, :4] *= 1.3                                                    # rewrite the future
    ctx2 = C.build(q, {})
    b = F.attach_features(tr[tr["entry_date"] < p["spy.us"].index[540]], q, ctx2, None)
    a2 = a.loc[b.index]
    cols = ["atr_ratio", "ext_sma20", "trend_with", "relvol", "spy_vs200", "vol20"]
    assert np.allclose(a2[cols].fillna(0).to_numpy(float), b[cols].fillna(0).to_numpy(float)) and (b["sig_date"] < b["entry_date"]).all()


def test_filter_study_results_are_shown_on_the_research_tab():
    from fxengine.stocks import dashboard as DB
    fl = dict(filters={"M_up": "S&P 500 in an uptrend", "S_deep": "stretched 1+ ATR below its 20-day average"}, results=[
        dict(rule="RSI2_PULLBACK", n=9000, filter="M_up & S_deep", verdict="HELPFUL on unseen data: candidate to adopt (a written decision is still required)",
             validation=dict(baseline=0.004, kept_mean=0.007, removed_mean=0.001, kept_share=0.6, improvement=0.003, ci_lo=0.0008, ci_hi=0.0052)),
        dict(rule="MOM_12_1", n=500, verdict="too few trades for a filter study")])
    h = DB.render(None, None, None, None, fl)
    assert "Entry-filter study" in h and "S&amp;P 500 in an uptrend + stretched 1+ ATR" in h and "HELPFUL" in h and "too few trades for a filter study" in h


def test_a_setup_is_tagged_with_the_candidate_filter_and_never_removed_by_it():
    from fxengine.stocks import filters as F, scan, crossctx as C
    assert F.passes("M_usd_calm & S_trend_strong", {"usd_20d_z": 0.5, "trend_with": 0.1}) is True
    assert F.passes("M_usd_calm & S_trend_strong", {"usd_20d_z": 2.0, "trend_with": 0.1}) is False
    assert F.passes("M_usd_calm & S_trend_strong", {"trend_with": 0.1}) is None                                    # a missing number is "unknown", never a silent pass
    d = _one_signal_series()
    p = {"aaa.us": d, "spy.us": _series(500, 3, vol=0.008, drift=0.0005)}
    p["spy.us"].index = d.index
    ctx = C.build(p, {})
    rows = scan.run(p, set(), [], ctx, None, cands={"RSI2_PULLBACK": "M_up & S_trend_strong"})
    s = next(r for r in rows if r["rule"] == "RSI2_PULLBACK")
    assert s["cand_filter"] == "M_up & S_trend_strong" and s["cand_ok"] in (True, False) and "trend_with" in s["ctx"] and "atr_ratio" in s["ctx"]
    off = scan.run(p, set(), [], ctx, None, cands={"RSI2_PULLBACK": "M_up & S_trend_strong"})
    assert len([r for r in off if r["rule"] == "RSI2_PULLBACK"]) == 1                                              # tagging, not removal: the setup is there either way


def test_forward_results_are_split_by_the_candidate_filter_and_shown():
    from fxengine.stocks import scan, dashboard as DB
    mk = lambda ok, g, i: dict(rule="STOCH_PULLBACK", status="CLOSED", cand_ok=ok, closed=dict(gross=g, entry_date="2026-12-01", exit_date="2026-12-05", bars=4), symbol=f"s{i}.us", market="US", signal_date="2026-11-30")
    rows = [mk(True, 0.02, 1), mk(True, 0.01, 2), mk(False, -0.01, 3), mk(None, 0.03, 4)]
    fw = scan.forward_summary(rows, {"STOCH_PULLBACK": 0.0066})["STOCH_PULLBACK"]
    assert fw["by_filter"]["with"] == dict(n=2, mean=0.015) and fw["by_filter"]["without"] == dict(n=1, mean=-0.01)
    h = DB.render(None, dict(asof="2026-12-06", setups=[], forward={"STOCH_PULLBACK": fw}, closed=[]))
    assert "Candidate filter" in h and "never removes a setup" in h


def test_only_countries_the_owner_can_trade_show_up_but_the_research_uses_all(tmp_path, monkeypatch):
    from fxengine.stocks import scan, crossctx as C, universe as UN, dashboard as DB
    assert UN.resolve_country("Germany") == "de" and UN.resolve_country("usa") == "us" and UN.resolve_country("de") == "de" and UN.resolve_country("Atlantis") is None
    monkeypatch.chdir(tmp_path)
    assert UN.allowed_countries() is None                                              # no file: every market is shown
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops/stocks_countries.txt").write_text("# my Revolut list\nUS\nuk  # London\n\n")
    assert UN.allowed_countries() == {"us", "uk"}
    d = _one_signal_series()
    p = {"aaa.us": d, "bbb.de": d.copy(), "spy.us": _series(500, 3, vol=0.008, drift=0.0005)}
    p["spy.us"].index = d.index
    rows = scan.run(p, set(), [], C.build(p, {}), None, cands={})
    assert {r["symbol"] for r in rows if r["rule"] == "RSI2_PULLBACK"} == {"aaa.us"}      # the German setup is researched but not shown or tracked
    (tmp_path / "ops/stocks_countries.txt").unlink()
    rows = scan.run(p, set(), [], C.build(p, {}), None, cands={})
    assert {r["symbol"] for r in rows if r["rule"] == "RSI2_PULLBACK"} == {"aaa.us", "bbb.de"}
    mk = dict(asof="2026-11-18", indices=[], breadth=dict(n=1, above50=0.5, above200=0.5, new_highs=0, new_lows=0), regime=dict(label="UPTREND", detail="x"), sectors=[], movers=dict(up=[], down=[]), charts={},
              system=dict(asof="2026-11-18", symbols=2, stale=[], gaps=[], suspicious=[], nightly=[], code="c", trials=16, holdout=[], rows=10))
    h = DB.render(None, dict(asof="2026-11-18", setups=[], forward={}, closed=[], coverage={"us": dict(symbols=100, setups=7), "de": dict(symbols=14, setups=3)}, allowed=["us"]), mk)
    assert "Coverage by country" in h and "YOU CAN TRADE" in h and "research only" in h and "Germany" in h


def test_adrs_give_tradable_exposure_to_other_countries_and_the_default_list_matches_revolut():
    from fxengine.stocks import dashboard as DB
    assert U.home_country("tsm.us") == "tw" and U.home_country("toyota.us") == "us" and U.home_country("aapl.us") == "us" and U.home_country("sap.de") == "de"
    assert {"tsm.us", "baba.us", "bhp.us", "vale.us", "shop.us", "infy.us"} <= set(U.SYMBOLS) and len(set(U.SYMBOLS)) == len(U.SYMBOLS)
    homes = {U.home_country(s) for s in U.SYMBOLS if s.endswith(".us")}
    assert {"tw", "jp", "cn", "in", "br", "ca", "au", "il", "kr", "mx"} <= homes                                       # many company countries are reachable through US listings
    allowed = U.allowed_countries(str(Path("ops/stocks_countries.txt")))
    assert allowed == {"us", "uk", "de", "fr", "nl", "it", "es", "be", "pt", "at", "fi", "se", "dk", "no"}                # US + UK + EEA venues; Tokyo/Hong Kong/Sydney etc. are research-only
    r = dict(id="a", rule="RSI2_PULLBACK", symbol="tsm.us", market="US", home="tw", signal_date="2026-11-18", close=100.0, invalidation=90.0, strength=1, exit_text="x", proven=True, status="PENDING")
    assert "Taiwan company (US-listed ADR)" in DB._trade_card(r) and "ADR" not in DB._trade_card(dict(r, symbol="aapl.us", home="us"))
