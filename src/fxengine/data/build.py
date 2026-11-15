"""python -m fxengine.data.build -> resample stored M5 into M15/H1 + quality report (data/quality.json)."""
import json
from pathlib import Path
from . import store
from .resample import resample
from .quality import quality
from .oanda_cli import PAIRS


def main():
    rep = {}
    for sym in PAIRS:
        m5 = store.load(sym, "M5")
        if m5.empty:
            continue
        rep[sym] = {"M5": quality(m5, "M5")}
        for tf in ("M15", "H1"):
            out = resample(m5, tf, base="M5")
            store.merge_save(sym, tf, out)
            rep[sym][tf] = quality(out, tf)
    Path("data").mkdir(exist_ok=True)
    json.dump(rep, open("data/quality.json", "w"), indent=1, default=str)
    print("wrote data/quality.json for", ", ".join(rep) or "nothing")


if __name__ == "__main__":
    main()
