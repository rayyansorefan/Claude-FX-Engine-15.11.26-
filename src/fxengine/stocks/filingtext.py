"""Read the WORDS of each company's latest earnings releases (SEC 8-K Item 2.02, Exhibit 99). Deterministic: a fixed word list, no model.
For the latest release and the one before it: tone (positive vs negative language, Loughran-McDonald style), guidance direction (raised / lowered / reaffirmed), and red flags (going concern, restatement, material weakness, impairment, investigation).
Output docs/results/stocks_filingtext.json, one record per company, plus an append-only log data/stocks/filingtext_log.jsonl so the scores can be tested against what happened AFTER each release (the only honest test: history has no archived text).
Information only: never changes a setup or paper trade until a pre-registered test says it should.
Usage on the VM: PYTHONPATH=src python -m fxengine.stocks.filingtext"""
from __future__ import annotations
import html
import json
import re
import time
from pathlib import Path
from .events import earnings_8ks, sec_contact, _http, EDGAR

POS = set("""achieve achieved achievement benefit benefited best better breakthrough confident delivered exceed exceeded excellent gain gains growth improve improved improvement leading momentum opportunity outperform outperformed
positive profitable profitability record robust solid strength strong stronger strongest success successful surpass surpassed tailwind upside accelerate accelerated expansion""".split())
NEG = set("""adverse against challenge challenges challenging closure decline declined declines decrease decreased deteriorate deterioration difficult disappointing downturn drop dropped headwind headwinds impairment lawsuit layoffs
loss losses lower lowered negative pressure pressures reduce reduced reduction restructuring risk risks shortfall slowdown slowing struggle uncertain uncertainty unfavorable volatile weak weaker weakness weakened worse writedown""".split())
RAISE = ("raise", "raised", "raising", "increase", "increased", "increasing", "above", "higher", "improved", "upward")
LOWER = ("lower", "lowered", "lowering", "reduce", "reduced", "reducing", "below", "cut", "cuts", "withdraw", "withdrew", "withdrawn", "suspend", "suspended", "downward")
FLAGS = ("going concern", "substantial doubt", "restatement", "restate", "material weakness", "investigation", "subpoena", "delisting", "default", "covenant", "impairment charge", "recall")


def clean(raw: str) -> str:
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def analyse(text: str) -> dict:
    words = re.findall(r"[a-z']+", text.lower())
    n = len(words)
    if n < 200:
        return dict(words=n, ok=False)
    pos, neg = sum(w in POS for w in words), sum(w in NEG for w in words)
    sents = re.split(r"(?<=[.!?])\s+", text.lower())
    gs = [s for s in sents if re.search(r"\b(guidance|outlook|expects?|expected|forecast|full[- ]year)\b", s) and re.search(r"\d", s)]
    up = sum(any(re.search(rf"\b{w}\b", s) for w in RAISE) for s in gs)
    dn = sum(any(re.search(rf"\b{w}\b", s) for w in LOWER) for s in gs)
    low = text.lower()
    flags = [f for f in FLAGS if f in low]
    guide = "no guidance found" if not gs else "RAISED" if up > dn + 0 and up >= 1 and dn == 0 else "LOWERED" if dn > up and dn >= 1 else "mixed / reaffirmed"
    return dict(ok=True, words=n, pos=pos, neg=neg, tone=round((pos - neg) / n * 100, 3), guidance=guide, guidance_sentences=len(gs), flags=flags)


def exhibit_url(index: dict, cik: str, acc: str) -> str | None:
    """Pick the press-release exhibit (ex99 / ex-99) from a filing's index.json."""
    names = [i["name"] for i in (index.get("directory") or {}).get("item", []) if i.get("name")]
    for n in names:
        if re.search(r"(?i)ex[-_]?99[-_.]?1|ex99", n) and n.lower().endswith((".htm", ".html", ".txt")):
            return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{n}"
    return None


def latest_two(sub: dict) -> list[dict]:
    r = (sub.get("filings") or {}).get("recent") or {}
    rows = [dict(date=d, acc=a) for f, d, it, a in zip(r.get("form", []), r.get("filingDate", []), r.get("items", []), r.get("accessionNumber", [])) if f == "8-K" and "2.02" in str(it).split(",")]
    return sorted(rows, key=lambda x: x["date"])[-2:]


def read_release(get, cik: str, acc: str, pause: float = 0.2) -> dict | None:
    st, b = get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/index.json")
    time.sleep(pause)
    if st != 200:
        return None
    url = exhibit_url(json.loads(b), cik, acc)
    if not url:
        return None
    st, b = get(url)
    time.sleep(pause)
    if st != 200:
        return None
    return analyse(clean((b if isinstance(b, str) else b.decode("utf-8", "replace"))[:600_000]))


def main(root: Path = Path("."), get=None, out: Path = Path("docs/results/stocks_filingtext.json"), max_age_days: int = 5, limit: int = 0):
    get = get or (lambda u: _http(u, sec_contact(root)))
    d = root / EDGAR
    prev = json.loads(out.read_text()).get("companies", {}) if out.exists() else {}
    res, log = dict(prev), []
    files = sorted(d.glob("*_sub.json"))
    for f in files[:limit or None]:
        sym = f.name[:-len("_sub.json")]
        try:
            sub = json.loads(f.read_text())
            two = latest_two(sub)
            if not two:
                continue
            if prev.get(sym, {}).get("latest_date") == two[-1]["date"]:
                continue                                          # already read this release
            cik = str(sub.get("cik") or "").zfill(10)
            cur = read_release(get, cik, two[-1]["acc"])
            old = read_release(get, cik, two[0]["acc"]) if len(two) == 2 else None
            if not cur or not cur.get("ok"):
                continue
            rec = dict(latest_date=two[-1]["date"], **cur)
            if old and old.get("ok"):
                rec["tone_change"] = round(cur["tone"] - old["tone"], 3)
                rec["prior_guidance"] = old["guidance"]
            res[sym] = rec
            log.append(dict(symbol=sym, **rec))
            print(sym, rec["latest_date"], rec["tone"], rec["guidance"], rec["flags"], flush=True)
        except Exception as e:
            print(sym, "FAILED", type(e).__name__, flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(note="information only; word-list reading of the latest earnings release", companies=res)))
    if log:
        lp = root / "data/stocks/filingtext_log.jsonl"
        lp.parent.mkdir(parents=True, exist_ok=True)
        with lp.open("a") as fh:
            for r in log:
                fh.write(json.dumps(r) + "\n")
    print(len(res), "companies read,", len(log), "new")
    return res


if __name__ == "__main__":
    main()
