# Learning loop (written 2026-11-19 21:20 UTC)

Exit in force for new setups: **none (frozen exit)**
Bars before any promotion: 60+ live trades, CI lower bound > 0 (alpha 0.05/9), offline walk-forward test agrees, max one change per 14 days, auto-rollback after 40 trades.

| rule | trades | cumulative gain vs frozen (R) | per trade | 95% range |
|---|---|---|---|---|
| A1_breakeven_at_0.75R | 17 | -9.67 | -0.569 | [-1.255, +0.065] |
| A2_breakeven_at_1R | 17 | -11.73 | -0.690 | [-1.274, -0.118] |
| A3_breakeven_at_1.5R | 17 | -7.76 | -0.456 | [-1.030, +0.000] |
| B1_trail_0.5R_behind_peak | 17 | -6.95 | -0.409 | [-0.804, -0.049] |
| B2_trail_1R_behind_peak | 17 | -8.38 | -0.493 | [-0.948, -0.101] |
| B3_trail_1.5R_behind_peak | 17 | -10.68 | -0.628 | [-1.185, -0.123] |
| C1_keep_40pc_of_peak | 17 | -9.61 | -0.566 | [-1.004, -0.162] |
| C2_keep_50pc_of_peak | 17 | -8.40 | -0.494 | [-0.899, -0.128] |
| C3_keep_60pc_of_peak | 17 | -7.56 | -0.445 | [-0.826, -0.095] |

Log:
