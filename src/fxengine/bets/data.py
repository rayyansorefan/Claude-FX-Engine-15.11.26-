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
    return d[KEEP + ["season"]]


def download(out=Path("data/bets"), divs=DIVS, seasons=SEASONS, get=None, pause=1.0) -> pd.DataFrame:
    import requests
    get = get or (lambda u: requests.get(u, timeout=30, headers={"User-Agent": "research-script"}))
    out.mkdir(parents=True, exist_ok=True)
    frames, gaps = [], []
    for s in seasons:
        for dv in divs:
            try:
                r = get(URL.format(s=s, d=dv))
                if r.status_code != 200:
                    gaps.append(f"{s}/{dv}: HTTP {r.status_code}"); continue
                p = parse(r.content.decode("latin-1"), dv, s)
                if len(p):
                    frames.append(p)
            except Exception as e:                       # one bad file never stops the run; it is listed in the gap report
                gaps.append(f"{s}/{dv}: {type(e).__name__}")
            time.sleep(pause)
    if not frames:
        sys.exit("no data downloaded: " + "; ".join(gaps[:5]))
    df = pd.concat(frames, ignore_index=True).drop_duplicates(["Div", "Date", "HomeTeam", "AwayTeam"])
    df.to_parquet(out / "matches.parquet")
    (out / "gaps.txt").write_text("\n".join(gaps))
    print(f"matches {len(df)} · seasons {df.season.nunique()} · leagues {df.Div.nunique()} · gaps {len(gaps)} · {df.Date.min():%Y-%m-%d} -> {df.Date.max():%Y-%m-%d}")
    return df


if __name__ == "__main__":
    download()
