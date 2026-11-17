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
