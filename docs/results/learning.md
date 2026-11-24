# Learning loop (written 2026-11-24 21:20 UTC)

Exit in force for new setups: **none (frozen exit)**
Bars before any promotion: 60+ live trades, CI lower bound > 0 (alpha 0.05/9), offline walk-forward test agrees, max one change per 14 days, auto-rollback after 40 trades.

| rule | trades | cumulative gain vs frozen (R) | per trade | 95% range |
|---|---|---|---|---|
| A1_breakeven_at_0.75R | 33 | -7.90 | -0.239 | [-0.644, +0.127] |
| A2_breakeven_at_1R | 33 | -9.61 | -0.291 | [-0.676, +0.042] |
| A3_breakeven_at_1.5R | 33 | -6.76 | -0.205 | [-0.533, +0.035] |
| B1_trail_0.5R_behind_peak | 33 | -7.72 | -0.234 | [-0.543, +0.085] |
| B2_trail_1R_behind_peak | 33 | -7.32 | -0.222 | [-0.544, +0.070] |
| B3_trail_1.5R_behind_peak | 33 | -9.23 | -0.280 | [-0.631, +0.013] |
| C1_keep_40pc_of_peak | 33 | -9.37 | -0.284 | [-0.626, +0.058] |
| C2_keep_50pc_of_peak | 33 | -7.64 | -0.232 | [-0.554, +0.099] |
| C3_keep_60pc_of_peak | 33 | -7.62 | -0.231 | [-0.541, +0.095] |

Log:
