# Batch 3 — daily momentum (E6) and carry+momentum (E7), scored on M5 bars (holdout untouched)

Trials logged: 12 (alpha = 0.05/12). Period 2023-11-01 -> 2026-05-14.
Pass = penalised cluster-bootstrap lower bound > 0 AND mean above the random-entry challenger's 95th percentile.
MDE = smallest true edge (R/trade) this sample could have detected; read 'no edge' as 'no edge above MDE'.

| variant | cost | signals | scored | pair-days | win | net R | 95% cluster CI | penalised low | MDE | challenger mean / p95 / real pct | years | pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E6_tsmom_daily | stressed | 124 | 116 | 116 | 44% | +0.154 | [-0.136, 0.457] | -0.136 | 0.299 | -0.078 / +0.058 / 99.5% | {2024: 0.299, 2025: 0.236, 2026: -0.264} | FAIL |
| E6_tsmom_daily | normal | 124 | 116 | 116 | 44% | +0.161 | [-0.128, 0.465] | -0.128 | 0.299 | -0.072 / +0.065 / 99.5% | {2024: 0.307, 2025: 0.243, 2026: -0.257} | FAIL |
| E6_tsmom_daily | measured | 124 | 116 | 116 | 44% | +0.141 | [-0.145, 0.446] | -0.145 | 0.300 | -0.088 / +0.053 / 99.6% | {2024: 0.3, 2025: 0.21, 2026: -0.277} | FAIL |
