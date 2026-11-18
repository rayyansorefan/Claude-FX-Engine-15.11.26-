"""Entry filters ("confluence"): named, pre-registered conditions on the market context recorded when a setup fires.
Used by the offline entry study (selection + validation) and by the live publisher (only filters listed in ops/filters.json, which is version-controlled)."""
from __future__ import annotations
import itertools, json
from pathlib import Path
import numpy as np
import pandas as pd

_A = {                                     # name -> (columns needed, function(DataFrame) -> boolean Series)
    "vol_not_low": (["atr_rank"], lambda d: d.atr_rank >= 0.30),
    "vol_not_high": (["atr_rank"], lambda d: d.atr_rank <= 0.80),
    "vol_mid": (["atr_rank"], lambda d: d.atr_rank.between(0.25, 0.75)),
    "trend_with_pos": (["trend_with"], lambda d: d.trend_with > 0),
    "trend_with_strong": (["trend_with"], lambda d: d.trend_with > 1.0),
    "not_extended": (["ext_ema20"], lambda d: d.ext_ema20 <= 1.5),
    "near_ema20": (["ext_ema20"], lambda d: d.ext_ema20 <= 0.8),
    "htf_with": (["htf_align"], lambda d: d.htf_align == 1),
    "htf_not_against": (["htf_align"], lambda d: d.htf_align >= 0),
    "london_ny_hours": (["hour_utc"], lambda d: d.hour_utc.between(7, 16)),
    "not_friday": (["dow"], lambda d: d.dow != 4),
    "not_monday": (["dow"], lambda d: d.dow != 0),
}
ATOMS = {k: v[1] for k, v in _A.items()}
FILE = Path("ops/filters.json")


def _needs(a):
    return _A[a][0]


def mask(d: pd.DataFrame, atoms) -> pd.Series:
    """Rows of a research frame that pass ALL atoms. A missing column means the atom cannot hold, so nothing passes."""
    m = pd.Series(True, index=d.index)
    for a in atoms:
        ok = _A[a][1](d) if all(c in d for c in _needs(a)) else pd.Series(False, index=d.index)
        m &= ok.fillna(False)
    return m


def candidates():
    """Every single atom and every pair of atoms (fixed, pre-registered family)."""
    names = list(ATOMS)
    return [(n,) for n in names] + list(itertools.combinations(names, 2))


def passes(ctx: dict, atoms) -> bool:
    """Live check for ONE setup. A context value that was not recorded makes the filter not evaluable: the setup is allowed (frozen behaviour wins)."""
    if not atoms:
        return True
    row = pd.DataFrame([ctx or {}])
    for a in atoms:
        if not all(c in row.columns and pd.notna(row[c].iloc[0]) for c in _needs(a)):
            continue
        if not bool(ATOMS[a](row).iloc[0]):
            return False
    return True


def load(path: Path = FILE) -> dict:
    """{setup type: [atoms]} from the version-controlled file; unknown atoms are ignored (never crash a live cycle)."""
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return {t: [a for a in v.get("atoms", []) if a in ATOMS] for t, v in raw.items() if isinstance(v, dict) and v.get("active")}
