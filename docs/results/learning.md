# Learning loop (written 2026-11-18 21:20 UTC)

Exit in force for new setups: **none (frozen exit)**
Bars before any promotion: 60+ live trades, CI lower bound > 0 (alpha 0.05/9), offline walk-forward test agrees, max one change per 14 days, auto-rollback after 40 trades.

| rule | trades | cumulative gain vs frozen (R) | per trade | 95% range |
|---|---|---|---|---|
| A1_breakeven_at_0.75R | 12 | -7.86 | -0.655 | [-1.489, +0.182] |
| A2_breakeven_at_1R | 12 | -9.92 | -0.826 | [-1.491, -0.165] |
| A3_breakeven_at_1.5R | 12 | -5.95 | -0.495 | [-1.159, +0.000] |
| B1_trail_0.5R_behind_peak | 12 | -6.87 | -0.573 | [-1.017, -0.154] |
| B2_trail_1R_behind_peak | 12 | -7.30 | -0.608 | [-1.189, -0.095] |
| B3_trail_1.5R_behind_peak | 12 | -9.02 | -0.751 | [-1.434, -0.133] |
| C1_keep_40pc_of_peak | 12 | -8.39 | -0.700 | [-1.205, -0.217] |
| C2_keep_50pc_of_peak | 12 | -7.54 | -0.628 | [-1.095, -0.191] |
| C3_keep_60pc_of_peak | 12 | -7.05 | -0.588 | [-1.021, -0.175] |

Log:
