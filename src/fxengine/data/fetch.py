"""CLI: python -m fxengine.data.fetch [--years 3] [--tfs M5,M15,H1] [--pairs EURUSD,...]
Reads keys from .env (CTRADER_CLIENT_ID, CTRADER_CLIENT_SECRET, CTRADER_ACCESS_TOKEN, CTRADER_LOGIN).
Resumable: re-running only fetches what is new."""
import argparse, logging, sys
from twisted.internet import reactor
from ..envfile import load_env
from .ctrader import fetch_all, PAIRS

REQUIRED = ["CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_ACCESS_TOKEN"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=3)
    ap.add_argument("--tfs", default="M5,M15,H1")
    ap.add_argument("--pairs", default=",".join(PAIRS))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    env = load_env()
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")
    d = fetch_all(env, a.pairs.split(","), a.tfs.split(","), a.years)
    d.addErrback(lambda f: (logging.error("FAILED: %s", f.getErrorMessage()), setattr(main, "rc", 1)))
    d.addBoth(lambda _: reactor.stop())
    reactor.run()
    sys.exit(getattr(main, "rc", 0))


if __name__ == "__main__":
    main()
