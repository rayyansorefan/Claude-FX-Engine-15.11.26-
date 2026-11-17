# Trade post-mortem (automatic, deterministic)

Classes: WRONG_WAY = never 0.5R ahead (signal wrong) · GAVE_BACK = was 1R+ ahead then lost (exit problem) · STALLED = 0.5-1R ahead then failed · COST_DRAG = right direction, costs ate it.
A pattern counts only with >= 30 trades, a Bonferroni-corrected test over every bucket checked, and the same sign in both halves of the sample.

## m5_rerun_E1_strength  (n=633)

Win rate 45% · mean -0.055R · **No winner-vs-loser pattern survives the multiple-testing and half-sample checks (treat differences as noise).**

| class | n | share | mean net R | mean best (MFE) | mean worst (MAE) |
|---|---|---|---|---|---|
| WIN | 287 | 45% | +0.884 | 1.27 | 0.42 |
| WRONG_WAY | 227 | 36% | -0.910 | 0.21 | 1.02 |
| STALLED | 93 | 15% | -0.708 | 0.71 | 0.89 |
| GAVE_BACK | 24 | 4% | -0.677 | 1.32 | 0.82 |
| COST_DRAG | 2 | 0% | -0.023 | 0.57 | 0.72 |

Winners vs losers: best excursion 1.274 vs 0.427 R, worst excursion 0.42 vs 0.972 R.

Exits: 7% of losers had been 1R+ ahead

Buckets tested 21 (needs |z| >= 3.04): none survive

## m5_rerun_E2_donchian  (n=496)

Win rate 38% · mean -0.118R · **No winner-vs-loser pattern survives the multiple-testing and half-sample checks (treat differences as noise).**

| class | n | share | mean net R | mean best (MFE) | mean worst (MAE) |
|---|---|---|---|---|---|
| WIN | 190 | 38% | +1.169 | 1.60 | 0.39 |
| WRONG_WAY | 179 | 36% | -1.022 | 0.22 | 1.07 |
| STALLED | 74 | 15% | -0.848 | 0.70 | 0.97 |
| GAVE_BACK | 51 | 10% | -0.686 | 1.32 | 0.85 |
| COST_DRAG | 2 | 0% | -0.018 | 0.75 | 0.61 |

Winners vs losers: best excursion 1.601 vs 0.52 R, worst excursion 0.389 vs 1.005 R.

Exits: 17% of losers had been 1R+ ahead

Buckets tested 21 (needs |z| >= 3.04): none survive

## m5_rerun_E4_donchian_trail  (n=415)

Win rate 35% · mean -0.107R · **No winner-vs-loser pattern survives the multiple-testing and half-sample checks (treat differences as noise).**

| class | n | share | mean net R | mean best (MFE) | mean worst (MAE) |
|---|---|---|---|---|---|
| WRONG_WAY | 152 | 37% | -0.915 | 0.22 | 0.94 |
| WIN | 145 | 35% | +1.072 | 2.32 | 0.33 |
| STALLED | 73 | 18% | -0.572 | 0.70 | 0.64 |
| GAVE_BACK | 39 | 9% | -0.480 | 1.31 | 0.59 |
| COST_DRAG | 6 | 1% | -0.034 | 1.27 | 0.35 |

Winners vs losers: best excursion 2.32 vs 0.534 R, worst excursion 0.335 vs 0.798 R.

Exits: 14% of losers had been 1R+ ahead

Buckets tested 21 (needs |z| >= 3.04): none survive

## m5_rerun_E5_strength_trail  (n=403)

Win rate 30% · mean -0.072R · **No winner-vs-loser pattern survives the multiple-testing and half-sample checks (treat differences as noise).**

