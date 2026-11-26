# Live post-mortem (written by code; nothing here changes a trade)

Finished live trades: 39 (14 won, 25 lost). Average win +1.68R, average loss -1.12R.

## What the losses have in common
- wrong from the start (never more than +0.4R ahead): 19
- faded (was +1.0R or better, then lost): 3
- timed out: 0
- other: 3; path unknown: 0

## Conditions compared, all strategies pooled

| condition | pass: n / win / mean | fail: n / win / mean | difference (range) | verdict |
|---|---|---|---|---|
| vol_not_low | 20 / 30% / -0.22R | 19 / 42% / -0.00R | -0.21R [-1.60, +1.17] | no separation |
| vol_not_high | 26 / 35% / -0.15R | 13 / 38% / -0.05R | -0.10R [-1.58, +1.38] | no separation |
| vol_mid | 18 / 39% / -0.05R | 21 / 33% / -0.17R | +0.12R [-1.28, +1.52] | no separation |
| trend_with_pos | 22 / 23% / -0.50R | 17 / 53% / +0.39R | -0.89R [-2.26, +0.47] | no separation |
| trend_with_strong | 22 / 23% / -0.50R | 17 / 53% / +0.39R | -0.89R [-2.26, +0.47] | no separation |
| not_extended | 14 / 36% / -0.16R | 25 / 36% / -0.09R | -0.07R [-1.53, +1.38] | no separation |
| near_ema20 | 7 / 29% / -0.26R | 32 / 38% / -0.08R | n/a | too few |
| htf_with | 20 / 20% / -0.58R | 19 / 53% / +0.38R | -0.96R [-2.28, +0.36] | no separation |
| htf_not_against | 20 / 20% / -0.58R | 19 / 53% / +0.38R | -0.96R [-2.28, +0.36] | no separation |
| london_ny_hours | 23 / 30% / -0.22R | 16 / 44% / +0.04R | -0.26R [-1.67, +1.14] | no separation |
| not_friday | 35 / 40% / -0.00R | 4 / 0% / -1.08R | n/a | too few |
| not_monday | 35 / 37% / -0.08R | 4 / 25% / -0.37R | n/a | too few |

## asia_breakout: 23 trades

| condition | pass: n / win / mean | fail: n / win / mean | difference (range) | verdict |
|---|---|---|---|---|
| vol_not_low | 12 / 33% / -0.14R | 11 / 55% / +0.49R | -0.63R [-2.60, +1.34] | no separation |
| vol_not_high | 15 / 40% / +0.05R | 8 / 50% / +0.38R | -0.33R [-2.44, +1.77] | no separation |
| vol_mid | 11 / 45% / +0.22R | 12 / 42% / +0.11R | +0.11R [-1.90, +2.12] | no separation |
| trend_with_pos | 10 / 20% / -0.54R | 13 / 62% / +0.71R | -1.25R [-3.06, +0.56] | no separation |
| trend_with_strong | 10 / 20% / -0.54R | 13 / 62% / +0.71R | -1.25R [-3.06, +0.56] | no separation |
| not_extended | 5 / 40% / +0.04R | 18 / 44% / +0.20R | n/a | too few |
| near_ema20 | 2 / 50% / +0.37R | 21 / 43% / +0.14R | n/a | too few |
| htf_with | 8 / 12% / -0.75R | 15 / 60% / +0.65R | -1.40R [-3.10, +0.29] | no separation |
| htf_not_against | 8 / 12% / -0.75R | 15 / 60% / +0.65R | -1.40R [-3.10, +0.29] | no separation |
| london_ny_hours | 17 / 35% / -0.09R | 6 / 67% / +0.87R | n/a | too few |
| not_friday | 22 / 45% / +0.22R | 1 / 0% / -1.06R | n/a | too few |
| not_monday | 20 / 50% / +0.36R | 3 / 0% / -1.13R | n/a | too few |


Correction: 24 comparisons were made in this report. SUPPORTED = 30+ trades on each side and p <= 0.05/24 (Bonferroni, so the chance of ANY false finding in the whole report is at most 5%). HYPOTHESIS = 8+ trades each side and Benjamini-Hochberg false-discovery rate 10%: shown for interest only, never acted on. The range shown is Bonferroni-corrected. Even a SUPPORTED condition is only a candidate: it must also pass the offline validation on unseen history before it can become an entry filter.
