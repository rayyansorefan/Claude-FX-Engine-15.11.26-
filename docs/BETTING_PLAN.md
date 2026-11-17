# Betting research engine (research-only) — plan, 2026-11-17
Goal as set by Rayyan: turn £100 into £1,000 with a Bet365 UK account. Same rules as the FX engine: research-only, £0, no Claude at runtime,
pre-registered gates, trial registry, sealed holdout, hypothetical scoring, negative results reported plainly.

## Hard rules (betting-specific)
- The engine NEVER places, edits or cancels a bet, never logs in to Bet365, never holds betting credentials, never scrapes Bet365
  (their terms forbid automation; it risks the account and there is no public API). Rayyan places any bet himself, at his own risk.
- Only money Rayyan can afford to lose entirely. Stake caps are advice in the output, not an instruction to bet.
- Free sources only. Anything needing a card or sign-up is flagged BEFORE use.

## The honest maths (simulated, 20,000 runs each; reproduce with the engine's bankroll simulator once built)
- All-in style staking (each bet sized to reach £1,000 if it wins), even-money-ish odds 2.0:
  - fair odds (no bookmaker margin): 10.0% chance of reaching £1,000 (it is just 100/1000);
  - with a typical 5% bookmaker margin: 8.6% (about 1 in 12), and the other 91% is losing the £100;
  - with a REAL +3% edge over the true probability: 10.6%.
- Small flat stakes (5% of bankroll per bet) at the same odds: 0.15% chance of ever reaching £1,000 before ruin.
- So: a 10x target is a lottery ticket whether or not there is an edge. An edge changes the odds only slightly. Compounding slowly needs a
  large, proven edge AND many bets; the bookmaker margin (4-7% on 1X2) is the main obstacle, and winning accounts get limited.
- The engine's job is therefore: (1) find out whether any rule has a genuine edge after the margin (probably not), (2) if it does, size bets by
  fractional Kelly and report the REAL probability of the target and of ruin, (3) never claim more than the evidence.

## Phases (one per session)
0. Plan + gates (this file). Gates to lock before any result: pass = cluster-bootstrap lower bound of ROI > 0 after margin, beats a random-bet challenger's p95,
   holds in the later half of seasons, Bonferroni over every rule tried; holdout = most recent full season, opened once.
1. Data: football-data.co.uk free CSVs (E0..E3, SP1, D1, I1, F1 from ~2010), Bet365 odds (B365H/D/A), Pinnacle closing odds (PSCH/D/A), max/avg market odds.
   Runs on the VM as a job (the build sandbox cannot reach the site). Quality report + known gaps.
2. Engine core: de-margin (Shin/proportional), closing-line-value, staking (flat, fractional Kelly), bankroll simulator (P(reach £1000), P(ruin), time),
   hypothetical ledger with one run_id per bet.
3. Pre-registered strategy tests (small list): favourite-longshot bias, Pinnacle-closing vs Bet365 gaps (value vs sharp price), best-of-market shopping,
   draw/under bias by league. Each logged as a trial. Include the random-bet challenger.
4. Forward paper-tracking of today's matches. Needs a free odds feed (The Odds API free tier needs a sign-up, no card: FLAG to Rayyan first) and a
   dashboard tab + Telegram, only after Phase 3 shows something real.
5. Post-mortem engine reuse: loss classes (wrong price / variance / margin drag), same strict pattern checks.

## Known gaps / things I will not pretend
- Bet365 closing odds in the data are historical; today's price may differ and Bet365 limits/closes accounts that beat the closing line.
- Free historical data has no stake limits, so achievable profit is overstated by backtests.
- "Sure bets"/arbitrage and matched betting are real but different: small, capped, one-off or account-limiting. Not part of this engine unless asked.

## Status 2026-11-17 (branch `betting-wip`, NOT merged to `engine`)
- Phases 1-3 code built and tested (96 tests pass; synthetic dry run: a fair market shows no edge, a planted 12% mispricing is found only with a large sample; holdout seasons 2526/2627 sealed).
- NO real-data results exist yet. The sandbox cannot reach football-data.co.uk (proxy 403), so the download runs on the VM.
- Fixed this session: Shin margin-removal bisection was reversed (it manufactured fake +10% "value"); missing-odds check.
- Run on the VM (separate clone, never touches the live FX engine):
    1. `cd ~/fx && git fetch origin betting-wip && git show origin/betting-wip:deploy/install_bets.sh | bash`   (clones ~/bets, installs, runs the betting tests)
    2. `cd ~/bets && nohup bash deploy/run_bets.sh > data/bets.log 2>&1 &`   (about 6-10 minutes; then read `docs/results/bets.md`)
- Runner jobs `bets` / `bets_research` are whitelisted in src/fxengine/ops/runner.py but only usable after betting code is merged to `engine` (merging restarts the live FX services: Rayyan's call).
- Phase 4 (forward tracking) needs a free odds feed with sign-up (The Odds API free tier, no card): flagged, not started.
