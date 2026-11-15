"""python -m fxengine.data.oanda_cli [--start 2023-11-01] [--gran M5] [--pairs ...]   (resumable)"""
import argparse, logging, sys
from ..envfile import load_env
from .oanda import download

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-11-01")
    ap.add_argument("--gran", default="M5")
    ap.add_argument("--pairs", default=",".join(PAIRS))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    tok = load_env().get("OANDA_TOKEN")
    if not tok:
        sys.exit("OANDA_TOKEN missing from .env")
    download(tok, a.pairs.split(","), a.gran, a.start)


if __name__ == "__main__":
    main()
