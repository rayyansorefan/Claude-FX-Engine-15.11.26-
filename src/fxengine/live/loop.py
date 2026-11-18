"""LIVE RESEARCH LOOP: one supervised process. Every 5 min in market hours: refresh data -> gate freshness -> publish
(<=5/day, one per pair) -> replay every active setup through the SAME Tracker driver as the research rerun -> alert on
state changes only. Zero Claude. Never places orders. State lives in SQLite; setups are re-derived by deterministic
replay so a restart loses nothing.
PYTHONPATH=src python -m fxengine.live.loop"""
from __future__ import annotations
import json, logging, math, time, traceback
from pathlib import Path
import pandas as pd
import requests
from ..envfile import load_env
from ..calendar import market_closed
from ..data import store, oanda
from ..data.resample import resample
from ..engine.costs import CostModel
from ..engine.tracker import Setup, Tracker, RESOLVED, bar_arrays, track_arrays
from . import db as DB, messages as M, telegram, scan as SC

log = logging.getLogger("loop")
FIVE = pd.Timedelta(minutes=5)
MAX_PER_DAY, PUBLISH_HOURS, STALE_MIN = 5, (7, 20), 12.0     # 12 min: one slow fetch must not flip STALE/RECOVERED
ERR_ALERT_EVERY = 36                                          # after the first alert at 3 errors, remind every 3 hours
TFMIN = {"H1": 60, "H4": 240}
HOLD = {"asia_breakout": 32, "trend_pullback": 32, "range_reversion": 24, "E1_strength": 12, "E2_donchian": 40}
SCAN_FILE = Path("data/latest_scan.json")


def refresh(token, root=store.ROOT, start=None):
    start = start or (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    oanda.download(token, SC.PAIRS, "M5", start, root, pause=0.05)
    for sym in SC.PAIRS:
        m5 = store.load(sym, "M5", root, tail=6500)
        if m5.empty:
            continue
        sub = m5[m5.index >= m5.index[max(0, len(m5) - 6000)].ceil("4h")]      # start on a 4h boundary: no partial buckets
        for tf in ("H1", "H4"):
            store.merge_save(sym, tf, resample(sub, tf, base="M5"), root)


def data_age_min(root, now):
    """Age of the OLDEST pair's last closed M5 candle: every stored pair must be fresh, not just EURUSD."""
    ages = []
    for sym in SC.PAIRS:
        m5 = store.load(sym, "M5", root, tail=3)
        if len(m5):
            ages.append((now - (m5.index[-1] + FIVE)).total_seconds() / 60)
    return max(ages) if ages else None


def _num(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def to_setup(c) -> Setup:
    ratio = TFMIN[c["tf"]] // 5
    return Setup(run_id=c["run_id"], symbol=c["pair"], direction=c["direction"], setup_type=c["type"], version="live-v1",
                 created_at=pd.Timestamp(c["created"]), entry=c["entry"], entry_kind=c["entry_kind"], stop=c["stop"], target=c["target"],
                 expires_at=pd.Timestamp(c["expires"]), max_hold_bars=HOLD[c["type"]] * ratio, invalidation=_num(c.get("invalidation")),
                 score=c["score"], reason=c.get("reason", c["type"]))


def load_m5(c, root):
    created = pd.Timestamp(c["created"])
    m5 = store.load(c["pair"], "M5", root, tail=4500)                    # ~15 days: enough for any live setup
    if len(m5) and m5.index[0] > created - FIVE and len(m5) >= 4500:    # older than the window: fall back to the whole file
        m5 = store.load(c["pair"], "M5", root)
    return m5[m5.index + FIVE > created]


def replay(c, root, cost=CostModel(True)):
    """Deterministic replay of one setup over stored M5 bars: the same track_arrays driver as the research rerun."""
    created = pd.Timestamp(c["created"])
    m5 = load_m5(c, root)
    arr = bar_arrays(m5)
    hook = None
    if c.get("exit_rule"):                                               # the exit rule that was in force when this setup was published
        from ..backtest.run_exits import exit_hook
        hook = exit_hook(c["exit_rule"], arr)
    t = track_arrays(to_setup(c), arr, FIVE, cost, after_bar=hook)
    return t, m5


def advice(t, m5, at):
    """Pre-set halfway rule (UNPROVEN): EXIT if the last 3 M5 closes AT THE TIME OF THE EVENT are all beyond the halfway
    level, else HOLD. Only bars closed by `at` are used, so a replay after an outage gives the same advice."""
    half = t.fill - 0.5 * t.s.risk if t.s.direction == "long" else t.fill + 0.5 * t.s.risk
    last = m5[m5.index + FIVE <= pd.Timestamp(at)].bid_c.iloc[-3:]
    beyond = (last < half).all() if t.s.direction == "long" else (last > half).all()
    return ("EXIT", "price keeps closing against you") if beyond else ("HOLD", "price has not settled beyond halfway")


def _alert(conn, env, send, c, idx, kind, text, event_ts, now, expires=None):
    ok = send(env, text)
    sent = pd.Timestamp(now)
    lat = (sent - pd.Timestamp(event_ts)).total_seconds()
    late = int(kind == "NEW" and sent > pd.Timestamp(c["expires"]))
    conn.execute("INSERT OR REPLACE INTO alerts VALUES(?,?,?,?,?,?,?,?,?)", (c["run_id"], idx, kind, str(event_ts), str(sent), lat, late, int(ok), text))
    conn.commit()
    return ok


def publish(conn, env, send, cands, now):
    n_today = conn.execute("SELECT COUNT(*) FROM setups WHERE day=?", (str(now.date()),)).fetchone()[0]
    active_pairs = {s["pair"] for s in DB.active_setups(conn)}
    out = []
    for c in sorted(cands, key=lambda x: -x["score"]):
        if n_today >= MAX_PER_DAY or c["pair"] in active_pairs or not (PUBLISH_HOURS[0] <= now.hour < PUBLISH_HOURS[1]):
            continue
        c = dict(c, run_id=f"live-{c['type']}-{c['pair']}-{pd.Timestamp(c['created']):%Y%m%d%H%M}")
        from ..features import context as CTX
        c["ctx"] = dict(c.get("ctx") or {}, **CTX.exposure(c["pair"], c["direction"], DB.active_setups(conn)))   # correlated setups lose together
        from ..learn import filters as FL
        flt = FL.load()                                                 # ops/filters.json: only filters that passed validation AND were switched on deliberately
        if c["type"] in flt and not FL.passes(c.get("ctx"), flt[c["type"]]):
            DB.kv_set(conn, "filtered_out", int(DB.kv_get(conn, "filtered_out", 0)) + 1)
            continue
        champ = DB.kv_get(conn, "champion_exit")
        if champ:                                                       # stored in the immutable record: this setup keeps its exit rule for life
            c["exit_rule"] = champ
        if DB.add_setup(conn, c["run_id"], c):
            n_today += 1
            active_pairs.add(c["pair"])
            out.append(c)
    return out


def track(conn, env, send, root, now):
    """Replay every active setup; alert on each NEW lifecycle event exactly once."""
    sent = 0
    for c in DB.active_setups(conn):
        t, m5 = replay(c, root)
        have = conn.execute("SELECT COUNT(*) FROM events WHERE run_id=?", (c["run_id"],)).fetchone()[0]
        for idx, ev in enumerate(t.events):
            if idx < have:
                continue
            conn.execute("INSERT INTO events VALUES(?,?,?,?,?,?)", (c["run_id"], idx, str(ev["ts"]), ev["frm"], ev["to"], ev["detail"]))
            if idx == 0:
                _alert(conn, env, send, c, 0, "NEW", M.new(c), ev["ts"], now)
                continue
            if "HALFWAY" in ev["detail"]:                    # must come first: a halfway event carries to_state == TRIGGERED
                a, why = advice(t, m5, ev["ts"])
                txt, kind = M.halfway(c, a, why), "HALFWAY"
            elif ev["to"] == "TRIGGERED" and ev["frm"] == "PUBLISHED":
                txt, kind = M.triggered(c, t.fill), "TRIGGERED"
            elif ev["to"] == RESOLVED:
                o = t.outcome
                conn.execute("INSERT OR REPLACE INTO outcomes(run_id,reason,net_r,fill,exit,resolved_at,gross_r,mfe_r,mae_r) VALUES(?,?,?,?,?,?,?,?,?)",
                             (c["run_id"], o.reason, o.net_r, o.fill, o.exit, str(ev["ts"]), o.gross_r, o.mfe_r, o.mae_r))
                txt, kind = M.resolved(c, o.reason, o.net_r), o.reason
            elif ev["to"] == "ADJUSTED" and ev["frm"] in ("TRIGGERED", "ADJUSTED") and c.get("exit_rule"):
                first = conn.execute("SELECT COUNT(*) FROM events WHERE run_id=? AND to_state='ADJUSTED' AND idx<?", (c["run_id"], idx)).fetchone()[0] == 0
                if not first:                                           # trailing rules move every bar: tell Rayyan once per trade
                    continue
                txt, kind = M.protected(c, ev["detail"]), "PROTECTED"
            else:
                continue
            _alert(conn, env, send, c, idx, kind, txt, ev["ts"], now)
            sent += 1
        conn.commit()
    return sent


def retry_unsent(conn, env, send, now):
    for r in conn.execute("SELECT run_id, idx, text FROM alerts WHERE ok=0").fetchall():
        if send(env, r["text"]):
            conn.execute("UPDATE alerts SET ok=1, sent_at=? WHERE run_id=? AND idx=?", (str(now), r["run_id"], r["idx"]))
    conn.commit()


def _save_scan(res, now):
    try:
        SCAN_FILE.parent.mkdir(exist_ok=True)
        SCAN_FILE.write_text(json.dumps(dict(res, generated=str(now)), indent=1, default=str))
    except OSError as e:
        log.warning("could not write %s: %s", SCAN_FILE, e)


def run_cycle(conn, env, now, send=telegram.send, root=store.ROOT, refresh_fn=None, scan_fn=None):
    t0 = time.time()
    note, ok, status, age = "", 1, "OK", None
    try:
        if market_closed(now):
            conn.execute("INSERT INTO cycles VALUES(?,?,?,?,?,?)", (str(now), 1, "CLOSED", None, 0, "market closed"))
            conn.commit()
            return "CLOSED"
        (refresh_fn or (lambda: refresh(env.get("OANDA_TOKEN"), root)))()
        age = data_age_min(root, now)
        if age is None or age > STALE_MIN:
            ok, status, note = 0, "STALE", f"data age {age}"
            if DB.kv_get(conn, "stale") != "1":
                send(env, M.stale(age or 999))
                DB.kv_set(conn, "stale", 1)
        else:
            if DB.kv_get(conn, "stale") == "1":
                send(env, M.recovered())
                DB.kv_set(conn, "stale", 0)
            key = str(store.last_open("EURUSD", "H1", root))
            if DB.kv_get(conn, "last_scan") != key:
                res = (scan_fn or (lambda: SC.scan(root, now=now)))()
                if isinstance(res, dict):
                    _save_scan(res, now)
                    cands = res["candidates"]
                else:
                    cands = res
                publish(conn, env, send, cands, now)
                DB.kv_set(conn, "last_scan", key)
            track(conn, env, send, root, now)
            retry_unsent(conn, env, send, now)
    except Exception as e:                                   # fail loudly in the ledger, keep the loop alive
        ok, status, note = 0, "ERROR", f"{type(e).__name__}: {e}"
        log.error(traceback.format_exc())
        n = int(DB.kv_get(conn, "consec_err", 0)) + 1
        DB.kv_set(conn, "consec_err", n)
        if n == 3 or n % ERR_ALERT_EVERY == 0:
            send(env, M.engine_error(n, note))
    else:
        if int(DB.kv_get(conn, "consec_err", 0)) >= 3:
            send(env, "🟢 ENGINE RECOVERED · cycles are succeeding again")
        DB.kv_set(conn, "consec_err", 0)
    conn.execute("INSERT INTO cycles VALUES(?,?,?,?,?,?)", (str(now), ok, status, age, round(time.time() - t0, 2), note))
    conn.commit()
    hb = Path("data/heartbeat.json")
    hb.parent.mkdir(exist_ok=True)
    hb.write_text(json.dumps(dict(ts=str(now), status=status, ok=ok)))
    try:                                                              # evidence file for open positions; must never break a cycle
        from .positions import snapshot
        snapshot(conn, root, now)
    except Exception:
        pass
    return status


def ping(env, ok):
    """Off-host dead-man switch (free healthchecks.io): HC_PING_URL in .env. Pinged every cycle; '/fail' on bad cycles.
    If the VM, the network or this process dies, healthchecks.io emails/Telegrams you after its grace period."""
    url = env.get("HC_PING_URL")
    if url:
        try:
            requests.get(url + ("" if ok else "/fail"), timeout=10)
        except requests.RequestException:
            pass


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    env = load_env()
    if not env.get("OANDA_TOKEN"):
        raise SystemExit("OANDA_TOKEN missing from .env")
    if not env.get("HC_PING_URL"):
        log.warning("HC_PING_URL not set: no off-host dead-man alert. Add a free healthchecks.io ping URL to .env.")
    conn = DB.connect()
    from . import schedule
    log.info("live loop started")
    while True:
        now = pd.Timestamp.now(tz="UTC")
        st = run_cycle(conn, env, now)
        schedule.daily_jobs(conn, env, now, root=store.ROOT)
        ping(env, st in ("OK", "CLOSED"))
        nxt = (now.floor("5min") + FIVE + pd.Timedelta(seconds=20))
        time.sleep(max(5, (nxt - pd.Timestamp.now(tz="UTC")).total_seconds()))


if __name__ == "__main__":
    main()
