# Learning loop (written 2026-11-17 21:20 UTC)

Exit in force for new setups: **none (frozen exit)**
Bars before any promotion: 60+ live trades, CI lower bound > 0 (alpha 0.05/9), offline walk-forward test agrees, max one change per 14 days, auto-rollback after 40 trades.

| rule | trades | cumulative gain vs frozen (R) | per trade | 95% range |
|---|---|---|---|---|
| A1_breakeven_at_0.75R | 8 | -1.89 | -0.237 | [-1.235, +0.644] |
| A2_breakeven_at_1R | 8 | -3.95 | -0.494 | [-1.236, +0.000] |
| A3_breakeven_at_1.5R | 8 | -1.98 | -0.247 | [-0.989, +0.000] |
| B1_trail_0.5R_behind_peak | 8 | -3.93 | -0.491 | [-1.089, +0.000] |
| B2_trail_1R_behind_peak | 8 | -3.47 | -0.433 | [-1.150, +0.000] |
| B3_trail_1.5R_behind_peak | 8 | -3.69 | -0.461 | [-1.243, +0.000] |
| C1_keep_40pc_of_peak | 8 | -4.49 | -0.561 | [-1.266, +0.000] |
| C2_keep_50pc_of_peak | 8 | -4.14 | -0.518 | [-1.161, +0.000] |
| C3_keep_60pc_of_peak | 8 | -3.80 | -0.475 | [-1.055, +0.000] |

Log:
