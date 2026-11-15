# Independent review request: FX Engine v2

You are an independent senior reviewer (quant + software + product). Review the repo
https://github.com/rayyansorefan/Claude-FX-Engine-15.11.26-  branch `engine`  (read CLAUDE.md, STATUS.md, docs/GATES.md,
docs/EXPERIMENTS.md, docs/REJECTED.md, docs/WHITEPAPER_NOTES.md first). The owner is a non-developer product owner.

## What it is
A RESEARCH-ONLY FX engine (never places orders, read-only OANDA practice data, zero LLM at runtime, £0 budget, free tools only).
It should: find <=5 ranked setups/day, monitor them, alert on state changes via Telegram, score every setup as a hypothetical
with executable-side prices and real costs, and honestly prove or disprove an edge. Plus a private visual dashboard.
Hard rules: no look-ahead (close = open + timeframe), stale data must fail loudly, one run_id per setup from creation to outcome,
same code for backtest/replay/live, frozen parameters, pre-registered gates, report negative results plainly.

## Results so far
7 strategy ideas (M15/H1/H4) all negative after stressed costs on ~2.5y of data; last 6 months sealed (holdout never opened).
Live loop, Telegram alerts, SQLite ledger, audit, watchdog and a multi-tab static dashboard are built (48 tests) but NOT yet run live.
Known gaps: VM installer untested; cloud sandbox could not reach OANDA; OANDA prices differ from Pepperstone; market-structure and
news-blackout ideas untested; costs are modelled assumptions.

## Please review, in this priority order
1. BACKTEST VALIDITY (most important). Could a bug or over-pessimistic assumption be making every strategy look negative?
   Check src/fxengine/engine/tracker.py, engine/costs.py, backtest/run.py, setups/v1.py, setups/v2.py, research/stats.py, research/split.py.
   Specifically: entry/exit fill rules (stop vs limit, gaps, slippage), spread added to BID-only history, commission double-counted
   on top of OANDA's already-wide spreads?, swap assumption, same-bar stop-first rule, cooldown logic, trailing stop, bootstrap and
   Bonferroni use, whether the pass rule in run_all.verdict is sound. Also: any look-ahead or leakage anywhere.
2. LIVE LOOP CORRECTNESS & ROBUSTNESS: src/fxengine/live/*.py, audit/run.py. Replay-based tracking, dedupe, retries, stale gate,
   restart safety, timezone/DST, market-closed logic, Telegram failure handling, secrets handling, anything that could silently fail.
3. DASHBOARD: src/fxengine/dashboard/build.py + journal.py. Does it show real substance and stay honest (no invented numbers)?
   Usability on phone and Mac, missing views, misleading charts, accessibility.
4. RESEARCH DIRECTION: given everything, what are the 3 cheapest, most credible next experiments (or is stopping right)?
   Consider costs vs horizon, different instruments, carry, regime filters. Respect the multiple-testing penalty.

## Output format
A prioritised list: severity (critical/high/medium/low), file:line, what is wrong, why it matters, the smallest concrete fix.
Finish with "Top 5 changes to make first". Do not rewrite the project. Do not suggest paid tools or any order placement.
Say clearly what you could not verify.
