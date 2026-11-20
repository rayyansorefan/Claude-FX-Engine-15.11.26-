# Learning loop (written 2026-11-20 21:20 UTC)

Exit in force for new setups: **none (frozen exit)**
Bars before any promotion: 60+ live trades, CI lower bound > 0 (alpha 0.05/9), offline walk-forward test agrees, max one change per 14 days, auto-rollback after 40 trades.

| rule | trades | cumulative gain vs frozen (R) | per trade | 95% range |
|---|---|---|---|---|
| A1_breakeven_at_0.75R | 23 | -8.93 | -0.388 | [-0.927, +0.112] |
| A2_breakeven_at_1R | 23 | -10.64 | -0.463 | [-0.944, -0.024] |
| A3_breakeven_at_1.5R | 23 | -7.76 | -0.337 | [-0.762, +0.000] |
| B1_trail_0.5R_behind_peak | 23 | -6.64 | -0.289 | [-0.657, +0.095] |
| B2_trail_1R_behind_peak | 23 | -7.07 | -0.307 | [-0.692, +0.061] |
| B3_trail_1.5R_behind_peak | 23 | -9.87 | -0.429 | [-0.880, -0.034] |
| C1_keep_40pc_of_peak | 23 | -9.48 | -0.412 | [-0.812, -0.009] |
| C2_keep_50pc_of_peak | 23 | -8.01 | -0.348 | [-0.723, +0.041] |
| C3_keep_60pc_of_peak | 23 | -7.13 | -0.310 | [-0.669, +0.076] |

Log:
