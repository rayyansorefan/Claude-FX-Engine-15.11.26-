"""Free historical football results + bookmaker odds from football-data.co.uk (public CSVs; Bet365 + Pinnacle + market columns).
Research only: nothing here touches Bet365. Run on the VM: python -m fxengine.bets.data   -> data/bets/matches.parquet"""
from __future__ import annotations
import io, sys, time
from pathlib import Path
import pandas as pd

URL = "https://www.football-data.co.uk/mmz4281/{s}/{d}.csv"
DIVS = ["E0", "E1", "E2", "E3", "EC", "SC0", "SC1", "D1", "D2", "SP1", "SP2", "I1", "I2", "F1", "F2", "N1", "B1", "P1", "T1", "G1"]
SEASONS = [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in range(2012, 2027)]            # 1213 .. 2627
KEEP = ["Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR", "B365H", "B365D", "B365A", "PSH", "PSD", "PSA", "PSCH", "PSCD", "PSCA",
        "B365CH", "B365CD", "B365CA", "MaxH", "MaxD", "MaxA", "AvgH", "AvgD", "AvgA", "B365>2.5", "B365<2.5", "P>2.5", "P<2.5",
        "B365C>2.5", "B365C<2.5", "PC>2.5", "PC<2.5", "Max>2.5", "Max<2.5", "Avg>2.5", "Avg<2.5"]


TEXT_COLS = {"Div", "Date", "HomeTeam", "AwayTeam", "FTR"}


def parse(text: str, div: str, season: str) -> pd.DataFrame:
    d = pd.read_csv(io.StringIO(text), on_bad_lines="skip")
    d = d.dropna(subset=[c for c in ("HomeTeam", "AwayTeam", "FTR") if c in d.columns]) if "HomeTeam" in d else pd.DataFrame()
    if d.empty:
        return d
    for c in KEEP:
        if c not in d:
            d[c] = float("nan")
    d["Date"] = pd.to_datetime(d["Date"], dayfirst=True, errors="coerce", format="mixed")
    d = d.dropna(subset=["Date"])
    d["Div"], d["season"] = div, season
    for c in KEEP:                                       # some files store odds as text ('2.21', ' ', '-'): force numbers, bad cells become NaN
        if c not in TEXT_COLS:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    return d[KEEP + ["season"]]


def download(out=Path("data/bets"), divs=DIVS, seasons=SEASONS, get=None, pause=0.5) -> pd.DataFrame:
    """Every raw file is saved to <out>/raw as it arrives, so a crash never loses downloads and a rerun skips what is already there.
    A file that does not exist (HTTP 404) leaves a .missing marker so it is not asked for again. Progress is printed per file."""
    import requests
    get = get or (lambda u: requests.get(u, timeout=30, headers={"User-Agent": "research-script"}))
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    frames, gaps, todo = [], [], [(s, dv) for s in seasons for dv in divs]
    for k, (s, dv) in enumerate(todo, 1):
        f, miss = raw / f"{s}_{dv}.csv", raw / f"{s}_{dv}.missing"
        try:
            if miss.exists():
                continue
            if not f.exists():
                r = get(URL.format(s=s, d=dv))
                time.sleep(pause)
                if r.status_code == 404:
                    miss.write_text("404"); print(f"[{k}/{len(todo)}] {s}/{dv} not published", flush=True); continue
                if r.status_code != 200:
                    gaps.append(f"{s}/{dv}: HTTP {r.status_code}"); print(f"[{k}/{len(todo)}] {s}/{dv} HTTP {r.status_code}", flush=True); continue
                f.write_bytes(r.content)
            p = parse(f.read_bytes().decode("latin-1"), dv, s)
            if len(p):
                frames.append(p)
            print(f"[{k}/{len(todo)}] {s}/{dv} {len(p)} rows", flush=True)
        except Exception as e:                           # one bad file never stops the run; it is listed in the gap report
            gaps.append(f"{s}/{dv}: {type(e).__name__}: {str(e)[:80]}"); print(f"[{k}/{len(todo)}] {s}/{dv} FAILED {type(e).__name__}", flush=True)
    if not frames:
        sys.exit("no data downloaded: " + "; ".join(gaps[:5]))
    df = pd.concat(frames, ignore_index=True).drop_duplicates(["Div", "Date", "HomeTeam", "AwayTeam"])
    df.to_parquet(out / "matches.parquet")
    (out / "gaps.txt").write_text("\n".join(gaps))
    print(f"matches {len(df)} · seasons {df.season.nunique()} · leagues {df.Div.nunique()} · gaps {len(gaps)} · {df.Date.min():%Y-%m-%d} -> {df.Date.max():%Y-%m-%d}")
    return df


if __name__ == "__main__":
    download()
