# Learning loop (written 2026-11-27 21:20 UTC)

Exit in force for new setups: **none (frozen exit)**
Bars before any promotion: 60+ live trades, CI lower bound > 0 (alpha 0.05/9), offline walk-forward test agrees, max one change per 14 days, auto-rollback after 40 trades.

| rule | trades | cumulative gain vs frozen (R) | per trade | 95% range |
|---|---|---|---|---|
| A1_breakeven_at_0.75R | 43 | -9.79 | -0.228 | [-0.596, +0.102] |
| A2_breakeven_at_1R | 43 | -12.41 | -0.289 | [-0.637, +0.009] |
| A3_breakeven_at_1.5R | 43 | -6.76 | -0.157 | [-0.410, +0.046] |
| B1_trail_0.5R_behind_peak | 43 | -9.48 | -0.221 | [-0.502, +0.062] |
| B2_trail_1R_behind_peak | 43 | -9.68 | -0.225 | [-0.532, +0.045] |
| B3_trail_1.5R_behind_peak | 43 | -10.42 | -0.242 | [-0.549, +0.004] |
| C1_keep_40pc_of_peak | 43 | -12.43 | -0.289 | [-0.601, +0.011] |
| C2_keep_50pc_of_peak | 43 | -10.33 | -0.240 | [-0.540, +0.051] |
| C3_keep_60pc_of_peak | 43 | -9.41 | -0.219 | [-0.502, +0.064] |

Log:
