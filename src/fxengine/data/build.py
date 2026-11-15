"""CLI: python -m fxengine.data.build  -> resample stored M1 into M5/M15/H1 + quality report (data/quality.json)."""
import json
from . import store
from .resample import resample
from .quality import quality
from .ctrader import PAIRS


def main():
    rep = {}
    for sym in PAIRS:
        m1 = store.load(sym, "M1")
        if m1.empty:
            continue
        rep[sym] = {"M1": quality(m1, "M1")}
        for tf in ("M5", "M15", "H1"):
            store.merge_save(sym, tf, resample(m1, tf, base="M1"))
    json.dump(rep, open("data/quality.json", "w"), indent=1, default=str)
    print("wrote data/quality.json")


if __name__ == "__main__":
    main()
