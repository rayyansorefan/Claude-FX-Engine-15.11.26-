"""No-look-ahead trade simulator. Entry and exit prices are OPENS (day rules: open and close of the same bar). Exits are decided at a close and executed
at the next open, so there is no intrabar ambiguity. Trades touching a probable data-error bar are dropped; a trade still open at the end of the data is dropped."""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import costs
from .data import BAD_MOVE
from .strategies import Sig


def swing_trades(o: np.ndarray, sig: Sig, bad_cum: np.ndarray, return_open: bool = False):
    """Returns (signal_bar, entry_bar, exit_bar): signal at the close of i, buy open of i+1, sell open of the bar after the exit condition (or after max_hold)."""
    n, res, i = len(o), [], 0
    while i < n - 1:
        if not sig.entry[i]:
            i += 1
            continue
        e, x = i + 1, None
        for j in range(e, min(e + sig.max_hold - 1, n - 2) + 1):
            if sig.exit[j] or j == e + sig.max_hold - 1:
                x = j + 1
                break
        if x is None:
            if return_open:
                return res, i                                  # signal bar of the trade still open at the end of the data
            break                                              # ran out of data: still open, not scored
        if bad_cum[x + 1] - bad_cum[i + 1] == 0:
            res.append((i, e, x))
        i = x
    return (res, None) if return_open else res


def trades_for(sym: str, d: pd.DataFrame, sig: Sig) -> pd.DataFrame:
    """All trades of one rule on one symbol: columns symbol, entry_date, exit_date, gross, bars."""
    o, c = d["open"].to_numpy(float), d["close"].to_numpy(float)
    dates = d.index.to_numpy()
    bad = np.r_[False, np.abs(c[1:] / c[:-1] - 1.0) > BAD_MOVE]
    bad_cum = np.r_[0, np.cumsum(bad)]
    rows = []
    if sig.max_hold == 0:                                      # day trade: open -> close of the same bar
        for t in np.flatnonzero(sig.entry):
            if t >= 1 and not bad[t]:
                rows.append((sym, dates[t], dates[t], c[t] / o[t] - 1.0, 0))
    else:
        for i, e, x in swing_trades(o, sig, bad_cum):
            rows.append((sym, dates[e], dates[x], o[x] / o[e] - 1.0, x - e))
    return pd.DataFrame(rows, columns=["symbol", "entry_date", "exit_date", "gross", "bars"])


def add_net(tr: pd.DataFrame, kinds: dict[str, str]) -> pd.DataFrame:
    """Adds net_normal and net_stressed columns (and keeps gross)."""
    if tr.empty:
        return tr.assign(net_normal=[], net_stressed=[])
    k = tr["symbol"].map(kinds)
    out = tr.copy()
    for mode in ("normal", "stressed"):
        cb = k.map(lambda x: costs.side_costs(x, mode)[0]).to_numpy(float)
        cs = k.map(lambda x: costs.side_costs(x, mode)[1]).to_numpy(float)
        out[f"net_{mode}"] = (1.0 + tr["gross"].to_numpy(float)) * (1.0 - cs) / (1.0 + cb) - 1.0
    return out
