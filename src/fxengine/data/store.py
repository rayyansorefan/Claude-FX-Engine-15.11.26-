"""Parquet store: data/<SYMBOL>/<TF>.parquet. Merge is idempotent (dedupe by open time)."""
from pathlib import Path
import pandas as pd

ROOT = Path("data/candles")


def path(symbol: str, tf: str, root: Path = ROOT) -> Path:
    return Path(root) / symbol / f"{tf}.parquet"


def load(symbol: str, tf: str, root: Path = ROOT) -> pd.DataFrame:
    p = path(symbol, tf, root)
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def merge_save(symbol: str, tf: str, new: pd.DataFrame, root: Path = ROOT) -> pd.DataFrame:
    old = load(symbol, tf, root)
    df = pd.concat([old, new]) if len(old) else new
    df = df[~df.index.duplicated(keep="last")].sort_index()
    p = path(symbol, tf, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p)
    return df


def last_open(symbol: str, tf: str, root: Path = ROOT):
    df = load(symbol, tf, root)
    return df.index.max() if len(df) else None
