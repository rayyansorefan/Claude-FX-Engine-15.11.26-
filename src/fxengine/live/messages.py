"""Alert text. Rule: max 3 short lines, plain English, always states UNPROVEN where relevant."""
from ..engine.costs import pip

GBP_PER_R = 20.0


def p(sym, v):
    return f"{v:.3f}" if sym.endswith("JPY") else f"{v:.5f}"


def hhmm(ts):
    """HH:MM in UK time (alerts are read in the UK). Timestamps are stored in UTC."""
    import pandas as pd
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t
    return f"{t.tz_convert('Europe/London'):%H:%M}"


def why(c) -> str:
    """First sentence of the setup's reason, kept short for a phone screen."""
    r = str(c.get("reason") or c["type"]).split("\n")[0].split(";")[0]
    return r if len(r) <= 58 else r[:55] + "..."


def _size(c) -> str:
    """Lots for the £2,500 account with NO leverage (position value never above the free cash); older records without it keep the old wording."""
    la = c.get("lots_account")
    if la is None:
        return f"{c['lots_for_20gbp_risk']} lots (£20 risk)"
    if c.get("suspended"):
        return "NOT TAKEN: this strategy is on probation (live results clearly below zero). Published and scored anyway."
    if la <= 0:
        return "NOT AFFORDABLE: no free cash in the £2,500 account (published and scored anyway)"
    pl = c.get("per_lot_gbp") or 0
    return f"{la} lots = £{la * pl:,.0f} (no leverage; £20-risk size was {c['lots_for_20gbp_risk']})"


def new(c) -> str:
    inv = c.get("invalidation")
    cancel = f" · cancel if close {'<=' if c['direction'] == 'long' else '>='} {p(c['pair'], inv)}" if inv is not None else ""
    return (f"🟢 NEW · {c['pair']} {c['direction'].upper()} · {c['tf']} {c['type']} · UNPROVEN\n"
            f"Entry {p(c['pair'], c['entry'])} ({c['entry_kind']} order) · stop-loss {p(c['pair'], c['stop'])} · target {p(c['pair'], c['target'])} · "
            f"{_size(c)}\n"
            f"{why(c)} · expires {hhmm(c['expires'])} UK{cancel}")


def triggered(c, fill) -> str:
    return (f"▶️ TRIGGERED · {c['pair']} {c['direction'].upper()} (hypothetical fill {p(c['pair'], fill)})\n"
            f"Stop {p(c['pair'], c['stop'])} · Target {p(c['pair'], c['target'])}")


def halfway(c, advice, why_) -> str:
    return (f"⚠️ HALFWAY · {c['pair']} {c['direction'].upper()} · -£{GBP_PER_R / 2:.0f}\n"
            f"Advice: {advice} (unproven) · {why_}")


def resolved(c, reason, net_r) -> str:
    gbp = net_r * GBP_PER_R
    head = {"TARGET": "✅ TARGET HIT", "STOP": "❌ STOPPED OUT", "TIMEOUT": "⌛ TIME EXIT", "EXPIRED": "⌛ EXPIRED (never triggered)",
            "INVALIDATED": "🚫 INVALIDATED (never triggered)"}[reason]
    if reason in ("EXPIRED", "INVALIDATED"):
        return f"{head} · {c['pair']} {c['direction'].upper()}\nNo trade taken."
    return f"{head} · {c['pair']} {c['direction'].upper()} · {gbp:+.0f} GBP ({net_r:+.1f}R)\nHypothetical, after costs."


def protected(c, detail) -> str:
    """The champion exit rule moved the stop to protect profit (first move only)."""
    import re
    m = re.search(r"stop=([0-9.]+)", detail)
    return (f"🔒 PROFIT PROTECTED · {c['pair']} {c['direction'].upper()}\n"
            f"Stop moved to {m.group(1) if m else '?'} by the exit rule in force ({c.get('exit_rule', '?')}). UNPROVEN.")


def stale(age) -> str:
    return f"🔴 DATA STALE · last price {age:.0f} min old\nNo new setups until fresh data returns."


def recovered() -> str:
    return "🟢 DATA FRESH AGAIN · scanning resumed"


def engine_error(n: int, note: str) -> str:
    """Error alert that says exactly what to do. A 401 means the OANDA token is no longer valid (only one can exist)."""
    if "401" in note:
        return (f"🔴 OANDA TOKEN REJECTED (x{n}) · no new prices\n"
                "Fix: OANDA > Manage API Access > Revoke > Generate. On the server run: bash ~/fx/deploy/set_token.sh\n"
                "Do not create a token anywhere else, it cancels this one.")
    return f"🔴 ENGINE ERROR x{n} · {note[:80]}\nLoop is alive but failing: no new setups until this is fixed."