| class | n | share | mean net R | mean best (MFE) | mean worst (MAE) |
|---|---|---|---|---|---|
| WRONG_WAY | 136 | 34% | -1.017 | 0.20 | 1.04 |
| WIN | 119 | 30% | +1.815 | 3.15 | 0.40 |
| GAVE_BACK | 73 | 18% | -0.598 | 1.60 | 0.72 |
| STALLED | 72 | 18% | -0.873 | 0.74 | 0.95 |
| COST_DRAG | 3 | 1% | -0.059 | 2.05 | 0.53 |

Winners vs losers: best excursion 3.148 vs 0.719 R, worst excursion 0.402 vs 0.933 R.

Exits: 26% of losers had been 1R+ ahead

Buckets tested 21 (needs |z| >= 3.04): none survive

## m5_rerun_v1_H1  (n=7954)

Win rate 35% · mean -0.147R · **1 pattern(s) survived strict checks: CANDIDATE hypotheses logged, not applied.**

| class | n | share | mean net R | mean best (MFE) | mean worst (MAE) |
|---|---|---|---|---|---|
| WRONG_WAY | 2959 | 37% | -1.125 | 0.17 | 1.21 |
| WIN | 2756 | 35% | +1.654 | 1.98 | 0.52 |
| STALLED | 1225 | 15% | -1.094 | 0.72 | 1.20 |
| GAVE_BACK | 995 | 12% | -1.064 | 1.40 | 1.22 |
| COST_DRAG | 19 | 0% | -0.034 | 1.42 | 0.80 |

Winners vs losers: best excursion 1.982 vs 0.542 R, worst excursion 0.517 vs 1.208 R.

Exits: 19% of losers had been 1R+ ahead

Buckets tested 20 (needs |z| >= 3.02): symbol=EURGBP (-0.25R)

## m5_rerun_v1_M15  (n=18719)

Win rate 33% · mean -0.282R · **6 pattern(s) survived strict checks: CANDIDATE hypotheses logged, not applied.**

| class | n | share | mean net R | mean best (MFE) | mean worst (MAE) |
|---|---|---|---|---|---|
| WRONG_WAY | 7827 | 42% | -1.197 | 0.15 | 1.27 |
| WIN | 6172 | 33% | +1.500 | 1.95 | 0.54 |
| STALLED | 2663 | 14% | -1.132 | 0.72 | 1.29 |
| GAVE_BACK | 1962 | 10% | -1.099 | 1.42 | 1.37 |
| COST_DRAG | 95 | 0% | -0.047 | 0.96 | 0.67 |

Winners vs losers: best excursion 1.954 vs 0.475 R, worst excursion 0.543 vs 1.287 R.

Exits: 16% of losers had been 1R+ ahead

Buckets tested 20 (needs |z| >= 3.02): symbol=EURGBP (-0.36R), symbol=GBPJPY (+0.14R), symbol=NZDUSD (-0.14R), symbol=USDJPY (+0.18R), session=London/NY overlap (+0.10R), session=NY PM (-0.11R)

## batch3_E6  (n=116)

Win rate 44% · mean +0.154R · **No winner-vs-loser pattern survives the multiple-testing and half-sample checks (treat differences as noise).**

| class | n | share | mean net R | mean best (MFE) | mean worst (MAE) |
|---|---|---|---|---|---|
| WIN | 51 | 44% | +1.236 | 1.77 | 0.36 |
| WRONG_WAY | 44 | 38% | -0.685 | 0.18 | 0.78 |
| STALLED | 10 | 9% | -0.769 | 0.67 | 0.87 |
| GAVE_BACK | 9 | 8% | -0.817 | 1.36 | 0.84 |
| COST_DRAG | 2 | 2% | -0.019 | 1.43 | 0.40 |

Winners vs losers: best excursion 1.766 vs 0.459 R, worst excursion 0.359 vs 0.788 R.

Exits: 14% of losers had been 1R+ ahead

Buckets tested 14 (needs |z| >= 2.91): none survive

## live_ledger  (n=8)

too few scored trades with diagnostics to say anything
