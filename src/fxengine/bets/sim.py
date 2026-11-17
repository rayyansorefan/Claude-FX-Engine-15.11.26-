"""Bankroll simulator: resample REAL historical bets (the strategy's own, with real odds and outcomes) and report what happens to a bankroll.
Answers: chance of reaching the goal, chance of ruin, median bets needed. Same output whether or not the strategy has an edge."""
import numpy as np


def simulate(odds, won, start=100.0, goal=1000.0, frac=0.05, max_bets=2000, n=3000, seed=5, kelly_edge=None):
    """frac = fixed fraction of the CURRENT bankroll per bet (minimum bet £1; below £1 = ruin)."""
    odds, won = np.asarray(odds, float), np.asarray(won, bool)
    rng = np.random.default_rng(seed)
    hit = ruin = 0
    lengths = []
    for _ in range(n):
        b, k = start, 0
        idx = rng.integers(0, len(odds), size=max_bets)
        while k < max_bets and 1.0 <= b < goal:
            s = max(1.0, min(b, b * frac))
            i = idx[k]
            b += s * (odds[i] - 1) if won[i] else -s
            k += 1
        hit += b >= goal
        ruin += b < 1.0
        lengths.append(k)
    return dict(p_goal=hit / n, p_ruin=ruin / n, p_neither=1 - (hit + ruin) / n, median_bets=int(np.median(lengths)), frac=frac)
