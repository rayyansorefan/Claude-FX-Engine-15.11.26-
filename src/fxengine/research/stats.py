"""Honest statistics. All in R units (1R = planned risk). Seeded => reproducible.
2026-11-15: added cluster (block) bootstrap by day, minimum detectable effect, and a random-entry challenger test."""
from __future__ import annotations
from statistics import NormalDist
import numpy as np


def expectancy(r) -> float:
    r = np.asarray(r, float)
    return float(r.mean()) if len(r) else float("nan")


def bootstrap_ci(r, alpha=0.05, n=10000, seed=7):
    """Percentile bootstrap CI of the mean (trades treated as independent). Returns (lo, hi)."""
    r = np.asarray(r, float)
    if len(r) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = rng.choice(r, size=(n, len(r)), replace=True).mean(axis=1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def cluster_bootstrap_ci(r, clusters, alpha=0.05, n=10000, seed=7):
    """Block bootstrap: whole clusters (e.g. pair-days or days) are resampled with replacement, so trades that
    overlap in time do not pretend to be independent. Returns (lo, hi) of the mean."""
    r, cl = np.asarray(r, float), np.asarray(clusters)
    keys, inv = np.unique(cl, return_inverse=True)
    k = len(keys)
    if k < 2:
        return (float("nan"), float("nan"))
    sums, cnts = np.bincount(inv, weights=r, minlength=k), np.bincount(inv, minlength=k).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, k, size=(n, k))
    means = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def adjusted_alpha(n_trials: int, alpha=0.05) -> float:
    """Bonferroni multiple-testing penalty: every variant ever tried counts."""
    return alpha / max(1, n_trials)


def min_detectable_effect(r, alpha_one_sided: float, n_eff: int | None = None) -> float:
    """Smallest true expectancy (R/trade) this sample could have declared > 0 with 50% power at the given
    one-sided alpha: z * sd / sqrt(n_eff). Reported with every verdict so 'no edge' is read as 'no edge above X'."""
    r = np.asarray(r, float)
    if len(r) < 2:
        return float("nan")
    n_eff = n_eff or len(r)
    return float(NormalDist().inv_cdf(1 - alpha_one_sided) * r.std(ddof=1) / np.sqrt(max(n_eff, 1)))


def monte_carlo_drawdown(r, n=5000, seed=7):
    """Reshuffle trade order; return (median, 95th pct) of max drawdown in R."""
    r = np.asarray(r, float)
    rng = np.random.default_rng(seed)
    dds = []
    for _ in range(n):
        c = np.cumsum(rng.permutation(r))
        dds.append(float((np.maximum.accumulate(np.maximum(c, 0)) - c).max()))
    return float(np.median(dds)), float(np.quantile(dds, 0.95))


def challenger(real_mean: float, pool, n: int, draws=2000, seed=7) -> dict:
    """Random-entry challenger: `pool` = net R of many random setups with the same stop/target/hold/cost rules.
    Draw `draws` samples of size n from the pool; report where the real mean sits (percentile) and the 95th pct."""
    pool = np.asarray(pool, float)
    if len(pool) < 10 or n < 1:
        return {"pct": float("nan"), "p95": float("nan"), "pool_mean": float("nan"), "pool_n": int(len(pool))}
    rng = np.random.default_rng(seed)
    means = rng.choice(pool, size=(draws, n), replace=True).mean(axis=1)
    return {"pct": float((means < real_mean).mean() * 100), "p95": float(np.quantile(means, 0.95)),
            "pool_mean": float(pool.mean()), "pool_n": int(len(pool))}


def gate_b(r, min_n: int, n_trials: int = 1, alpha=0.05, clusters=None) -> dict:
    """Gate B (research economics). PASS only if n >= min_n AND the lower bound of the
    (multiple-testing-adjusted) one-sided bootstrap CI of net expectancy is > 0.
    With `clusters` the CI is a block bootstrap by cluster and min_n counts clusters (independent pair-days)."""
    r = np.asarray(r, float)
    a = adjusted_alpha(n_trials, alpha)
    if clusters is not None:
        n_eff = int(len(np.unique(np.asarray(clusters))))
        lo, hi = cluster_bootstrap_ci(r, clusters, a * 2)
    else:
        n_eff = int(len(r))
        lo, hi = bootstrap_ci(r, a * 2)         # two-sided CI with a/2 per tail == one-sided a
    exp = expectancy(r)
    return {"n": int(len(r)), "n_eff": n_eff, "min_n": min_n, "expectancy_r": exp, "ci_lo": lo, "ci_hi": hi,
            "alpha_used": a, "mde_r": min_detectable_effect(r, a, n_eff),
            "pass": bool(n_eff >= min_n and exp > 0 and lo > 0)}
