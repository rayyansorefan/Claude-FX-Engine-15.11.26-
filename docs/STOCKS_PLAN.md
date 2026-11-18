# Stocks research engine (research-only): plan + pre-registered gates. LOCKED 2026-11-18 before any real-data result.

Owner goal: master short-term trading (days) and longer swing/position trading (weeks to months) on US + UK stocks held in a Revolut account.
Same objectives and rules as the FX engine: research-only, £0, no Claude at runtime, pre-registered gates, trial registry, sealed holdout,
hypothetical scoring, negative results reported plainly.  Loosening any number below needs a plain-English note to the owner and a dated change-log entry.

## Hard rules
- The engine NEVER places, edits or cancels an order and holds NO Revolut credentials (Revolut has no retail trading API anyway). The owner places any trade, at his own risk.
- Free sources only; anything needing a card or sign-up is flagged BEFORE use. No secrets in git.
- Look-ahead is a test failure: a signal at the close of day t uses data up to t only; entry is the NEXT open (day-trade rules decide at the open and enter at that open).
- Every rule/parameter set ever tried is logged in `docs/stocks_trials.jsonl`; multiple-testing penalty = Bonferroni, alpha = 0.05 / (logged trials).
- Parameters are fixed in advance (textbook values, no fitting). Changing one is a NEW trial.

## What "comprehensive research" means here, and what it does NOT mean
The owner asked for: reading earnings and official documents, macro awareness, anticipating price moves, and continually re-checking live setups.
- **Deterministic, point-in-time, free.** Filings and macro data enter as numbers with their real publication timestamps (SEC EDGAR `filed` dates and XBRL company facts for US companies; FRED series and release/FOMC calendars for macro; UK RNS later if a free source exists). Nothing may be used before it was public.
- **Hypotheses are written down first**, then tested like any other rule (examples: post-earnings drift after a large reported-earnings surprise; behaviour around FOMC/CPI days; market-regime filters such as VIX or trend of the index). Each costs a trial.
- **"Anticipating" = conditional statistics, not prophecy.** The engine reports "in situations like this, historically, after costs, X happened, with this much uncertainty". It never claims to know what will happen.
- **No Claude at runtime** (FX engine rule). A model reading filings/news each day would break the £0 budget and make every result unrepeatable. Optional later and only if the owner chooses and pays attention to cost: a *weekly Claude research brief* kept strictly separate, scored on paper like the bookie "tipster", never feeding live signals.
- **"Positively reinforcing setups"** is implemented as *re-checking*, in both directions: every live setup has an explicit invalidation level and a written list of conditions; each after-close scan re-evaluates them, logs what improved AND what got worse, and updates the status (VALID / WEAKENING / INVALIDATED / TARGET HIT). A confirmation rule (for example "add only if X") is allowed only if it has been tested and proven to beat plain holding; until then every such message is labelled UNPROVEN (same as the FX halfway check). Averaging down or ignoring invalidation is never advised.

## Phases (one per session; each must be proven before the next is trusted)
1. **Price engine (this session).** Universe, free daily data (Stooq, run on the VM), quality report, Revolut-style cost model, six pre-registered price rules, no-look-ahead backtester, gates, sealed holdout, dashboard. Result may well be "no edge" (the FX engine found none in 7 variants).
2. **Event layer.** Earnings dates + reported results (EDGAR), macro calendar and series (FRED), regime features; pre-registered event hypotheses.
3. **Live after-close scanner + setup lifecycle** like FX: at most 5 ranked setups, Telegram alerts, invalidation/target monitoring, paper journal, "UNPROVEN" labels. Intraday monitoring needs intraday data (no reliable free long history): daily-bar monitoring first.
4. **Optional, owner's choice:** weekly Claude research brief (paper-scored, separate from signals).

## Universe (v1)
~55 large US stocks + 14 US ETFs + ~30 liquid FTSE 100 stocks + 3 UK ETFs (see `stocks/universe.py`). Mostly available on Revolut: the owner must confirm availability before any trade. Known bias: today's survivors only (survivorship bias flatters long-only results). Reported on every verdict.

## Data
Stooq free daily OHLCV (split-adjusted), no key. History to ~2005 where available. UK prices are in pence; only returns are used. Bars with an absolute daily move over 45% are flagged as probable data errors and any trade touching them is dropped.

## Pre-registered rules (v1, six trials, fixed parameters)
| id | idea | entry (decided at the close of day t; enter the next open) | exit | max hold |
|---|---|---|---|---|
| RSI2_PULLBACK | short-term mean reversion | RSI(2) < 10 and close > SMA200 | close > SMA5 (exit next open) | 10 bars |
| BREAKOUT_20 | breakout / trend | close > highest high of the previous 20 days and close > SMA50 | close < lowest low of the previous 10 days | 60 bars |
| TREND_50_200 | long-term trend following | SMA50 crosses above SMA200 while close > SMA200 | close < SMA50 | 250 bars |
| MOM_12_1 | long-term cross-sectional momentum | month-end: top 20% by return from t-252 to t-21 | none (time stop) | 21 bars |
| GAP_CONT_DAY | day trade, continuation | gap at the open > +2% and prior close > SMA50: buy the open, sell the close | same day close | 0 |
| GAP_FADE_DAY | day trade, reversal | gap at the open < -2% and prior close > SMA200: buy the open, sell the close | same day close | 0 |
Day-trade rules decide on the opening price and fill at it: optimistic by construction (a real order fills a little later), so they get the stressed costs and are flagged.

## Costs v1 (ASSUMPTIONS: the owner must replace them with his real Revolut plan fees; replacing = logged change)
Per side, as a fraction of the trade value. NORMAL / STRESSED:
| item | US stock | US ETF | UK stock | UK ETF |
|---|---|---|---|---|
| spread + slippage | 0.05% / 0.10% | 0.03% / 0.06% | 0.10% / 0.20% | 0.06% / 0.12% |
| commission | 0.05% / 0.12% | 0.05% / 0.12% | 0.05% / 0.12% | 0.05% / 0.12% |
| currency conversion (US) | 0% / 0.25% | 0% / 0.25% | n/a | n/a |
| UK stamp duty (BUY only) | n/a | n/a | 0.5% / 0.5% | 0% |
Costs are shown beside every result (information only, not in the gate).

## Gates
**Changed 2026-11-18 on the owner's instruction (no real-data result existed yet): the headline and the gate use PRICE-ONLY (gross) returns, so the question is "does the setup itself work?". Costs are still computed and shown as two information columns, but no longer decide pass/fail. A setup can therefore pass and still lose money after real Revolut fees.**
Research gate for a rule (all must hold, or it is "no edge" / "inconclusive"):
1. At least 100 independent weeks with a trade (trades are clustered by entry week; many stocks trade the same week so trades are not independent).
2. Mean price-only return per trade > 0 and the lower bound of the cluster-bootstrap CI at the Bonferroni-adjusted alpha > 0.
3. Mean beats the 95th percentile of a random-entry challenger (same holding times, random stocks and dates, price-only).
4. Net mean > 0 in BOTH halves of the research window (by date).
Holdout: the most recent 365 days are sealed. Opened once, for one frozen rule that passed 1-4, logged in `docs/stocks_holdout_log.txt`. A pass needs net mean > 0 with at least 30 trades, otherwise "inconclusive".
Every verdict prints the minimum detectable effect (MDE): "no edge" means "no edge above the MDE".
Benchmark shown beside every result: buy-and-hold SPY and an equal-weight buy-and-hold of the universe. A rule that cannot beat doing nothing is not worth the effort.

## Change log
- 2026-11-18: created (before any real-data result).
- 2026-11-18 (design fix, before any holdout look): the sealed boundary was computed as 'latest date minus 365 days', which would have moved every day. It is now FIXED at 2025-11-18 (the boundary of the first real run, so no sealed data has influenced any result); everything from that date on is sealed/forward data. Holdout command: `python -m fxengine.stocks.run --holdout RULE --why "..."`, once per rule, only for a rule that passed the gate, logged in docs/stocks_holdout_log.txt.
- 2026-11-18: owner instruction: gate and headline are now price-only (gross); costs are information only. Logged before any real-data result.

## Update 2026-11-18 (later): first real results, stress checks, sealed year, forward test
- First real-data run (103 symbols, 2000-2025, price-only gate): RSI2_PULLBACK, MOM_12_1, GAP_FADE_DAY passed the gate.
- Stress checks: GAP_FADE_DAY rejected (top 1% of trades = 94% of all gains, one year at +46% per trade: outliers/data errors, ETF-only range includes zero).
  RSI2_PULLBACK survives (ETF-only +0.36% [+0.22%, +0.50%], trimmed +0.40%, crash years removed +0.42%). MOM_12_1 survives with thinner evidence (ETF-only n=192, survivorship-flattered).
- Sealed boundary fixed at 2025-11-18 (it was a moving 365-day window: fixed before any holdout look).
- Holdout opened ONCE for RSI2_PULLBACK on 2026-11-18 (docs/stocks_holdout_log.txt): n=800, mean +0.536%, 65.5% wins, range [+0.14%, +0.94%] -> PASS. Needs forward confirmation.
- Forward test (from 2026-11-18): the scanner tracks EVERY signal of the four swing rules, mirrors the research's one-position-per-stock rule, and closes trades with the same backtest code, so live results are directly comparable. Nightly timer (weekdays 22:45 UTC).

