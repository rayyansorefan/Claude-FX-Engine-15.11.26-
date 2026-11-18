"""Entry-filter study (the FX engine's method, adapted for stocks). Does a market/stock condition recorded when a setup fires separate the winning setups from the losing ones?
Pre-registered: 15 named conditions + all their pairs (120), fixed thresholds. Per rule: CHOOSE the best filter on the EARLIER 60% of the research window, VALIDATE it ONCE on the LATER 40%.
Throughput guard: a filter must keep at least half of the setups (it may never starve the engine). A filter counts as helpful only if, on the unseen later 40%, trades it keeps
beat the unfiltered average and the 95% range (clustered by week) of that improvement is above zero. Nothing is applied automatically: adoption is a written decision (ops/stocks_filters.json).
Every feature at a trade uses data up to the close of the signal day only."""
from __future__ import annotations
import itertools
import json
from pathlib import Path
import numpy as np
import pandas as pd
from . import indicators as I

KEEP_MIN = 0.50            # throughput guard
MIN_KEPT = 150             # trades the filter must keep in selection
SELECT_T = 3.0             # selection needs a clear signal before a filter is even put forward
FILTERS = {                # name -> (columns needed, description, function(features) -> bool Series)
    "M_up": (["spy_trend"], "S&P 500 in an uptrend", lambda f: f.spy_trend > 0),
    "M_calm": (["vol20"], "S&P volatility under 25%", lambda f: f.vol20 < 0.25),
    "M_breadth": (["breadth200"], "over half the stocks above their 200-day", lambda f: f.breadth200 > 0.5),
    "M_spy_dip": (["spy_5d"], "the market itself fell over the last week", lambda f: f.spy_5d < -0.01),
    "M_vix_not_high": (["vix_z"], "VIX not unusually high", lambda f: f.vix_z < 1.5),
    "M_vix_up": (["vix_z"], "VIX above its yearly average (fear)", lambda f: f.vix_z > 0),
    "M_usd_calm": (["usd_20d_z"], "US dollar not surging", lambda f: f.usd_20d_z < 1.5),
    "M_risk_on": (["risk_20d_z"], "risk mood (AUDJPY) not collapsing", lambda f: f.risk_20d_z > -1.0),
    "S_vol_mid": (["atr_ratio"], "the stock's volatility near normal", lambda f: f.atr_ratio.between(0.7, 1.6)),
    "S_deep": (["ext_sma20"], "stretched 1+ ATR below its 20-day average", lambda f: f.ext_sma20 <= -1.0),
    "S_trend_strong": (["trend_with"], "5%+ above its 200-day average", lambda f: f.trend_with > 0.05),
    "S_rs_pos": (["rs3m"], "beating the market over 3 months", lambda f: f.rs3m > 0),
    "S_post_earn_wait": (["dse"], "not within 3 days after its earnings release", lambda f: f.dse.isna() | (f.dse >= 3)),
    "S_relvol_hi": (["relvol"], "volume 20%+ above normal", lambda f: f.relvol > 1.2),
    "D_not_monday": (["dow"], "not a Monday", lambda f: f.dow != 0),
}


