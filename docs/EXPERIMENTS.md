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
- Stop-out semantics (stated 2026-11-16 after review, no change to code): `prev` is the weekly STATE, not the position. After a stop-out E6/E7 stay flat until the state next flips (the sign must change away and back), they do NOT re-enter on the next Friday. Changing that would be a rule change and a new trial.
- Costs reported in three modes as in R0 (stressed, normal, measured). Gate: unchanged. Trials: E6 +1, E7 +1.

## Exit-rule test, 9 variants (pre-registered 2026-11-17 BEFORE any result; revised the same day at Rayyan's request: no instant exits, test several, pick the best fairly)
Question: after a live H1 trade has been well in profit, does a protective exit beat the frozen exits (stop / 2R target / time limit)?
Rules (only the exit changes; signals, fills, costs identical). None closes at market: each only places a stop at least 0.15R behind the current price and never loosens one.
A1-A3 break-even stop once the peak reaches 0.75R / 1R / 1.5R. B1-B3 trail the stop 0.5R / 1R / 1.5R behind the peak (after +1R). C1-C3 keep 40% / 50% / 60% of the peak gain (after +1R).
Not tested (tracker has no partial closes yet): partial exits.
Data: v1_H1 rules at M5 resolution, research window only (holdout sealed). Costs: stressed and measured.
Selection: pick the best rule on the EARLIER half of the trades (stressed delta), then test ONLY that rule on the LATER half: one test, paired per-trade difference vs the frozen exit, cluster bootstrap by pair-day.
Pass (candidate only): lower CI bound > 0 under BOTH cost models on the later half. A pass = CANDIDATE for a new frozen version, then a forward test; nothing changes in the live loop.
Registry: the 9 rules are logged as trials (raises the bar for later tests). Report winners cut short vs losers saved.

## Entry-filter study (pre-registered 2026-11-17/18 BEFORE any result; requested by Rayyan: improve accuracy with more than one rule)
Question: do conditions recorded at signal time separate better setups from worse ones, per rule, on unseen data?
Context (features/context.py, closed bars only): volatility rank (ATR percentile over 100 bars), trend strength with the trade (EMA50-EMA200 in ATRs), stretch from EMA20 (ATRs),
4h trend agreement, hour, weekday. Fixed family (learn/filters.py): 12 single conditions + all 66 pairs. No other conditions will be tried.
Data: R0 per-trade results (v1_H1 split into asia_breakout / trend_pullback / range_reversion, E1_strength, E2_donchian), research window only, holdout sealed.
Per rule: earlier 60% = discovery (best mean net R keeping >= 40% of trades and >= 150 trades, stressed costs); later 40% = validation (ONE filter, ONE test per cost model).
Pass (candidate): clustered lower bound of (kept mean - all mean) > 0 at alpha 0.05 / 5 under BOTH stressed and measured costs AND kept mean above the 95th percentile of random subsets of equal size.
Reported honestly: a candidate may only make a losing rule LESS bad. A candidate is applied only by a deliberate, version-controlled switch (ops/filters.json) and announced; the live loop counts filtered setups.
Registry: 5 trials (entry_filter_<rule>).

## Profitability search (pre-registered 2026-11-27 BEFORE any result; reason: all 5 live strategies net-negative in research; cost kills edge on M15 stops)
Problem: M15 stops = 10-12 pips = 0.1-0.2R cost per trade. All five live strategies have zero/negative gross edge at normal costs. Increasing live-trade volume will only confirm losers, not find winners.
Solution: test regime/session/HTF-alignment filters to concentrate edge (fewer setups, higher win rate, wider stops/faster targets). Same data/holdout/gates as before. Trials: +3 (E8_regime, E9_session, E10_htf_align). Max Bonferroni alpha = 0.05/14.

### E8 — volatility-regime gate (all five live strategies + R0 baseline re-tested through it)
- Added to run_m5 as a data-collection filter (not changing entry rules).
- Publish only setups on days where ATR(20, H1) is in the middle 50%-80% (avoid extreme chop and extreme spikes separately).
- Expected: reject ~50% of setups, keep those in trend-favourable regimes. Average R should improve (or confirm: edge is zero everywhere).
- Decision rule: stressed CI low > 0 (better than unfiltered baseline R0) on LATER half of trades (out-of-sample) AND same gate increases Sharpe by > 0.1.
- If pass: apply to live; if fail: edge is in choppy days (counterintuitive) or doesn't exist in this regime.

### E9 — session-time gate (per-pair optimal hours; same approach as E8)
- Publish only setups during the pair's highest-volatility session (EURUSD/GBPUSD 08:00-11:00 UTC, USDJPY 21:00-00:00 or 00:00-09:00 UTC, etc.).
- Expected: fewer setups, faster target-hits (volatility is higher). Average R should improve.
- Decision rule: stressed CI low > 0 versus unfiltered baseline AND Sharpe improved.

### E10 — higher-timeframe (H4) alignment gate
- Publish breakout entries only when H4 is also in a breakout (highest high of 55 bars on H4). Range reversions only when H4 is consolidating.
- Expected: fewer but higher-quality setups. Average R improves.
- Decision rule: stressed CI low > 0 versus unfiltered AND win rate improves.

### Registry: 3 trials (regime / session / htf_align). If all three fail: "cost and regime are the problem; strategy idea is not viable without higher timeframe or macro context." No further threshold-based tweaking tested.
