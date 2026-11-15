"""Setup lifecycle state machine. THE SAME CODE runs backtest, replay and live: it is fed
CLOSED bars one at a time (never a forming bar). Decisions are stamped with the bar CLOSE time.
Executable-side prices: long entry/exit use ask/bid; short use bid/ask (ask = bid + spread).
Conservative same-bar rule: stop beats target; on the entry bar only the stop can fire.
States: PUBLISHED -> TRIGGERED -> (ADJUSTED) -> RESOLVED(reason)."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
import pandas as pd
from .costs import CostModel, pip, rollover_nights

PUBLISHED, TRIGGERED, ADJUSTED, RESOLVED = "PUBLISHED", "TRIGGERED", "ADJUSTED", "RESOLVED"
TARGET, STOP, EXPIRED, INVALIDATED, TIMEOUT = "TARGET", "STOP", "EXPIRED", "INVALIDATED", "TIMEOUT"


@dataclass(frozen=True)
class Setup:                      # immutable published record
    run_id: str
    symbol: str
    direction: str                # "long" | "short"
    setup_type: str
    version: str
    created_at: pd.Timestamp      # close time of the bar that produced it
    entry: float                  # trigger level
    entry_kind: str               # "limit" (pullback to level) | "stop" (breakout through level)
    stop: float
    target: float
    expires_at: pd.Timestamp      # untriggered setups die here
    max_hold_bars: int            # triggered trades exit at close after this many bars
    invalidation: Optional[float] = None   # pre-trigger: bar CLOSE beyond this cancels (long: <=, short: >=)
    score: float = 0.0
    reason: str = ""

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)


@dataclass(frozen=True)
class Bar:
    open_time: pd.Timestamp
    close_time: pd.Timestamp      # = open_time + timeframe
    o: float
    h: float
    l: float
    c: float                      # BID prices


@dataclass
class Outcome:
    run_id: str
    reason: str
    fill: Optional[float] = None
    exit: Optional[float] = None
    gross_r: float = 0.0
    cost_r: float = 0.0           # commission + swap (spread/slippage are inside fill/exit prices)
    net_r: float = 0.0
    bars_held: int = 0
    mfe_r: float = 0.0
    mae_r: float = 0.0


class Tracker:
    def __init__(self, setup: Setup, cost: CostModel):
        self.s, self.cost = setup, cost
        self.state = PUBLISHED
        self.stop, self.target = setup.stop, setup.target     # may be adjusted; setup record never changes
        self.events = [dict(ts=setup.created_at, frm=None, to=PUBLISHED, detail="published")]
        self.outcome: Optional[Outcome] = None
        self.fill = self.fill_time = None
        self.bars_held = 0
        self.mfe = self.mae = 0.0
        self._half = False

    # ---- helpers
    def _log(self, ts, to, detail):
        self.events.append(dict(ts=ts, frm=self.state, to=to, detail=detail))
        self.state = to

    @property
    def active(self):
        return self.state != RESOLVED

    def _long(self):
        return self.s.direction == "long"

    def _ask(self, b, x):  # convert a BID price on bar b to the ask side
        return x + self.cost.spread(self.s.symbol, b.open_time)

    # ---- public
    def adjust(self, ts, stop=None, target=None, detail="adjusted"):
        assert self.state in (TRIGGERED, ADJUSTED), "can only adjust a live trade"
        self.stop = self.stop if stop is None else stop
        self.target = self.target if target is None else target
        self._log(ts, ADJUSTED, f"{detail}: stop={self.stop} target={self.target}")

    def on_bar(self, b: Bar):
        if not self.active or b.close_time <= self.s.created_at:
            return []
        n0 = len(self.events)
        if self.state == PUBLISHED:
            self._pre_trigger(b)
        else:
            self._manage(b, entry_bar=False)
        return self.events[n0:]

    # ---- pre-trigger
    def _pre_trigger(self, b: Bar):
        s, sp, slip = self.s, self.cost.spread(self.s.symbol, b.open_time), self.cost.slippage(self.s.symbol, b.open_time)
        if b.close_time > s.expires_at:
            return self._resolve(s.expires_at, EXPIRED, None)
        if self._long():
            ao, al, ah = b.o + sp, b.l + sp, b.h + sp
            hit = al <= s.entry if s.entry_kind == "limit" else ah >= s.entry
            fill = min(s.entry, ao) if s.entry_kind == "limit" else max(s.entry, ao) + slip
        else:
            bo, bl, bh = b.o, b.l, b.h
            hit = bh >= s.entry if s.entry_kind == "limit" else bl <= s.entry
            fill = max(s.entry, bo) if s.entry_kind == "limit" else min(s.entry, bo) - slip
        if hit:
            self.fill, self.fill_time = fill, b.open_time
            self._log(b.close_time, TRIGGERED, f"filled {fill:.5f}")
            return self._manage(b, entry_bar=True)
        # not triggered: invalidation / target-before-entry
        if s.invalidation is not None and ((self._long() and b.c <= s.invalidation) or (not self._long() and b.c >= s.invalidation)):
            return self._resolve(b.close_time, INVALIDATED, None, "closed beyond invalidation")
        reached = (b.h >= s.target) if self._long() else (b.l + sp <= s.target)
        if reached:
            return self._resolve(b.close_time, INVALIDATED, None, "target reached before entry")

    # ---- live trade
    def _manage(self, b: Bar, entry_bar: bool):
        s, sp, slip = self.s, self.cost.spread(self.s.symbol, b.open_time), self.cost.slippage(self.s.symbol, b.open_time)
        risk = s.risk
        if not entry_bar:
            self.bars_held += 1
        if self._long():                       # exits on BID
            stop_hit, tgt_hit = b.l <= self.stop, b.h >= self.target
            stop_px, tgt_px = min(self.stop, b.o) - slip, max(self.target, b.o)
            fav, adv, close_px = b.h - self.fill, self.fill - b.l, b.c
        else:                                  # exits on ASK
            ah, al, ao, ac = b.h + sp, b.l + sp, b.o + sp, b.c + sp
            stop_hit, tgt_hit = ah >= self.stop, al <= self.target
            stop_px, tgt_px = max(self.stop, ao) + slip, min(self.target, ao)
            fav, adv, close_px = self.fill - al, ah - self.fill, ac
        self.mfe, self.mae = max(self.mfe, fav / risk), max(self.mae, adv / risk)
        if stop_hit:
            return self._resolve(b.close_time, STOP, stop_px, exit_time=b.close_time)
        if tgt_hit and not entry_bar:
            return self._resolve(b.close_time, TARGET, tgt_px, exit_time=b.close_time)
        if self.bars_held >= s.max_hold_bars:
            return self._resolve(b.close_time, TIMEOUT, close_px, exit_time=b.close_time)
        if not self._half and adv / risk >= 0.5:
            self._half = True
            self.events.append(dict(ts=b.close_time, frm=self.state, to=self.state, detail="HALFWAY: adverse >= 0.5R"))

    def _resolve(self, ts, reason, exit_px, detail="", exit_time=None):
        s = self.s
        o = Outcome(s.run_id, reason)
        if self.fill is not None and exit_px is not None:
            sign = 1 if self._long() else -1
            risk = s.risk
            o.fill, o.exit = self.fill, exit_px
            o.gross_r = sign * (exit_px - self.fill) / risk
            nights = rollover_nights(self.fill_time, exit_time or ts)
            o.cost_r = (self.cost.commission(s.symbol) + nights * self.cost.swap_per_night(s.symbol)) / risk
            o.net_r = o.gross_r - o.cost_r
            o.bars_held, o.mfe_r, o.mae_r = self.bars_held, self.mfe, self.mae
        self.outcome = o
        self._log(ts, RESOLVED, f"{reason} {detail}".strip())


def run_setup(setup: Setup, bars: pd.DataFrame, tf_delta: pd.Timedelta, cost: CostModel) -> Tracker:
    """Backtest/replay driver: bars = DataFrame (index = open time, cols bid_o,bid_h,bid_l,bid_c)."""
    t = Tracker(setup, cost)
    for ot, r in bars.iterrows():
        if not t.active:
            break
        t.on_bar(Bar(ot, ot + tf_delta, r.bid_o, r.bid_h, r.bid_l, r.bid_c))
    return t
