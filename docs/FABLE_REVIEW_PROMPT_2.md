# Prompt for Fable — independent review of FX Engine v2 after Day 1 (2026-11-16)

You are an independent senior reviewer (quant researcher + site-reliability engineer + product reviewer). Review
https://github.com/rayyansorefan/Claude-FX-Engine-15.11.26-  branch `engine` (code) and branch `vm-results` (files the VM pushes back: data/ops_*.log,
data/ops_report.txt, docs/results/*). Read CLAUDE.md, STATUS.md, docs/HANDOVER.md, docs/DAY1_AUDIT.md, docs/GATES.md, docs/EXPERIMENTS.md,
docs/REJECTED.md, docs/UI_ACCEPTANCE.md first. Run `PYTHONPATH=src pytest -q` (74 tests). The owner (Rayyan, UK) is a non-developer and is frustrated by
having to intervene; the system is meant to run unattended, research-only (never places orders), GBP 0 budget, zero LLM at runtime.

## State to challenge, not accept
- Research: 7 strategy variants negative after stressed costs; sealed holdout (>= 2026-05-15) untouched; R0 (M5-resolution rerun with three cost modes and a
  random-entry challenger) and batch 3 (E6 daily momentum, E7 carry+momentum, pre-registered in docs/EXPERIMENTS.md) are QUEUED on the VM but have not produced valid results.
- Infrastructure: one Google e2-micro VM (1 GB RAM, 2 GB swap), systemd services fxengine (live loop), fxdash (dashboard), fxops.timer (self-update from `engine`
  every 2 min with auto-rollback; whitelisted job queue ops/jobs.txt; ops/control.txt kill/resume; results pushed to `vm-results` via a write deploy key).
- Day 1 outcomes (docs/DAY1_AUDIT.md): OANDA token rejected twice (401), 3-year history never downloaded on the VM, queue ran a re-test on partial data, a heavy job froze
  the VM for ~5 h, cycle success 57% at 14:25 UTC (Gate A needs 99%). Fixes were added today and have NOT yet been proven on the VM.

## Review in this order
1. OPS RUNNER SAFETY & CORRECTNESS (src/fxengine/ops/runner.py, deploy/*.sh, ops/*). It runs as ROOT, pulls code from a public repo and executes whitelisted jobs.
   Look for: command/argument injection (jobs.txt, control.txt, quoting inside `bash -c '...'`), privilege problems (files created by root inside the owner's checkout),
   race conditions between timer ticks, state-file corruption, halted/resume/kill logic holes, rollback logic (does it really restore the old commit and services?),
   what happens if the deploy key is missing/revoked, if `git merge --ff-only` fails, if a job survives a reboot, whether `earlyoom` + `nice` actually protect the live loop,
   and whether a malicious or accidental push to `engine` could do damage.
2. MEMORY/CPU BUDGET on 1 GB: estimate peak RAM of `fxengine.data.build`, `backtest.run_m5` and `backtest.run_batch3` on ~226k M5 rows x 10 pairs x 3 timeframes
   (src/fxengine/backtest/run_m5.py, run_batch3.py, data/store.py). Will they fit? Propose the smallest change (chunking, dtype, per-pair processing) if not.
3. BATCH 3 CORRECTNESS (src/fxengine/data/daily.py, data/rates.py, setups/v3.py, backtest/run_batch3.py, engine/tracker.py `carry_annual`): DST-safe 17:00 New York daily
   bars, 45-day publication lag for rates, signal timing (Friday close), hold-length conversion from calendar exit to M5 bars (`_hold_bars`), carry sign and size
   (financing earned/paid on entry price, 1pp mark-up), challenger fairness, look-ahead anywhere. FRED series IDs in rates.py are UNVERIFIED: say what could go wrong.
4. R0 / COST QUESTION: is "no edge" actually supported? Commission 0.7 pip is added on top of OANDA spreads that are already wide; stressed mode doubles spread; measured mode uses
   the data's own ask-bid with no commission. Check run_m5.py and engine/costs.py for double counting, fill-rule bugs, same-bar stop-first bias, cooldown, trailing logic.
5. LIVE LOOP (src/fxengine/live/*.py, audit/run.py, dashboard/*): stale/market-hours logic (src/fxengine/calendar.py), replay-based tracking, alert dedupe/retry, token-401 handling,
   dashboard honesty (no invented numbers), page build cost, stale-while-revalidate server, JS chart code (dashboard/build.py JS string) for bugs on phone widths.
6. RELIABILITY GATE: given a single free VM with no external dead-man alert, what is the realistic cycle-success and outage profile? What is the cheapest fix that keeps GBP 0
   (including auto-reboot of a hung VM) and does it threaten the free-tier terms?

## Output
Prioritised findings: severity (critical/high/medium/low), file:line, what is wrong, why it matters, smallest concrete fix (a patch or exact code). Then "Top 5 changes to make first".
Say clearly what you could not verify. Do not rewrite the project. No paid tools. Never suggest placing orders. Be blunt.
