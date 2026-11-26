# Learning loop (written 2026-11-26 21:20 UTC)

Exit in force for new setups: **none (frozen exit)**
Bars before any promotion: 60+ live trades, CI lower bound > 0 (alpha 0.05/9), offline walk-forward test agrees, max one change per 14 days, auto-rollback after 40 trades.

| rule | trades | cumulative gain vs frozen (R) | per trade | 95% range |
|---|---|---|---|---|
| A1_breakeven_at_0.75R | 39 | -6.86 | -0.176 | [-0.541, +0.139] |
| A2_breakeven_at_1R | 39 | -8.58 | -0.220 | [-0.563, +0.067] |
| A3_breakeven_at_1.5R | 39 | -6.76 | -0.173 | [-0.450, +0.051] |
| B1_trail_0.5R_behind_peak | 39 | -6.96 | -0.179 | [-0.475, +0.128] |
| B2_trail_1R_behind_peak | 39 | -6.08 | -0.156 | [-0.435, +0.103] |
| B3_trail_1.5R_behind_peak | 39 | -8.49 | -0.218 | [-0.522, +0.033] |
| C1_keep_40pc_of_peak | 39 | -9.24 | -0.237 | [-0.553, +0.085] |
| C2_keep_50pc_of_peak | 39 | -7.24 | -0.185 | [-0.487, +0.123] |
| C3_keep_60pc_of_peak | 39 | -6.95 | -0.178 | [-0.485, +0.138] |

Log:
