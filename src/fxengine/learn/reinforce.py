"""Autonomous reinforcement (deterministic, zero Claude at runtime). Pre-registered in docs/LEARNING.md.
Every strategy has a WEIGHT = its expected result per trade in R, learned from two sources and updated every night:
    weight = (prior_mean * K + sum of live results) / (K + live trades)
  prior = the strategy's result on years of history (R0, stressed costs, thousands of trades); K = 40 trades' worth of trust in that history.
  So a few live trades nudge the weight and many live trades take over.
What the weight DOES (reversible, recomputed from scratch every time):
  FAVOURED  weight >= -0.05R : first call on the daily setup slots and on free cash.
  NORMAL                     : ordered by weight after the favoured ones.
  REDUCED   weight < -0.20R  : taken at HALF size.
  NOT TAKEN weight < -0.30R  : still published and scored (research untouched) but not taken in the account.
It never raises the £20 risk cap and never changes a rule, gate, stop or target. All strategies are net losers in research: FAVOURED means 'least bad', not 'proven profitable'."""
from __future__ import annotations
import json
from . import scorecard as SC

PRIOR = {                                     # (mean R per trade, trades) from the M5 rerun (R0) / entry study, stressed costs; overwritten by docs/results/entries.json when present
    "asia_breakout": (-0.132, 1305), "trend_pullback": (-0.151, 1033), "range_reversion": (-0.165, 841),
    "E1_strength": (-0.055, 253), "E2_donchian": (-0.118, 200),
}
K_PRIOR = 40
FAVOURED_AT, REDUCE_BELOW, STOP_BELOW = -0.05, -0.20, -0.30
DEFAULT_PRIOR = (-0.15, 0)


def _prior(path="docs/results/entries.json") -> dict:
    p = dict(PRIOR)
    try:
        for k, v in json.load(open(path))["rules"].items():
            m = v.get("base_all", {}).get("stressed")
            if m is not None and v.get("n"):
                p[k] = (float(m), int(v["n"]))
    except Exception:
        pass
    return p


def action(w: float) -> str:
    return "NOT TAKEN" if w < STOP_BELOW else "REDUCED" if w < REDUCE_BELOW else "FAVOURED" if w >= FAVOURED_AT else "NORMAL"


def weights(conn, prior: dict | None = None) -> dict[str, dict]:
    prior = prior or _prior()
    live = SC.collect(conn)
    out = {}
    MIN_LIVE_TRADES = 15  # Match scorecard.py MIN_JUDGE; don't reduce/stop until we have enough data
    for t in set(prior) | set(live):
        pm = prior.get(t, DEFAULT_PRIOR)[0]
        rs = live.get(t, [])
        w = (pm * K_PRIOR + sum(rs)) / (K_PRIOR + len(rs))
        # With fewer than 15 live trades, treat as NORMAL (never REDUCED or NOT_TAKEN): early data is noisy
        act = action(w) if len(rs) >= MIN_LIVE_TRADES else ("NORMAL" if action(w) in ("REDUCED", "NOT TAKEN") else action(w))
        out[t] = dict(w=w, n=len(rs), wins=sum(x > 0 for x in rs), live_mean=(sum(rs) / len(rs) if rs else None), prior=pm, action=act)
    return out


def order_key(wts: dict, c: dict):
    """Sort key for candidates: higher weight first, then the rule's own score."""
    return (-wts.get(c["type"], {}).get("w", DEFAULT_PRIOR[0]), -float(c.get("score") or 0))


def size_factor(wts: dict, typ: str) -> float:
    a = wts.get(typ, {}).get("action", "NORMAL")
    return 0.0 if a == "NOT TAKEN" else 0.5 if a == "REDUCED" else 1.0


def nightly(conn, now) -> list[str]:
    """Called once a night. Logs and announces ONLY changes of action, so the owner sees the engine adapting (and why)."""
    from ..live import db as DB
    wts = weights(conn)
    prev = json.loads(DB.kv_get(conn, "reinforce_actions") or "{}")
    msgs = ["\n".join(summary_lines(conn))] if not prev else []          # the very first night announces the starting position
    for t, v in sorted(wts.items()):
        if prev.get(t) is not None and prev[t] != v["action"]:
            live = "" if not v["n"] else f" Live: {v['wins']} wins in {v['n']} trades ({v['live_mean']:+.2f}R each)."
            msgs.append(f"🧭 LEARNING · {t} {prev[t]} → {v['action']} (weight {v['w']:+.2f}R, history {v['prior']:+.2f}R).{live}")
            conn.execute("INSERT INTO learning_log VALUES(?,?,?)", (str(now), "REINFORCE", f"{t}: {prev[t]} -> {v['action']} w={v['w']:+.3f}"))
    DB.kv_set(conn, "reinforce_actions", json.dumps({t: v["action"] for t, v in wts.items()}))
    conn.commit()
    return msgs


def summary_lines(conn) -> list[str]:
    w = weights(conn)
    order = sorted(w.items(), key=lambda kv: -kv[1]["w"])
    fav = [k for k, v in order if v["action"] == "FAVOURED"]
    bad = [k for k, v in order if v["action"] in ("REDUCED", "NOT TAKEN")]
    return ["🧭 REINFORCEMENT · favoured (first call on slots and cash): " + (", ".join(fav) or "none") + ".",
            "Reduced or not taken: " + (", ".join(f"{k} ({w[k]['action'].lower()})" for k in bad) or "none") + ".",
            "Weights = history plus live trades, updated nightly. Least bad, not proven profitable."]
