"""The no-leverage paper account (owner rule: the £2,500 balance is the most that can be in positions at once; no margin).
Every FX setup is still PUBLISHED and SCORED exactly as before (research is unchanged). This module decides how many lots the £2,500 account could actually hold:
  lots held = min(lots for £20 risk, lots whose full value fits in the FREE cash), free cash = balance - value of positions open or waiting to fill.
A setup that finds no free cash is NOT TAKEN in the account (it is still published and scored). One function serves both new setups (at publish time) and the replay of all past/open ones.
Position value = lots x 100,000 base units converted to pounds. Hypothetical only: nothing is ever ordered."""
from __future__ import annotations
import math
import pandas as pd

ACCOUNT = 2500.0
RISK = 20.0
UNITS = 100_000.0
MIN_LOT = 0.01


def gbp_per_base_unit(symbol: str, px: dict) -> float | None:
    """GBP value of ONE unit of the pair's base currency (needs GBPUSD, EURGBP, AUDUSD, NZDUSD as relevant)."""
    try:
        base = symbol[:3]
        if base == "GBP":
            return 1.0
        if base == "USD":
            return 1.0 / px["GBPUSD"]
        if base == "EUR":
            return px["EURGBP"]
        if base == "AUD":
            return px["AUDUSD"] / px["GBPUSD"]
        if base == "NZD":
            return px["NZDUSD"] / px["GBPUSD"]
    except (KeyError, ZeroDivisionError, TypeError):
        return None
    return None


def per_lot_gbp(symbol: str, px: dict) -> float | None:
    g = gbp_per_base_unit(symbol, px)
    return None if g is None else UNITS * g


def affordable_lots(wanted: float, per_lot: float | None, free: float) -> float:
    """Largest 0.01-lot step that is <= the wanted lots and whose full value fits in the free cash (0.0 = cannot afford even the minimum)."""
    if not per_lot or per_lot <= 0 or wanted <= 0 or free <= 0:
        return 0.0
    cap = math.floor(free / per_lot * 100 + 1e-9) / 100
    lots = min(wanted, cap)
    return lots if lots >= MIN_LOT else 0.0


def replay(setups: list[dict], px: dict) -> dict:
    """setups: dicts with run_id, created (ts), end (ts when the cash is released: resolved, expired or invalidated; None = still active), pair, lots (the £20-risk lots),
    net_r (None until resolved), per_lot (optional, GBP value of one lot; else from px) and lots_account (optional: a decision already stored at publish time, kept as is).
    Walks them in creation order. Returns {run_id: dict(lots, value, scale, taken, why)} where scale = lots held / lots for £20 risk (multiplies that setup's £ result)."""
    rows = sorted(setups, key=lambda s: pd.Timestamp(s["created"]))
    out: dict = {}
    for s in rows:
        t = pd.Timestamp(s["created"])
        realised = 0.0
        exposure = 0.0
        for o in rows:
            if o is s or o["run_id"] not in out:
                continue
            d = out[o["run_id"]]
            e = o.get("end")
            if e is not None and pd.Timestamp(e) <= t:
                if d["taken"] and o.get("net_r") is not None:
                    realised += float(o["net_r"]) * RISK * d["scale"]
            elif d["taken"]:
                exposure += d["value"]
        free = ACCOUNT + realised - exposure
        want = float(s.get("lots") or 0.0)
        pl = s.get("per_lot") or per_lot_gbp(s["pair"], px)
        if s.get("lots_account") is not None and pl:
            lots = float(s["lots_account"])                      # decided at publish time: kept
        else:
            lots = affordable_lots(want, pl, free)
        taken = lots >= MIN_LOT and bool(pl)
        out[s["run_id"]] = dict(lots=lots if taken else 0.0, value=(lots * pl) if taken else 0.0, scale=(lots / want) if (taken and want) else 0.0, taken=taken,
                                free_before=round(free, 2), why="" if taken else ("no free cash in the £2,500 account" if pl else "no price to value the position"))
    return out


def exposure_now(replayed: dict, setups: list[dict]) -> float:
    """Value of positions currently open or waiting to fill (setups with no end)."""
    ids = {s["run_id"] for s in setups if s.get("end") is None}
    return sum(d["value"] for i, d in replayed.items() if i in ids and d["taken"])


def rows_from_db(conn) -> list[dict]:
    """Every published setup as a replay row: created, the time its cash is released (outcome time, else still active), lots, result in R, stored publish-time decision."""
    import json
    out = []
    for r in conn.execute("SELECT s.run_id, s.record, o.reason, o.net_r, o.resolved_at FROM setups s LEFT JOIN outcomes o USING(run_id)"):
        rec = json.loads(r["record"])
        out.append(dict(run_id=r["run_id"], pair=rec["pair"], created=rec["created"], end=r["resolved_at"] if r["reason"] else None, lots=rec.get("lots_for_20gbp_risk"),
                        net_r=r["net_r"], per_lot=rec.get("per_lot_gbp"), lots_account=rec.get("lots_account")))
    return out


def free_cash_now(conn, px: dict) -> float:
    """Free cash of the no-leverage account right now: balance (start + results so far) minus positions open or waiting to fill."""
    rows = rows_from_db(conn)
    rp = replay(rows, px)
    realised = sum(float(r["net_r"]) * RISK * rp[r["run_id"]]["scale"] for r in rows if r["end"] is not None and r["net_r"] is not None and rp[r["run_id"]]["taken"])
    return ACCOUNT + realised - exposure_now(rp, rows)
