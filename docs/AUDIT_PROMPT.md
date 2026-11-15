# Independent audit: is FX Engine v2 best placed to achieve its 4 objectives?

You are an independent senior auditor (quant researcher + software architect + product reviewer). Audit the repo
https://github.com/rayyansorefan/Claude-FX-Engine-15.11.26-  branch `engine`. Start with CLAUDE.md, STATUS.md, docs/GATES.md,
docs/EXPERIMENTS.md, docs/REJECTED.md, docs/WHITEPAPER_NOTES.md, docs/results/. Run the test suite (pytest) and the code yourself
where you can. The owner (Rayyan, UK) is a non-developer product owner with a paper account treated as GBP 2,500, 0.8% risk (GBP 20) per trade.

## The 4 underlying objectives
1. ANALYSIS: analyse FX pairs with a small set of NON-REDUNDANT indicator families (trend, momentum, volatility, market structure/key
   levels, session/time-of-day, currency strength/correlation, scheduled-news blackout); each must earn its place through incremental
   out-of-sample value; log rejects.
2. PUBLISH & MONITOR: each day publish the best setups (quality over quantity, max 5, "none today" is valid) with pair, direction, entry
   zone, stop, targets, expiry, invalidation rule and a two-line reason; monitor all day and alert on pre-defined state changes.
3. AUTONOMY: runs unattended (supervised process, auto-restart, watchdog, dead-man alert); no babysitting; escalate only for credentials
   or money. Zero Claude usage at runtime; GBP 0 budget; free tools only.
4. HONEST SCORING: score every setup as a hypothetical with executable-side prices and real costs; track whether setups make money;
   never claim an edge without evidence (pre-registered gates, walk-forward, sealed holdout, Monte Carlo, multiple-testing penalty).
Plus: a clear private visual dashboard, and lessons from the previous engine (no look-ahead, stale data fails loudly, one run_id per setup,
no stacked vetoes, real broker costs, frozen parameters).

## Current state (claims to CHALLENGE, not accept)
- Data: OANDA practice bid/ask, 10 pairs, ~3y M5. Costs are modelled (spread x2, 0.7 pip commission, slippage on stops, swap), not Pepperstone-measured.
- Research: 7 strategy variants on M15/H1/H4 all negative after stressed costs; last 6 months sealed and never opened; E3 filters, market structure
  and news-blackout NOT tested.
- Built: shared Tracker for backtest/replay/live, SQLite ledger, live loop, Telegram alerts, daily brief/EOD/audit, watchdog, multi-tab
  static dashboard + local server, VM installer (Google e2-micro + Tailscale). Live loop and VM NOT yet run in production.
- Everything published by the live loop is labelled UNPROVEN because every tested rule failed.

## What I need from you
A. VERDICT PER OBJECTIVE: score 1-5 with evidence for each of the 4 objectives and for the dashboard. What exactly is missing?
B. IS THIS THE BEST ARCHITECTURE? Compare with realistic alternatives (e.g. different data source, bar-level vs tick, event-driven vs
   polling, GitHub-hosted vs VM, other instruments, a different research framing such as carry/regime/cross-asset, or stopping and
   repurposing as a discipline/journaling tool). State which you would choose and why, given GBP 0 and no paid data.
C. TEST IT: try to BREAK it. Find look-ahead/leakage, cost double-counting or over-pessimism that could be falsely killing every strategy
   (OANDA spreads are already wide; commission is added on top), fill-rule bugs, statistical errors in the bootstrap/Bonferroni/pass rule,
   replay/dedupe/restart bugs, timezone/DST/market-hours errors, secrets exposure (repo is public), silent-failure paths, and dashboard
   statements that could mislead. Give a minimal reproduction where possible.
D. DOES THE EVIDENCE SUPPORT "NO EDGE FOUND"? Or is it "no edge found with this implementation"? What single re-test would settle it?
E. RESEARCH PLAN: the 3 cheapest credible next experiments (or a justified recommendation to stop), respecting the multiple-testing penalty.

## Output
1) Scorecard table (objective, score, evidence, gap). 2) Prioritised findings: severity (critical/high/medium/low), file:line, issue, why it
matters, smallest fix. 3) "Top 5 changes to make first" with effort estimates. 4) What you could not verify. Do not rewrite the project,
do not suggest paid tools, never suggest placing orders. Be blunt; the owner wants the truth, not reassurance.
