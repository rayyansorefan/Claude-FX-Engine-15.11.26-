# Learning loop (written 2026-11-23 21:20 UTC)

Exit in force for new setups: **none (frozen exit)**
Bars before any promotion: 60+ live trades, CI lower bound > 0 (alpha 0.05/9), offline walk-forward test agrees, max one change per 14 days, auto-rollback after 40 trades.

| rule | trades | cumulative gain vs frozen (R) | per trade | 95% range |
|---|---|---|---|---|
| A1_breakeven_at_0.75R | 28 | -7.90 | -0.282 | [-0.756, +0.149] |
| A2_breakeven_at_1R | 28 | -9.61 | -0.343 | [-0.790, +0.046] |
| A3_breakeven_at_1.5R | 28 | -6.76 | -0.242 | [-0.626, +0.071] |
| B1_trail_0.5R_behind_peak | 28 | -5.80 | -0.207 | [-0.554, +0.154] |
| B2_trail_1R_behind_peak | 28 | -5.93 | -0.212 | [-0.574, +0.120] |
| B3_trail_1.5R_behind_peak | 28 | -9.23 | -0.330 | [-0.725, +0.015] |
| C1_keep_40pc_of_peak | 28 | -8.05 | -0.287 | [-0.677, +0.088] |
| C2_keep_50pc_of_peak | 28 | -6.47 | -0.231 | [-0.593, +0.141] |
| C3_keep_60pc_of_peak | 28 | -5.49 | -0.196 | [-0.547, +0.173] |

Log:
