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
- 2026-11-18: owner instruction: gate and headline are now price-only (gross); costs are information only. Logged before any real-data result.