def stock_features(panel: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Per symbol, per bar: volatility ratio, stretch, trend, relative strength, relative volume. Past data only."""
    spy = panel.get("spy.us")
    out = {}
    for s, d in panel.items():
        c = d["close"]
        a = I.atr(d["high"], d["low"], c, 14)
        ap = a / c
        f = pd.DataFrame(index=d.index)
        f["atr_ratio"] = ap / ap.rolling(250, min_periods=120).median()
        f["ext_sma20"] = (c - I.sma(c, 20)) / a
        f["trend_with"] = c / I.sma(c, 200) - 1
        f["relvol"] = d["volume"] / I.sma(d["volume"], 20)
        f["rs3m"] = (c / c.shift(63) - 1) - ((spy["close"] / spy["close"].shift(63) - 1).reindex(d.index, method="ffill") if spy is not None else 0.0)
        out[s] = f
    return out


def attach_features(tr: pd.DataFrame, panel: dict, ctx: pd.DataFrame, events: pd.DataFrame | None) -> pd.DataFrame:
    """One row per trade with the context as of the CLOSE BEFORE entry (the signal day)."""
    if tr.empty:
        return tr
    sf = stock_features(panel)
    rows = []
    for s, g in tr.groupby("symbol"):
        d = panel[s]
        pos = d.index.get_indexer(pd.DatetimeIndex(g["entry_date"])) - 1                  # the signal bar = the bar before the entry bar
        ok = pos >= 0
        f = sf[s].iloc[np.where(ok, pos, 0)].reset_index(drop=True)
        f.index = g.index
        f["sig_date"] = d.index[np.where(ok, pos, 0)]
        f.loc[~ok, :] = np.nan
        rows.append(f.assign(symbol=s))
    feat = pd.concat(rows).sort_index()
    out = tr.join(feat.drop(columns=["symbol"]))
    c = ctx.reindex(pd.DatetimeIndex(out["sig_date"]), method="ffill") if not ctx.empty else pd.DataFrame(index=range(len(out)))
    c.index = out.index
    for col in c.columns:
        out[col] = c[col]
    out["dse"] = np.nan
    if events is not None and len(events):
        e = events.sort_values("announce_date")
        for s, g in out.groupby("symbol"):
            es = e[e["symbol"] == s]["announce_date"].to_numpy()
            if len(es):
                k = np.searchsorted(es, g["sig_date"].to_numpy(), side="left") - 1
                days = (g["sig_date"].to_numpy() - es[np.clip(k, 0, None)]).astype("timedelta64[D]").astype(float)
                out.loc[g.index, "dse"] = np.where(k >= 0, days, np.nan)
    return out


def candidate_filters(feat: pd.DataFrame) -> dict[str, np.ndarray]:
    """All singles and pairs whose columns exist (and are not all missing) in this data set -> boolean keep-masks."""
    singles = {}
    for name, (cols, _, fn) in FILTERS.items():
        if all(c in feat.columns and feat[c].notna().mean() > 0.5 for c in cols if c != "dse"):
            singles[name] = fn(feat).fillna(False).to_numpy(bool)
    out = dict(singles)
    for a, b in itertools.combinations(sorted(singles), 2):
        out[f"{a} & {b}"] = singles[a] & singles[b]
    return out


def _welch_t(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 30 or len(b) < 30:
        return float("nan")
    return float((a.mean() - b.mean()) / np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b) + 1e-18))


def _cluster_improvement(r: np.ndarray, keep: np.ndarray, weeks: np.ndarray, n=3000, seed=11) -> tuple[float, float]:
    """95% range (clustered by week) of mean(kept) - mean(all)."""
    keys, inv = np.unique(weeks, return_inverse=True)
    k = len(keys)
    sa, ca = np.bincount(inv, weights=r, minlength=k), np.bincount(inv, minlength=k).astype(float)
    sk, ck = np.bincount(inv, weights=r * keep, minlength=k), np.bincount(inv, weights=keep.astype(float), minlength=k)
    rng = np.random.default_rng(seed)
    out = np.empty(n)
    for i in range(0, n, 500):
        idx = rng.integers(0, k, size=(min(500, n - i), k))
        out[i:i + 500] = sk[idx].sum(1) / np.maximum(ck[idx].sum(1), 1) - sa[idx].sum(1) / ca[idx].sum(1)
    return float(np.quantile(out, 0.025)), float(np.quantile(out, 0.975))


def study(rule: str, tr: pd.DataFrame) -> dict:
    """Choose on the earlier 60%, validate once on the later 40%. `tr` must have entry_date, gross and the feature columns."""
    if len(tr) < 1500:
        return dict(rule=rule, n=int(len(tr)), verdict="too few trades for a filter study")
    tr = tr.sort_values("entry_date").reset_index(drop=True)
    cut = int(len(tr) * 0.6)
    a, b = tr.iloc[:cut], tr.iloc[cut:]
    ma = candidate_filters(a)
    ra = a["gross"].to_numpy(float)
    best = None
    for name, keep in ma.items():
        if keep.mean() < KEEP_MIN or keep.sum() < MIN_KEPT:
            continue
        t = _welch_t(ra[keep], ra[~keep]) if (~keep).sum() >= 30 else float("nan")
        if t == t and (best is None or t > best[1]):
            best = (name, t, float(ra[keep].mean()), float(keep.mean()))
    base = dict(rule=rule, n=int(len(tr)), n_candidates=len(ma), selected_on=f"{a['entry_date'].min():%Y-%m-%d}..{a['entry_date'].max():%Y-%m-%d}", validated_on=f"{b['entry_date'].min():%Y-%m-%d}..{b['entry_date'].max():%Y-%m-%d}",
                baseline_selection=round(float(ra.mean()), 5))
    if best is None or best[1] < SELECT_T:
        return dict(base, verdict="no filter stood out on the earlier 60%", best_t=None if best is None else round(best[1], 2))
    name = best[0]
    mb = candidate_filters(b).get(name)
    if mb is None:
        return dict(base, filter=name, verdict="the filter's data is missing in the later 40%")
    rb = b["gross"].to_numpy(float)
    kept_share = float(mb.mean())
    lo, hi = _cluster_improvement(rb, mb, b["entry_date"].dt.strftime("%G-%V").to_numpy())
    imp = float(rb[mb].mean() - rb.mean())
    ok = kept_share >= KEEP_MIN and lo > 0
    return dict(base, filter=name, selection=dict(t=round(best[1], 2), kept_mean=round(best[2], 5), kept_share=round(best[3], 3)),
                validation=dict(baseline=round(float(rb.mean()), 5), kept_mean=round(float(rb[mb].mean()), 5), removed_mean=round(float(rb[~mb].mean()), 5) if (~mb).sum() else None, kept_share=round(kept_share, 3),
                                improvement=round(imp, 5), ci_lo=round(lo, 5), ci_hi=round(hi, 5)),
                verdict=("HELPFUL on unseen data: candidate to adopt (a written decision is still required)" if ok else "did NOT hold up on unseen data"))


def main(path=Path("data/stocks/prices.parquet"), res_path=Path("docs/results/stocks.json"), out=Path("docs/results")):
    from . import crossctx as CX, events as EV, run as R, strategies as S
    root = Path(path).parent.parent.parent
    panel = R.load_panel(path)
    events = EV.load(root)
    ctx = CX.build(panel, CX.load_fx(root / "data/stocks/raw"), EV.load_fred(root))
    res = json.loads(Path(res_path).read_text())
    rules = [r["rule"] for r in res["rules"] if r.get("passes") and r["rule"] in S.SWING_RULES]
    results = []
    for rule in rules:
        tr = R.rule_trades(rule, panel, events)
        feat = attach_features(tr, panel, ctx, events)
        results.append(study(rule, feat))
        print(rule, "->", results[-1].get("verdict"), flush=True)
    doc = dict(filters={k: v[1] for k, v in FILTERS.items()}, results=results)
    out.mkdir(parents=True, exist_ok=True)
    (out / "stocks_filters.json").write_text(json.dumps(doc, indent=1, default=str))
    return doc


if __name__ == "__main__":
    main()


def parse_expr(expr: str) -> list[str]:
    return [x.strip() for x in expr.split("&") if x.strip()]


def passes(expr: str, feats: dict) -> bool | None:
    """Does ONE setup (a dict of its recorded context + stock features) satisfy a named filter such as 'M_usd_calm & S_trend_strong'? None if a needed number is missing."""
    f = pd.DataFrame([feats])
    for name in parse_expr(expr):
        cols, _, fn = FILTERS[name]
        need = [c for c in cols if c != "dse"]
        if any(c not in f.columns or pd.isna(f.iloc[0][c]) for c in need):
            return None
        if "dse" in cols and "dse" not in f.columns:
            f["dse"] = np.nan
        if not bool(fn(f).iloc[0]):
            return False
    return True


def load_candidates(path: Path = Path("ops/stocks_filter_candidates.json")) -> dict[str, str]:
    """Filters that held up in the study but are only CANDIDATES: they tag setups and are measured live; they never remove one."""
    return json.loads(path.read_text()) if path.exists() else {}
