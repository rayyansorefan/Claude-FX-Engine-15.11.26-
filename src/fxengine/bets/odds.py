"""Odds maths. All pure functions."""
import numpy as np


def implied(odds):
    return 1.0 / np.asarray(odds, float)


def overround(*odds) -> float:
    """Bookmaker margin of a market: sum of implied probabilities minus 1 (e.g. 0.05 = 5%)."""
    return float(sum(1.0 / o for o in odds) - 1.0)


def fair_probs(*odds):
    """Remove the margin proportionally. Returns probabilities summing to 1 (None if any odd missing)."""
    o = np.asarray(odds, float)
    if np.isnan(o).any() or (o <= 1.0).any():
        return None
    p = 1.0 / o
    return p / p.sum()


def fair_probs_shin(*odds, iters=200):
    """Shin (1993) margin removal: allocates more margin to longshots (better for favourite-longshot bias)."""
    o = np.asarray(odds, float)
    if np.isnan(o).any() or (o <= 1.0).any():
        return None
    q = 1.0 / o
    s = q.sum()
    lo, hi = 0.0, 0.4
    for _ in range(iters):
        z = (lo + hi) / 2
        p = (np.sqrt(z * z + 4 * (1 - z) * q * q / s) - z) / (2 * (1 - z))
        lo, hi = (lo, z) if p.sum() < 1 else (z, hi)      # sum(p) falls as z rises: too small a sum means z is too big
    return p / p.sum()


def fair_probs_shin_arr(odds, iters=200):
    """Row-wise Shin for an (n, k) array of odds: same maths as fair_probs_shin, no Python loop over rows.
    Rows with a missing odd or an odd <= 1 come back as NaN."""
    o = np.asarray(odds, float)
    out = np.full(o.shape, np.nan)
    ok = ~np.isnan(o).any(axis=1) & (o > 1.0).all(axis=1)
    if not ok.any():
        return out
    q = 1.0 / o[ok]
    s = q.sum(axis=1, keepdims=True)
    lo, hi = np.zeros_like(s), np.full_like(s, 0.4)
    for _ in range(iters):
        z = (lo + hi) / 2
        p = (np.sqrt(z * z + 4 * (1 - z) * q * q / s) - z) / (2 * (1 - z))
        small = p.sum(axis=1, keepdims=True) < 1                  # sum(p) falls as z rises: too small a sum means z is too big
        lo, hi = np.where(small, lo, z), np.where(small, z, hi)
    out[ok] = p / p.sum(axis=1, keepdims=True)
    return out
