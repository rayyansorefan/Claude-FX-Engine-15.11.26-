"""Walk-forward windows and a NEVER-TOUCHED holdout, enforced in code.
research_view() hides everything at/after HOLDOUT_START. open_holdout() can run ONCE and
leaves a permanent log line in docs/holdout_log.txt (committed)."""
from __future__ import annotations
from pathlib import Path
import pandas as pd

HOLDOUT_START = pd.Timestamp("2026-05-15", tz="UTC")   # last ~6 months of history; fixed in GATES.md
LOG = Path("docs/holdout_log.txt")


def research_view(df: pd.DataFrame) -> pd.DataFrame:
    return df[df.index < HOLDOUT_START]


def open_holdout(df: pd.DataFrame, why: str, log: Path = LOG) -> pd.DataFrame:
    if log.exists() and log.read_text().strip():
        raise RuntimeError("holdout already opened once; it cannot be reused:\n" + log.read_text())
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f"{pd.Timestamp.now(tz='UTC')} holdout opened: {why}\n")
    return df[df.index >= HOLDOUT_START]


def walk_forward_windows(start, end, train_days=180, test_days=30):
    """Rolling windows: (train_start, train_end, test_end). Test never overlaps train.
    Windows are clipped to the holdout boundary."""
    def _utc(x):
        x = pd.Timestamp(x)
        return x.tz_localize('UTC') if x.tzinfo is None else x
    start, end = _utc(start), min(_utc(end), HOLDOUT_START)
    out, t = [], start
    while t + pd.Timedelta(days=train_days + test_days) <= end:
        te = t + pd.Timedelta(days=train_days)
        out.append((t, te, te + pd.Timedelta(days=test_days)))
        t += pd.Timedelta(days=test_days)
    return out
