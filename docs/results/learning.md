# Learning loop (written 2026-11-25 21:20 UTC)

Exit in force for new setups: **none (frozen exit)**
Bars before any promotion: 60+ live trades, CI lower bound > 0 (alpha 0.05/9), offline walk-forward test agrees, max one change per 14 days, auto-rollback after 40 trades.

| rule | trades | cumulative gain vs frozen (R) | per trade | 95% range |
|---|---|---|---|---|
| A1_breakeven_at_0.75R | 38 | -6.86 | -0.181 | [-0.542, +0.143] |
| A2_breakeven_at_1R | 38 | -8.58 | -0.226 | [-0.570, +0.075] |
| A3_breakeven_at_1.5R | 38 | -6.76 | -0.178 | [-0.462, +0.052] |
| B1_trail_0.5R_behind_peak | 38 | -6.96 | -0.183 | [-0.484, +0.132] |
| B2_trail_1R_behind_peak | 38 | -6.08 | -0.160 | [-0.455, +0.108] |
| B3_trail_1.5R_behind_peak | 38 | -8.49 | -0.224 | [-0.532, +0.040] |
| C1_keep_40pc_of_peak | 38 | -9.24 | -0.243 | [-0.570, +0.076] |
| C2_keep_50pc_of_peak | 38 | -7.24 | -0.190 | [-0.501, +0.127] |
| C3_keep_60pc_of_peak | 38 | -6.95 | -0.183 | [-0.491, +0.141] |

Log:
