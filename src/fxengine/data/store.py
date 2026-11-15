"""Parquet store: data/<SYMBOL>/<TF>.parquet. Merge is idempotent (dedupe by open time).
Writes are ATOMIC (temp file + os.replace) and SERIALISED (fcntl lock per file), so a reader never sees a
half-written file and two processes (live loop + research run) cannot lose each other's rows."""
import fcntl, os, threading
from pathlib import Path
import pandas as pd

ROOT = Path("data/candles")


def path(symbol: str, tf: str, root: Path = ROOT) -> Path:
    return Path(root) / symbol / f"{tf}.parquet"


def load(symbol: str, tf: str, root: Path = ROOT) -> pd.DataFrame:
    p = path(symbol, tf, root)
    if not p.exists():
        return pd.DataFrame()
    with open(p, "rb") as f:          # ONE open: pyarrow would otherwise reopen the path for pages after reading the
        return pd.read_parquet(f)     # footer, and see a different version if a writer replaced the file in between


def merge_save(symbol: str, tf: str, new: pd.DataFrame, root: Path = ROOT) -> pd.DataFrame:
    p = path(symbol, tf, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p.with_suffix(".lock"), "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        old = load(symbol, tf, root)
        df = pd.concat([old, new]) if len(old) else new
        df = df[~df.index.duplicated(keep="last")].sort_index()
        tmp = p.with_name(f"{p.name}.tmp{os.getpid()}-{threading.get_ident()}")
        df.to_parquet(tmp)
        os.replace(tmp, p)
    return df


def last_open(symbol: str, tf: str, root: Path = ROOT):
    df = load(symbol, tf, root)
    return df.index.max() if len(df) else None