## Update 2026-11-18 (evening): the two engines LEARN FROM EACH OTHER, kept separate (owner instruction, corrected)
**What the owner wants, stated precisely:** FX and Stocks stay SEPARATE (separate tabs, separate paper accounts, separate rules and results; NO combined/merged view). They must LEARN from each other.
**How "learn from each other" is implemented (the learning link, stocks/crossctx.py):**
- Each engine publishes its daily market read, point-in-time (a value on a date uses data up to that day's close only), with full history.
  - Stocks -> FX: docs/results/stocks_context_history.csv + stocks_context.json (equity trend, breadth, volatility, 5-day move). The FX engine's entry-filter study can test these on its own trades.
  - FX -> Stocks: USD strength and risk mood (AUDJPY) from free daily FX rates (history to 2003), computed on the stocks side and stored on EVERY stock setup when it fires. The stocks entry-filter study (phase D) tests whether they improve the stock rules.
- Cross-features are ordinary pre-registered conditions: chosen on the earlier 60% of history, validated ONCE on the later 40%, per rule, with the throughput guard; adopted only with evidence, and announced. Each engine keeps its own learning log.
- Methods are shared too: both use the same rules of evidence (pre-registered tests, sealed period, forward test, honest 'no edge').
- A combined tab was built by mistake (a display, not learning) and removed the same day.

**Done (this session):**
- Stocks paper account: £2,500, £20 risk per trade (1R) sized from each setup's own invalid-below level (none -> 10% below entry), max 25% of the account per position, no leverage, takes every new setup of a rule that PASSED the research gate (strongest first), same entry/exit dates and prices as the research, GBPUSD-converted, UK pence handled. Rebuilt deterministically from the setup ledger every night (stocks/account.py).
- Learning link (stocks/crossctx.py): daily context history (SPY trend, breadth, volatility, USD strength, risk mood), published for FX, stored on every setup, tested for look-ahead.

**FX methods to port to stocks (each pre-registered, validated on later unseen data, announced when it changes anything):**
1. Record market context when a setup fires (market regime, breadth, volatility rank, trend strength, extension, relative strength, day of week) - FX does this at entry.
2. Per-trade post-mortem for every closed trade: best/worst point (MFE/MAE) and a cause class; per-rule tally.
3. Entry-filter study: named conditions on that context, chosen on the earlier 60% of history, validated ONCE on the later 40%, per rule; throughput guard so filters cannot starve the engine of setups.
4. Exit shadow-replay: every finished trade replayed under alternative exit rules (trailing stop, profit target, time stop); a change is adopted only with evidence on unseen data AND a weekly review.

**Build order (one verified step at a time; each needs a VM run, so they are not piled into one unverified drop):**
- A. International universe (Revolut's ~36 countries): per-market tickers, currencies, GBP conversion, country on every setup. Rules are FROZEN; the new markets are an out-of-sample generalisation test, reported separately (the sealed year was already opened once for RSI2 on US/UK, so international results are not a clean holdout).
- B. Technical-indicator batch 2 (pre-registered before any result; literature-backed, fixed parameters): 52-week-high momentum, Donchian 55 breakout, volume-confirmed breakout, ADX trend, Bollinger reversion, internal-bar-strength reversion, stochastic pullback, MACD (a popular indicator, tested honestly), relative-strength leaders pullback. Each counts toward the multiple-testing penalty.
- C. Events layer (deterministic, point-in-time, free): SEC EDGAR filings (8-K item 2.02 earnings releases with acceptance timestamps, XBRL company facts for reported revenue/EPS/margins), FRED macro series, FOMC/CPI/NFP calendar; hypotheses written down first (post-earnings drift, pre-earnings run-up, macro-day behaviour, regime filters). Needs the SEC contact string for its User-Agent (owner decision).
- D. Entry-filter study + exit shadow-replay (items 3-4 above) once enough closed forward trades exist.
- E. Cross-engine: shared event calendar (earnings, macro) used by both engines' studies; one daily brief per engine (Telegram, owner's decision); per-setup "assessment" refreshed nightly. (Context feeds are already built: see above.)

## Batch 2 of pre-registered technical rules (locked 2026-11-18, BEFORE any result; textbook parameters, no fitting). Now 15 trials -> alpha = 0.05/15.
HIGH52_MOM (month-end, within 5% of the 52-week high and up over 126 days; George & Hwang), DONCHIAN_55 (55-day breakout, exit 20-day low), VOL_BREAKOUT (20-day high on 2x volume, above the 50-day),
ADX_TREND (ADX crosses 25, +DI > -DI, above the 50-day; exit ADX < 20 or below the 50-day), BOLLINGER_REVERT (below the lower 20/2 band in an uptrend; exit at the middle band),
IBS_REVERT (internal bar strength < 0.2 in an uptrend; exit above the prior high), STOCH_PULLBACK (%K(14) < 20 in an uptrend; exit %K > 70), MACD_CROSS (12/26/9 cross-up below zero in an uptrend; popular, tested honestly),
RS_PULLBACK (beat the S&P over 126 days, RSI(5) < 30, in an uptrend; exit above the 5-day average). Gate unchanged. Measured gate false-pass rate on random markets: 1 false pass in 9 markets (~90 rule-runs), i.e. about the 5% family-wise design:
no pass is trusted alone (sealed year + live forward test still required). The sealed year stays sealed for these rules until one passes the stress checks.

## Events layer (pre-registered 2026-11-18, before any result)
Sources (free, official, point-in-time): SEC EDGAR submissions + XBRL company facts (US companies), FRED (VIX, 10y-2y curve, high-yield spread). The SEC contact string lives only on the VM (data/stocks/sec_contact.txt), never in git.
Every earnings number is dated by its release (8-K Item 2.02 filing date) and uses each quarter as FIRST reported (restatements ignored). Fiscal-year-end releases (annual 10-K) are skipped on purpose (no quarterly fact). Macro values are lagged one trading day.
- Rule PEAD_SUE (trial 16, fixed): after a standardised surprise SUE >= 2.0 (seasonal random walk, >= 6 past year-on-year changes), EPS up and revenue not down: signal at the close of the first trading day AFTER the filing date, buy the next open, hold 40 bars. (Bernard & Thomas post-earnings-announcement drift.)
- Context candidates recorded on every setup for the entry-filter study (phase D): days since the last earnings release, VIX level and its z-score, yield-curve slope, credit-spread z-score, plus the equity/USD/risk-mood context. Chosen on the earlier 60% of history, validated once on the later 40%.
- Not yet built: text of filings (risk-factor changes, tone), guidance, analyst estimates (no free source), UK/EU filings, macro release calendar and surprise.
Generalisation: each rule's result is reported separately for the markets it was found in (US+UK) and for the other countries, which it was never looked at in.

## Results of the first full run (2026-11-18, 16 rules, 253 symbols, 2000-2025; sealed year untouched except RSI2 opened once)
Passed the price-only gate: RSI2_PULLBACK, BOLLINGER_REVERT, IBS_REVERT, STOCH_PULLBACK, RS_PULLBACK (five ways of buying a sharp short-term dip in an uptrend: ONE effect, so not five independent discoveries; ETF-only checks hold for all), MOM_12_1 (month-end momentum), GAP_FADE_DAY (REJECTED: top 1% of trades = 89% of gains, one year +23% per trade = outliers).
Did not pass: breakouts/trend (BREAKOUT_20, DONCHIAN_55, VOL_BREAKOUT, ADX_TREND, TREND_50_200, MACD_CROSS: positive on average but no better than random entries held as long, i.e. market drift, not skill), HIGH52_MOM, GAP_CONT_DAY (loses). PEAD_SUE: 102 trades from 53 companies, range [+1.1%, +7.1%], below the random 95th percentile and under 100 weeks: INCONCLUSIVE, needs more companies (universe widened to 157 US stocks).
Fixes after the run: paper account holds one position per stock across rules and ranks rules by research gain; macro data falls back to Yahoo (VIX, 10y-13w curve) when FRED times out (it did, no macro context was recorded).
Next: entry-filter study on the historical trades using the recorded context (equity regime, breadth, VIX, USD/risk mood, days since earnings), validated on later data; keep the forward test running (tracks every signal of every swing rule).

## Entry-filter study (built 2026-11-18, pre-registered: 15 conditions + all pairs = 120, fixed thresholds; stocks/filters.py)
For each rule that passed: choose the best condition on the EARLIER 60% of the research window, validate it ONCE on the LATER 40%; a condition must keep at least half the setups; helpful only if the clustered 95% range of its improvement on the unseen 40% is above zero.
Measured behaviour on synthetic data: finds a planted real condition; adopts a useless one in at most 1 of 8 noise data sets. Nothing is applied automatically: adoption is a written decision (ops/stocks_filters.json), announced.

## First entry-filter study results (2026-11-18)
Six rules studied. HELPFUL on the unseen later 40%: BOLLINGER_REVERT and STOCH_PULLBACK, both with "US dollar not surging (from the FX data) & stock 5%+ above its 200-day": improvement +0.30% [+0.01, +0.72] and +0.35% [+0.00, +0.94]: marginal, and the two rules are near-duplicates, so ONE finding. Not helpful: RSI2 (the condition helped, +0.11% [+0.02, +0.20], but would remove more than half the setups: the throughput guard refuses it), MOM_12_1, IBS_REVERT, RS_PULLBACK.
Decision (written, per the plan): NOT adopted. Both are CANDIDATES (ops/stocks_filter_candidates.json): the scanner tags each new setup that meets the condition and the Performance tab reports live results with and without it; the tag never removes a setup. Adoption needs live evidence.
