# Phase 3 v1 on M15 — RESULT: FAIL (2026-11-15)
Data: OANDA practice bid/ask, 10 pairs, 2023-11-01 -> 2026-05-14 (holdout 2026-05-15+ untouched).
Costs: stressed (spread x2, commission 0.7 pip, slippage on stop fills, swap). 1R = planned stop distance.

| type | scored | win | net R stressed | net R normal cost | 95% CI (stressed) |
|---|---|---|---|---|---|
| asia_breakout | 2,119 | 31% | -0.397 | -0.245 | [-0.457, -0.336] |
| range_reversion | 8,131 | 35% | -0.210 | -0.148 | [-0.238, -0.183] |
| trend_pullback | 9,513 | 31% | -0.359 | -0.236 | [-0.386, -0.331] |
| ALL | 19,763 | 33% | -0.302 | -0.201 | [-0.320, -0.283] |

Negative in every year (2023-2026) and for every type; negative even at normal costs.
Win rate ~33% with 2R targets = roughly zero GROSS edge; costs (~0.1-0.2R per trade on M15) do the rest.
Measured OANDA median spreads (pips): EURUSD 1.6, GBPUSD 1.9, USDJPY 1.7, USDCHF 1.5, AUDUSD 1.3,
USDCAD 1.8, NZDUSD 1.5, EURGBP 1.4, EURJPY 2.4, GBPJPY 3.3 (assumed base 0.3-1.2 + 0.7 commission, x2 stressed).
Verdict: v1 on M15 rejected. No parameter tuning will be done on this result.
