"""Honest statistics. All in R units (1R = planned risk). Seeded => reproducible."""
from __future__ import annotations
import numpy as np


def expectancy(r) -> float:
    r = np.asarray(r, float)
    return float(r.mean()) if len(r) else float("nan")


def bootstrap_ci(r, alpha=0.05, n=10000, seed=7):
    """Percentile bootstrap CI of the mean. Returns (lo, hi)."""
    r = np.asarray(r, float)
    if len(r) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = rng.choice(r, size=(n, len(r)), replace=True).mean(axis=1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def adjusted_alpha(n_trials: int, alpha=0.05) -> float:
    """Bonferroni multiple-testing penalty: every variant ever tried counts."""
    return alpha / max(1, n_trials)


def monte_carlo_drawdown(r, n=5000, seed=7):
    """Reshuffle trade order; return (median, 95th pct) of max drawdown in R."""
    r = np.asarray(r, float)
    rng = np.random.default_rng(seed)
    dds = []
    for _ in range(n):
        c = np.cumsum(rng.permutation(r))
        dds.append(float((np.maximum.accumulate(np.maximum(c, 0)) - c).max()))
    return float(np.median(dds)), float(np.quantile(dds, 0.95))


def gate_b(r, min_n: int, n_trials: int = 1, alpha=0.05) -> dict:
    """Gate B (research economics). PASS only if n >= min_n AND the lower bound of the
    (multiple-testing-adjusted) one-sided bootstrap CI of net expectancy is > 0."""
    r = np.asarray(r, float)
    a = adjusted_alpha(n_trials, alpha)
    lo, hi = bootstrap_ci(r, a * 2)         # two-sided CI with a/2 per tail == one-sided a
    exp = expectancy(r)
    return {"n": int(len(r)), "min_n": min_n, "expectancy_r": exp, "ci_lo": lo, "ci_hi": hi,
            "alpha_used": a, "pass": bool(len(r) >= min_n and exp > 0 and lo > 0)}
