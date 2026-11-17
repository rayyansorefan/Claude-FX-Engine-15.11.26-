import json
import numpy as np, pandas as pd
from fxengine.research import diagnose as D
from fxengine.live import db as DB


def _frame(n=600, seed=0, planted=False):
    rng = np.random.default_rng(seed)
    created = pd.date_range("2024-01-01", periods=n, freq="7h", tz="UTC")
    net = rng.normal(0, 1, n)
    sym = rng.choice(["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"], n)
    if planted:
        net = net + np.where(sym == "USDJPY", 0.8, 0.0)
    mfe = np.abs(rng.normal(0.6, 0.5, n))
    gross = net + 0.05
    return pd.DataFrame(dict(symbol=sym, created=created, reason="STOP", net_r_stressed=net, trig_stressed=True, gross_r=gross,
                             mfe_r=mfe, mae_r=np.abs(rng.normal(0.5, 0.3, n)), direction=rng.choice(["long", "short"], n),
                             hour=created.hour, dow=created.dayofweek))


def test_classify_separates_signal_from_exit_problems():
    base = dict(triggered=True, net_r=-1.0, gross_r=-0.9, mfe_r=0.1)
    assert D.classify({**base}) == "WRONG_WAY"
    assert D.classify({**base, "mfe_r": 1.4}) == "GAVE_BACK"
    assert D.classify({**base, "mfe_r": 0.7}) == "STALLED"
    assert D.classify({**base, "gross_r": 0.1, "net_r": -0.05}) == "COST_DRAG"
    assert D.classify({**base, "net_r": 0.5}) == "WIN"
    assert D.classify({**base, "triggered": False}) == "NO_FILL"


def test_pure_noise_produces_no_supported_pattern():
    hits = 0
    for seed in range(15):
        r = D.diagnose(_frame(seed=seed), "noise")
        hits += bool(r["scan"]["supported"])
    assert hits <= 2                       # nominal 5% false-alarm rate per dataset: at most a rare fluke in 15 noise datasets


def test_real_pattern_is_found_and_logged_but_never_applied(tmp_path):
    r = D.diagnose(_frame(planted=True), "planted")
    assert any(s["feature"] == "symbol" and s["bucket"] == "USDJPY" for s in r["scan"]["supported"])
    reg = tmp_path / "h.jsonl"
    assert D.log_hypotheses(r, reg) >= 1 and D.log_hypotheses(r, reg) == 0       # idempotent
    assert "CANDIDATE" in json.loads(reg.read_text().splitlines()[0])["status"]


def test_too_few_trades_is_reported_not_concluded():
    r = D.diagnose(_frame(n=20), "tiny")
    assert "too few" in r["verdict"]


def test_old_frames_without_diagnostics_are_skipped():
    assert D.prepare(pd.DataFrame(dict(net_r_stressed=[1.0], trig_stressed=[True], created=[pd.Timestamp("2024-01-01", tz="UTC")]))).empty


def test_ledger_migrates_and_live_line_reads_it(tmp_path):
    p = tmp_path / "e.db"
    import sqlite3
    c = sqlite3.connect(p)
    c.executescript("CREATE TABLE outcomes(run_id TEXT PRIMARY KEY, reason TEXT, net_r REAL, fill REAL, exit REAL, resolved_at TEXT);"
                    "INSERT INTO outcomes VALUES('old','STOP',-1,1,1,'x');")
    c.commit(); c.close()
    c = DB.connect(p)                                                # old ledger gets the new columns, rows kept
    assert c.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0] == 1
    rec = dict(direction="long")
    c.execute("INSERT INTO setups VALUES('r1','2026-11-17T09:00:00+00:00','x','EURUSD','t','M15','2026-11-17',?)", (json.dumps(rec),))
    c.execute("INSERT INTO outcomes(run_id,reason,net_r,fill,exit,resolved_at,gross_r,mfe_r,mae_r) VALUES('r1','STOP',-1.1,1,1,'x',-1.0,0.1,1.0)")
    c.commit()
    assert "wrong way" in D.live_line(c)
