# Pre-registered experiments — written 2026-11-15 BEFORE any result for them exists
Cap: at most 3 more ideas (E1, E2, E3). Each runs ONCE with the frozen parameters below; no tuning.
Data/costs/holdout/gate maths exactly as docs/GATES.md. Trials counted: 6 so far; E1 +1, E2 +1, E3 up to +2 (max 10),
so the penalised alpha is at most 0.05/10. Honest caveat: these ideas were chosen AFTER seeing v1 fail, on the
same 2023-11..2026-05 data, so a pass is only provisional until the untouched holdout and forward test confirm it.

## E1 — currency-strength momentum, H4
- Strength(ccy) = mean over the available pairs of 30-bar (5-day) log-return, signed (+ if base, - if quote).
- Pair differential d = S(base)-S(quote); z = d / rolling std(d, 500 bars, min 250).
- Signal at each H4 close if |z| >= 1.5 AND the pair is in the top 3 |z| across all 10 pairs that bar. Long if z>0.
- Entry: stop-order at the signal close. Stop 2 ATR(14), target 4 ATR (2R). Expiry 2 bars. Max hold 12 bars (2 days).
- One open setup per pair at a time.

## E2 — Donchian trend-following with wide stops, H4
- Long when close > highest high of the previous 55 bars (first break) AND EMA50 > EMA200; short mirrored.
- Entry: stop-order at the signal close. Stop 3 ATR(14), target 6 ATR (2R). Expiry 3 bars. Max hold 40 bars (~7 days).
- One open setup per pair at a time.

## E3 — filters (ONLY run if E1 or E2 has penalised CI lower bound > -0.05R)
- Apply to the better of E1/E2 once: (a) only signals created 07:00-17:00 UTC; (b) skip the first Friday of each
  month (US jobs report day). Each filter is judged by its marginal effect and the change in setup frequency.

## Decision rule
Pass = Gate-B maths on the research period (penalised lower CI > 0, n >= 100) AND positive in at least 3 of the
4 calendar years AND not driven by one pair. Anything else = rejected and logged in docs/REJECTED.md.
If E1, E2 (and E3 if run) all fail: report "no edge found in simple public-data FX setups".

# BATCH 2 — pre-registered 2026-11-15 (before any result). FINAL cap: E4 and E5 only.
Reason: batch 1 used only fixed 2R targets. Trend/momentum edges usually come from letting winners run.
Trials: 8 so far; +2 = 10; penalised alpha = 0.05/10. Same data/costs/holdout/decision rule as batch 1.
## E4 — E2 entries (H4 Donchian-55 + EMA50/200 filter) with a trailing exit
- Initial stop 3 ATR. No practical target (15 ATR). Trail: after each closed bar, stop = best of (current stop,
  lowest low of last 20 bars for longs / highest high for shorts), applied from the NEXT bar, never loosened.
  Expiry 3 bars. Max hold 120 bars (~20 days). Swap charged (pessimistic model).
## E5 — E1 entries (H4 currency-strength momentum) with the same trailing exit
- Initial stop 2 ATR. Target 10 ATR (practical none). Trail 20 bars as above. Expiry 2 bars. Max hold 60 bars.
## Decision rule: identical to batch 1. If both fail: "no edge found" is final for this search; no further ideas
## will be tested without Rayyan proposing one.
