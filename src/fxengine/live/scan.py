"""Live scan (research only). Refreshes M5 from OANDA practice (read-only), rebuilds H1/H4, and lists any
signals that fired on the LATEST CLOSED bar using the frozen rules. Deterministic, zero Claude.
EVERY candidate is labelled UNPROVEN: all these rules FAILED the backtests (docs/REJECTED.md).
Usage: PYTHONPATH=src python -m fxengine.live.scan"""
from __future__ import annotations
import json, logging
from pathlib import Path
import pandas as pd
from ..envfile import load_env
from ..data import store, oanda
from ..data.resample import resample
from ..data.timeframes import tf_delta
from ..features.indicators import prepare
from ..engine.costs import BASE_SPREAD_PIPS
from ..setups import v1, v2
from .sizing import lots_for_risk

PAIRS = list(BASE_SPREAD_PIPS)
NOTE = "UNPROVEN: this rule failed its backtest. Research only."


def refresh(token, root=store.ROOT):
    oanda.download(token, PAIRS, "M5", "2023-11-01", root)
    for sym in PAIRS:
        m5 = store.load(sym, "M5", root)
        for tf in ("H1", "H4"):
            store.merge_save(sym, tf, resample(m5, tf, base="M5"), root)


def _cands(sym, d, tf, kind, sig, now, px):
    out = []
    last = len(d) - 1
    for r in sig[sig.pos == last].itertuples():
        created = d.index[r.pos] + tf_delta(tf)
        lots, stop_pips = lots_for_risk(sym, r.entry, r.stop, px)
        inv = getattr(r, "invalidation", float("nan"))
        out.append(dict(pair=sym, type=kind, tf=tf, direction=r.direction, entry_kind=r.kind,
                        entry=round(float(r.entry), 5), stop=round(float(r.stop), 5), target=round(float(r.target), 5),
                        created=str(created), expires=str(created + int(r.expiry_bars) * tf_delta(tf)),
                        invalidation=None if inv != inv else round(float(inv), 5), reason=str(getattr(r, "reason", kind)),
                        stop_pips=round(stop_pips, 1), lots_for_20gbp_risk=lots, score=round(float(r.score), 2),
                        note=NOTE))
    return out


def scan(root=store.ROOT, now=None, max_age_min=None):
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    root = Path(root)
    px, frames = {}, {"H1": {}, "H4": {}}
    last_m5 = None
    for sym in PAIRS:
        m5 = store.load(sym, "M5", root)
        if m5.empty:
            continue
        px[sym] = float(m5.bid_c.iloc[-1])
        last_m5 = max(last_m5 or m5.index[-1], m5.index[-1])
        for tf in ("H1", "H4"):
            frames[tf][sym] = prepare(store.load(sym, tf, root))
    age_min = None if last_m5 is None else (now - (last_m5 + pd.Timedelta(minutes=5))).total_seconds() / 60
    cands = []
    if age_min is not None and age_min <= (max_age_min or 90):
        for sym, d in frames["H1"].items():
            for kind in v1.TYPES:
                cands += _cands(sym, d, "H1", kind, v1.GENERATORS[kind](d), now, px)
        for sym, d in frames["H4"].items():
            cands += _cands(sym, d, "H4", "E2_donchian", v2.donchian_trend(d), now, px)
        for sym, sig in v2.strength_signals(frames["H4"]).items():
            cands += _cands(sym, frames["H4"][sym], "H4", "E1_strength", sig, now, px)
    cands.sort(key=lambda c: -c["score"])
    return dict(generated=str(now), last_candle_close=None if last_m5 is None else str(last_m5 + pd.Timedelta(minutes=5)),
                data_age_min=None if age_min is None else round(age_min, 1), candidates=cands[:5], total_found=len(cands),
                status="OK" if age_min is not None and age_min <= 15 else ("STALE" if age_min is not None else "NO DATA"))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    tok = load_env().get("OANDA_TOKEN")
    if not tok:
        raise SystemExit("OANDA_TOKEN missing from .env")
    refresh(tok)
    res = scan()
    Path("data").mkdir(exist_ok=True)
    json.dump(res, open("data/latest_scan.json", "w"), indent=1)
    print(f"Data status: {res['status']} (last candle closed {res['last_candle_close']}, age {res['data_age_min']} min)")
    if res["status"] != "OK":
        print("Market closed or data stale: no candidates. (Forex reopens Sunday ~22:00 UTC.)")
    for c in res["candidates"]:
        print(f"{c['pair']} {c['direction'].upper()} [{c['type']} {c['tf']}] {c['entry_kind']} {c['entry']} | stop {c['stop']} "
              f"({c['stop_pips']} pips) | target {c['target']} | expires {c['expires'][11:16]} UTC | {c['lots_for_20gbp_risk']} lots = £20 risk")
    print(f"{res['total_found']} candidate(s) found; showing up to 5. {NOTE}")
    print("NOTE: the live loop (fxengine.live.loop) does this every 5 minutes and writes the same file; this command is for a manual check.")


if __name__ == "__main__":
    main()
