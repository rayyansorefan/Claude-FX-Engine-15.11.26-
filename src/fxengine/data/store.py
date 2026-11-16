"""Parquet store: data/<SYMBOL>/<TF>.parquet. Merge is idempotent (dedupe by open time).
Writes are ATOMIC (temp file + os.replace) and SERIALISED (fcntl lock per file), so a reader never sees a
half-written file and two processes (live loop + research run) cannot lose each other's rows."""
import fcntl, os, threading
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path("data/candles")


def path(symbol: str, tf: str, root: Path = ROOT) -> Path:
    return Path(root) / symbol / f"{tf}.parquet"


ROW_GROUP = 2048      # small row groups let readers fetch only the newest rows (the live loop and dashboard need ~1% of the file)


def load(symbol: str, tf: str, root: Path = ROOT, tail: int = None) -> pd.DataFrame:
    """Whole file, or just the newest rows (at least `tail`; a multiple of ROW_GROUP) when tail is given."""
    p = path(symbol, tf, root)
    if not p.exists():
        return pd.DataFrame()
    with open(p, "rb") as f:          # ONE open: pyarrow would otherwise reopen the path for pages after reading the
        if tail is None:              # footer, and see a different version if a writer replaced the file in between
            return pd.read_parquet(f)
        pf = pq.ParquetFile(f)
        n = pf.metadata.num_row_groups
        sizes = [pf.metadata.row_group(i).num_rows for i in range(n)]
        got, k = 0, n
        while k > 0 and got < tail:                   # take row groups from the end until we have enough rows
            k -= 1
            got += sizes[k]
        df = pf.read_row_groups(list(range(k, n))).to_pandas()
        return df.tail(max(tail, 1)) if len(df) > tail else df


def merge_save(symbol: str, tf: str, new: pd.DataFrame, root: Path = ROOT) -> pd.DataFrame:
    p = path(symbol, tf, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p.with_suffix(".lock"), "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        old = load(symbol, tf, root)
        df = pd.concat([old, new]) if len(old) else new
        df = df[~df.index.duplicated(keep="last")].sort_index()
        tmp = p.with_name(f"{p.name}.tmp{os.getpid()}-{threading.get_ident()}")
        df.to_parquet(tmp, row_group_size=ROW_GROUP)
        os.replace(tmp, p)
    return df


def last_open(symbol: str, tf: str, root: Path = ROOT):
    df = load(symbol, tf, root, tail=1)
    return df.index.max() if len(df) else None
