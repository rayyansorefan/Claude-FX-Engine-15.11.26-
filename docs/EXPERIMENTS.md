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

# R0 — M5-resolution rescoring, pre-registered 2026-11-15 (NOT a new idea; the seven frozen rule sets are unchanged)
Why: the original runners resolved fills/stops/targets on the signal bar (M15/H1/H4). The live loop resolves them on M5 bars. On a 4-hour bar the conservative rules ('stop beats target in the same bar', 'no target on the entry bar') bite far harder, so the H4 verdicts carry an unknown pessimistic bias, and live scores would never be comparable with research scores.
How: `python -m fxengine.backtest.run_m5`. Same data window, holdout untouched, same cooldown. Costs: stressed (headline), normal, measured (OANDA ask-bid from the data, no commission). Cluster bootstrap by pair-day. Random-entry challenger (3,000 random setups per variant with the same mechanics). MDE printed.
Decision rule: a variant is a CANDIDATE only if, under STRESSED costs, the penalised cluster-bootstrap lower bound > 0 AND its mean beats the challenger's 95th percentile AND 3 of 4 years positive AND positive without its best pair. A candidate then goes to the holdout under docs/GATES.md. Otherwise the 2026-11-15 'no edge found' verdict stands, now stated as 'no edge above the printed MDE'.
Counts as 1 trial (alpha becomes 0.05/11). Runtime: roughly 1-3 hours on the e2-micro VM.

# BATCH 3 — pre-registered 2026-11-16 BEFORE any result. Reason: literature review (see docs/LITERATURE_NOTES.md).
Different STYLE from batches 1-2: slow, low-turnover, daily bars (institutional factor style). Same data window, costs, holdout (sealed),
gates and decision rule. Trials +2 (E6, E7). Caveat: chosen after seeing batches 1-2 fail on the same data, so a pass is provisional
until the sealed holdout and a forward test confirm it. Run on the VM via the M5-resolution driver (track_arrays), never on signal bars.
## E6 — time-series momentum, daily
- Daily bars close 17:00 New York (fxengine.calendar). Universe: the 10 pairs. Rebalance weekly at the Friday daily close.
- Signal: sign of the 60-trading-day return (long if > 0, short if < 0). One setup per pair per rebalance; if the sign is unchanged, the
  running position continues (no new setup, no extra costs).
- Stop: 3 x ATR(20, daily) from entry; no profit target (practical none, 10 ATR); exit at the first rebalance where the sign flips,
  or the stop, or 60 trading days. Entry at the next bar open after the signal bar.
- Costs: stressed as before PLUS, in a second reported column, MEASURED (data ask-bid, no commission) with swap at the pessimistic rate.
## E7 — carry + momentum (BLOCKED until data exists)
- Needs historical policy/short rates per currency (free sources: central bank / FRED series) to build interest differentials, and
  real OANDA financing rates for swap. Rule: rank the 8 currencies by 3-month rate; long highest-carry vs lowest-carry pairs in the
  momentum-confirmed direction (E6 sign agrees). Swap is EARNED/PAID by sign, not assumed adverse. Details to be pre-registered once
  the rate data and its known gaps are documented in docs/DATA_SOURCES.md. Do not run E7 before that.
## Decision rule: identical to batch 1 (penalised CI low > 0, n >= 100 independent pair-days, >= 3 positive years, not one pair,
## and it must beat the random-entry challenger). Report the minimum detectable effect with every number.

## Batch 3 — implementation details frozen 2026-11-16 (code: setups/v3.py, backtest/run_batch3.py; written BEFORE any batch-3 result)
- Daily bars close 17:00 New York (data/daily.py, DST-safe). E6 and E7 act only on the Friday 17:00 NY close.
- A signal is emitted when the weekly position state CHANGES to long/short; the position is held until the state next changes, the 3-ATR
  stop, or 84 calendar days. Entry is a stop order at the Friday close (the weekend gap is paid). ATR = Wilder ATR(20) on daily bars.
- E6 state = sign(close / close[-60 daily bars] - 1). E6 uses the old pessimistic swap model (0.3 pip/night against) in all cost modes.
- E7 state = sign(60-day return) if the rate differential (base minus quote, percentage points, KNOWN at the close) has the same sign and
  |differential| >= 1.0pp, else flat. Carry per position = direction x differential - 1.0pp/year broker mark-up, earned/paid per calendar day
  held on the entry price (differential frozen at entry). Rates: OECD 3-month interbank, monthly, from FRED (series ids in data/rates.py,
  UNVERIFIED until run on the VM); a value is treated as known 45 days after the start of its month. E7 runs ONLY if rates have no gaps.
- Challenger: random Friday close, random direction, same stop/target ATR multiples and a hold length drawn from the real holds; for E7 it
  also earns/pays carry by its random direction, so structural carry in the mechanics is not credited to the strategy.
- Costs reported in three modes as in R0 (stressed, normal, measured). Gate: unchanged. Trials: E6 +1, E7 +1.
