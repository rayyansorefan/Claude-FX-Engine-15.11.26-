# Phase 3 v1 on H1 — RESULT: FAIL (2026-11-15)
Same rules as M15 (only the timeframe changed). Same data/costs/holdout rule. Trials logged at run time: 6.

| type | scored | win | net R stressed | net R normal cost | 95% CI (stressed) |
|---|---|---|---|---|---|
| asia_breakout | 3,461 | 34% | -0.151 | -0.085 | [-0.199, -0.104] |
| range_reversion | 2,186 | 35% | -0.162 | -0.140 | [-0.215, -0.109] |
| trend_pullback | 2,765 | 34% | -0.177 | -0.116 | [-0.227, -0.126] |
| ALL | 8,412 | 34% | -0.162 | -0.110 | [-0.191, -0.133] |

Losses are smaller than on M15 (costs ~3x smaller relative to stops) but still negative every year
(trend_pullback +0.113R in 2023 only, negative after). Gross edge ~0: 34% wins on 2R targets is break-even before costs.
Verdict: rejected. Cost drag explains part of the M15 loss, not all: the rules themselves carry no measurable edge.
