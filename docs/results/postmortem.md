# Live post-mortem (written by code; nothing here changes a trade)

Finished live trades: 43 (16 won, 27 lost). Average win +1.70R, average loss -1.12R.

## What the losses have in common
- wrong from the start (never more than +0.4R ahead): 20
- faded (was +1.0R or better, then lost): 3
- timed out: 1
- other: 3; path unknown: 0

## Conditions compared, all strategies pooled

| condition | pass: n / win / mean | fail: n / win / mean | difference (range) | verdict |
|---|---|---|---|---|
| vol_not_low | 20 / 30% / -0.22R | 23 / 43% / +0.06R | -0.28R [-1.61, +1.05] | no separation |
| vol_not_high | 30 / 37% / -0.08R | 13 / 38% / -0.05R | -0.03R [-1.48, +1.42] | no separation |
| vol_mid | 18 / 39% / -0.05R | 25 / 36% / -0.08R | +0.04R [-1.32, +1.39] | no separation |
| trend_with_pos | 22 / 23% / -0.50R | 21 / 52% / +0.39R | -0.89R [-2.16, +0.39] | no separation |
| trend_with_strong | 22 / 23% / -0.50R | 21 / 52% / +0.39R | -0.89R [-2.16, +0.39] | no separation |
| not_extended | 17 / 41% / +0.03R | 26 / 35% / -0.13R | +0.16R [-1.22, +1.54] | no separation |
| near_ema20 | 10 / 40% / +0.09R | 33 / 36% / -0.12R | +0.21R [-1.46, +1.87] | no separation |
| htf_with | 23 / 26% / -0.40R | 20 / 50% / +0.31R | -0.71R [-2.02, +0.60] | no separation |
| htf_not_against | 23 / 26% / -0.40R | 20 / 50% / +0.31R | -0.71R [-2.02, +0.60] | no separation |
| london_ny_hours | 27 / 33% / -0.13R | 16 / 44% / +0.04R | -0.18R [-1.54, +1.19] | no separation |
| not_friday | 38 / 42% / +0.07R | 5 / 0% / -1.10R | n/a | too few |
| not_monday | 39 / 38% / -0.04R | 4 / 25% / -0.37R | n/a | too few |

## asia_breakout: 27 trades

| condition | pass: n / win / mean | fail: n / win / mean | difference (range) | verdict |
|---|---|---|---|---|
| vol_not_low | 12 / 33% / -0.14R | 15 / 53% / +0.46R | -0.60R [-2.40, +1.20] | no separation |
| vol_not_high | 19 / 42% / +0.12R | 8 / 50% / +0.38R | -0.27R [-2.29, +1.76] | no separation |
| vol_mid | 11 / 45% / +0.22R | 16 / 44% / +0.18R | +0.04R [-1.83, +1.92] | no separation |
| trend_with_pos | 10 / 20% / -0.54R | 17 / 59% / +0.63R | -1.17R [-2.87, +0.53] | no separation |
| trend_with_strong | 10 / 20% / -0.54R | 17 / 59% / +0.63R | -1.17R [-2.87, +0.53] | no separation |
| not_extended | 8 / 50% / +0.36R | 19 / 42% / +0.12R | +0.24R [-1.82, +2.30] | no separation |
| near_ema20 | 5 / 60% / +0.69R | 22 / 41% / +0.08R | n/a | too few |
| htf_with | 11 / 27% / -0.32R | 16 / 56% / +0.55R | -0.88R [-2.63, +0.88] | no separation |
| htf_not_against | 11 / 27% / -0.32R | 16 / 56% / +0.55R | -0.88R [-2.63, +0.88] | no separation |
| london_ny_hours | 21 / 38% / +0.00R | 6 / 67% / +0.87R | n/a | too few |
| not_friday | 25 / 48% / +0.30R | 2 / 0% / -1.14R | n/a | too few |
| not_monday | 24 / 50% / +0.36R | 3 / 0% / -1.13R | n/a | too few |


Correction: 24 comparisons were made in this report. SUPPORTED = 30+ trades on each side and p <= 0.05/24 (Bonferroni, so the chance of ANY false finding in the whole report is at most 5%). HYPOTHESIS = 8+ trades each side and Benjamini-Hochberg false-discovery rate 10%: shown for interest only, never acted on. The range shown is Bonferroni-corrected. Even a SUPPORTED condition is only a candidate: it must also pass the offline validation on unseen history before it can become an entry filter.
