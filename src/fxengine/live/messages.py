"""Alert text. Rule: max 3 short lines, plain English, always states UNPROVEN where relevant."""
from ..engine.costs import pip

GBP_PER_R = 20.0


def p(sym, v):
    return f"{v:.3f}" if sym.endswith("JPY") else f"{v:.5f}"


def hhmm(ts):
    return str(ts)[11:16]


def why(c) -> str:
    """First sentence of the setup's reason, kept short for a phone screen."""
    r = str(c.get("reason") or c["type"]).split("\n")[0].split(";")[0]
    return r if len(r) <= 58 else r[:55] + "..."


def new(c) -> str:
    inv = c.get("invalidation")
    cancel = f" · cancel if close {'<=' if c['direction'] == 'long' else '>='} {p(c['pair'], inv)}" if inv is not None else ""
    return (f"🟢 NEW · {c['pair']} {c['direction'].upper()} · {c['tf']} {c['type']} · UNPROVEN\n"
            f"{c['entry_kind'].title()} {p(c['pair'], c['entry'])} · stop {p(c['pair'], c['stop'])} · target {p(c['pair'], c['target'])} · "
            f"{c['lots_for_20gbp_risk']} lots (£20 risk)\n"
            f"{why(c)} · expires {hhmm(c['expires'])} UTC{cancel}")


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
