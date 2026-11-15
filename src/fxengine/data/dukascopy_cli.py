"""python -m fxengine.data.dukascopy_cli --start 2023-11-01 [--end yesterday] [--pairs EURUSD,...]"""
import argparse, logging
import pandas as pd
from .dukascopy import download

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-11-01")
    ap.add_argument("--end", default=str((pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=1)).date()))
    ap.add_argument("--pairs", default=",".join(PAIRS))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    download(a.pairs.split(","), a.start, a.end)


if __name__ == "__main__":
    main()
