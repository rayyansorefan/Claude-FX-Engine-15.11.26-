import numpy as np, pandas as pd
from fxengine.data import store
from fxengine.live import scan as sc
from fxengine.live.sizing import lots_for_risk, gbp_per_pip_per_lot
from fxengine.dashboard import build as db
from test_setups import synth

PX = {"GBPUSD": 1.25, "USDJPY": 150.0, "USDCHF": 0.9, "USDCAD": 1.35, "GBPJPY": 190.0}


def test_sizing():
    lots, pips = lots_for_risk("EURUSD", 1.1000, 1.0985, PX)         # 15 pips, $10/pip/lot -> GBP 8/pip/lot
    assert abs(pips - 15.0) < 1e-6 and abs(lots - 0.16) < 0.011
    assert gbp_per_pip_per_lot("EURGBP", PX) == 10.0
    assert gbp_per_pip_per_lot("USDJPY", PX) > 0 and gbp_per_pip_per_lot("USDCAD", PX) > 0


def _store(tmp):
    for i, s in enumerate(sc.PAIRS):
        m5 = synth(40000, seed=50 + i)
        m5.index = pd.date_range("2025-06-01", periods=len(m5), freq="5min", tz="UTC")
        px = {"JPY": 150.0, "": 1.1}
        store.merge_save(s, "M5", m5, tmp)
        from fxengine.data.resample import resample
        for tf in ("H1", "H4"):
            store.merge_save(s, tf, resample(m5, tf, base="M5"), tmp)
    return m5.index[-1] + pd.Timedelta(minutes=5)


def test_scan_stale_returns_no_candidates_and_fresh_works(tmp_path):
    end = _store(tmp_path)
    stale = sc.scan(tmp_path, now=end + pd.Timedelta(days=3))
    assert stale["status"] == "STALE" and stale["candidates"] == []
    fresh = sc.scan(tmp_path, now=end)
    assert fresh["status"] == "OK" and len(fresh["candidates"]) <= 5
    for c in fresh["candidates"]:
        assert "UNPROVEN" in c["note"]


def test_dashboard_builds_without_and_with_research_files(tmp_path, monkeypatch):
    end = _store(tmp_path)
    monkeypatch.chdir(tmp_path)
    out = db.build(root=tmp_path, out=tmp_path / "d" / "index.html", now=end)
    html = open(out).read()
    assert "Reliability" in html and "no edge found" in html and "Data age" in html
