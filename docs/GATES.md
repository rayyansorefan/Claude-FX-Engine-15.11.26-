# Pre-registered gates — LOCKED 2026-11-15 (before any forward test or any real-data backtest)

Loosening any number below requires telling Rayyan in plain words and a dated entry in the
Change log at the bottom. Never edit a number silently.

## Fixed experimental rules
- Costs: `engine/costs.py` v1, STRESSED mode (spread x2, thin hours x2.5, slippage on stop
  fills, 0.7 pip commission, 0.3 pip/night swap against). Pessimistic assumptions until
  replaced by measured Pepperstone spreads (any replacement is logged here).
- Scoring unit: net R (1R = planned |entry - stop|), executable-side prices, same code as live.
- Holdout: all data from 2026-05-15 UTC onward. Opened ONCE, for the single frozen final
  configuration, logged in `docs/holdout_log.txt`. Walk-forward: 180d train / 30d test, rolling.
- Trial registry `docs/trials.jsonl`: every variant tried is logged; multiple-testing penalty is
  Bonferroni, alpha = 0.05 / (number of logged trials).
- Same-bar ambiguity: stop wins; entry bar can only stop out.

## Research gate (history, must pass before going live)
Frozen config must show positive net expectancy in walk-forward OOS AND on the holdout, with the
penalised bootstrap lower bound > 0, and at least 100 triggered setups in each of OOS and holdout
(if history is too short to give 100 holdout setups, that is reported as "inconclusive", not a pass).

## Gate A — reliability (10 weekday sessions of live running)
1. >= 99% of scheduled cycles complete.
2. In-session data never older than 5 minutes (any breach = fail unless alerted within the cycle).
3. 100% of setups have complete lifecycle records; funnel counts reconcile exactly.
4. Every alert is delivered before the setup's expiry (late alerts are counted and reported).
5. Zero look-ahead test failures.
If free infrastructure cannot meet this: report the real numbers and propose the cheapest fix.

## Gate B — research economics (forward, hypothetical)
- At least 100 triggered, scored setups from the frozen config.
- Net expectancy after STRESSED costs > 0 and 95% bootstrap lower bound > 0, with alpha
  divided by the number of setup types published (Bonferroni). Interval reported either way.
- Halfway HOLD/EXIT advice is only labelled "proven" if it beats plain holding in OOS and holdout;
  otherwise every message carries the word "unproven".

## Gate C
If B passes, report plainly to Rayyan. Trading real money is his decision, outside the engine.

## Change log
- 2026-11-15: created.
- 2026-11-15 (TIGHTENED, from white-paper audit): Gate B counts INDEPENDENT scored pair-days: at most one scored setup
  per pair per day (the first fill), at least 100 of them across at least 20 distinct scored days; the bootstrap is
  clustered by day. Previous "100 setups" wording is superseded by this stricter rule. Receipt after expiry = late.
