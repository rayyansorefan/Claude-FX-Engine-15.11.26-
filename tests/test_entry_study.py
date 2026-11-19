import json
import numpy as np, pandas as pd
from fxengine.backtest import run_entry_study as ES
from fxengine.learn import filters as FL


def _trades(n=4000, seed=0, effect=0.0):
    rng = np.random.default_rng(seed)
    created = pd.date_range("2023-11-01", periods=n, freq="4h", tz="UTC")
    df = pd.DataFrame(dict(symbol=rng.choice(["EURUSD", "GBPUSD", "USDJPY"], n), type="asia_breakout", created=created, reason="STOP",
                           trig_stressed=True, trig_measured=True, atr_rank=rng.random(n), trend_with=rng.normal(1, 1.5, n), ext_ema20=np.abs(rng.normal(1, .7, n)),
                           htf_align=rng.choice([-1, 0, 1], n), hour_utc=created.hour, dow=created.day_of_week))
    df["day"] = df.symbol + "-" + df.created.dt.strftime("%Y%m%d")
    base = rng.normal(-0.15, 1.0, n) + effect * (df.htf_align == 1)               # a real, stable effect when effect > 0
    df["net_r_stressed"], df["net_r_measured"] = base, base + 0.03
    return df


def test_filter_atoms_apply_to_frames_and_live_contexts():
    d = _trades(50)
    assert FL.mask(d, ["htf_with"]).equals(d.htf_align == 1)
    assert FL.passes(dict(htf_align=1, atr_rank=.5), ["htf_with", "vol_mid"]) and not FL.passes(dict(htf_align=-1), ["htf_with"])
    assert FL.passes({}, ["htf_with"])                                            # not evaluable -> frozen behaviour (setup is allowed)
    assert FL.mask(d.drop(columns=["htf_align"]), ["htf_with"]).sum() == 0        # research frames without the column cannot pass


def test_a_real_effect_is_found_and_validated_on_unseen_trades():
    r = ES.evaluate(_trades(effect=0.5), n_tests=5)
    assert any(a.startswith("htf") for a in r["filter"]) and r["passes"] and r["validation"]["stressed"]["delta"] > 0.05


def test_pure_noise_rarely_passes():
    passes = sum(bool(ES.evaluate(_trades(seed=s), n_tests=5).get("passes")) for s in range(1, 7))
    assert passes <= 1                                                            # 78 candidates searched, but validation is a single test on unseen data


def test_live_filter_file_ignores_unknown_atoms_and_inactive_entries(tmp_path):
    p = tmp_path / "f.json"
    p.write_text(json.dumps(dict(asia_breakout=dict(active=True, atoms=["htf_with", "bogus"]), trend_pullback=dict(active=False, atoms=["htf_with"]))))
    assert FL.load(p) == {"asia_breakout": ["htf_with"]} and FL.load(tmp_path / "missing.json") == {}


def test_live_publisher_applies_only_switched_on_filters(tmp_path, monkeypatch):
    from fxengine.live import loop as L, db as DB
    conn = DB.connect(tmp_path / "e.db")
    now = pd.Timestamp("2026-11-18 10:00", tz="UTC")
    def cand(pair, htf):
        return dict(pair=pair, type="asia_breakout", tf="H1", direction="long", entry_kind="stop", entry=1.1, stop=1.09, target=1.12, created=str(now), expires=str(now + pd.Timedelta(hours=8)),
                    stop_pips=100, lots_for_20gbp_risk=0.02, score=1.0, reason="r", ctx=dict(htf_align=htf, atr_rank=.5))
    monkeypatch.setattr(FL, "load", lambda *a, **k: {})
    assert len(L.publish(conn, {}, lambda *a: True, [cand("EURUSD", -1)], now)) == 1                  # no filter on: frozen behaviour
    monkeypatch.setattr(FL, "load", lambda *a, **k: {"asia_breakout": ["htf_with"]})
    assert L.publish(conn, {}, lambda *a: True, [cand("GBPUSD", -1)], now) == []                      # filtered out
    assert len(L.publish(conn, {}, lambda *a: True, [cand("USDJPY", 1)], now)) == 1                    # passes the filter
    assert DB.kv_get(conn, "filtered_out") == "1"


def test_the_deployed_filter_file_is_valid_and_only_uses_known_conditions():
    raw = json.loads(open("ops/filters.json").read())
    for rule, spec in raw.items():
        assert set(spec["atoms"]) <= set(FL.ATOMS) and len(spec["atoms"]) <= 2           # max two conditions: no stacked vetoes
    assert FL.load("ops/filters.json") == {k: v["atoms"] for k, v in raw.items() if v.get("active")}
