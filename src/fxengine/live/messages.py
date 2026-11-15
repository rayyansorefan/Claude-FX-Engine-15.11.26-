"""Alert text. Rule: max 3 short lines, plain English, always states UNPROVEN where relevant."""
from ..engine.costs import pip

GBP_PER_R = 20.0


def p(sym, v):
    return f"{v:.3f}" if sym.endswith("JPY") else f"{v:.5f}"


def hhmm(ts):
    return str(ts)[11:16]


def why(c) -> str:
    """First line of the setup's reason, shortened for a phone screen."""
    r = str(c.get("reason") or c["type"]).split("\n")[0]
    return r if len(r) <= 90 else r[:87] + "..."


def new(c) -> str:
    inv = c.get("invalidation")
    cancel = f" · Cancel if close {'<=' if c['direction'] == 'long' else '>='} {p(c['pair'], inv)}" if inv is not None else ""
    return (f"🟢 NEW · {c['pair']} {c['direction'].upper()} ({c['tf']} {c['type']}) · {why(c)}\n"
            f"{c['entry_kind'].title()} entry {p(c['pair'], c['entry'])} · Stop {p(c['pair'], c['stop'])} · Target {p(c['pair'], c['target'])} · "
            f"{c['lots_for_20gbp_risk']} lots (£20 risk)\n"
            f"Expires {hhmm(c['expires'])} UTC{cancel} · UNPROVEN: this rule failed its backtests")


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
