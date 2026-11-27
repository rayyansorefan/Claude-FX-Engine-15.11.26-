**2026-11-17:** VM deployed the hardened runner and ran `harden` (earlyoom thresholds relaxed after it killed every job; 2 GB swap file). Batch 3 (E6) ran on real data: +0.15R/trade, 116 trades, CI [-0.14, +0.46], FAILS gate (12 trials); E7 skipped (FRED EUR/GBP 3-month series end Jan 2026). R0 not yet valid (old run killed; needs rerun with diagnostics). Built: automatic trade post-mortem (`research/diagnose.py`: wrong-way / gave-back / stalled / cost-drag, strict winner-vs-loser scan, candidate log docs/hypotheses.jsonl, EOD 'why trades lose' line); dashboard and alerts now show UK time (GMT/BST); dashboard auto-reloads every 60 s; runner deploys dashboard/live changes during a job. Heavy jobs (batch3, r0) HELD while a betting job shares the VM; re-queue when memory allows. NO vm-results push since 09:29 UTC: check whether the VM is healthy. Betting work is in another chat (branch betting-wip), not this one.
**2026-11-15 (Astra fixes applied, 56 tests pass):** price store is locked + atomic (research and live loop can share it); DST-aware market calendar; freshness = oldest pair, 12 min; scan result persisted and dashboard setups come from the ledger; every setup carries an invalidation level and a two-line reason; error alerts repeat and announce recovery; off-host dead-man via HC_PING_URL (healthchecks.io, free: add it to .env on the VM); cluster bootstrap + minimum detectable effect + random-entry challenger in the stats; NEW runner `fxengine.backtest.run_m5` (R0: same rules rescored on M5 bars, three cost models incl. measured OANDA spread) - MUST BE RUN ON THE VM: `cd ~/fx && bash deploy/update_vm.sh && nohup .venv/bin/python -m fxengine.backtest.run_m5 > data/r0.log 2>&1 &` (PYTHONPATH=src). Dead cTrader/Dukascopy code removed. STILL TO DO BY RAYYAN: (1) make the repo private or accept that its history is public; (2) copy docs/trials.jsonl and docs/results/*.md|json from the VM into git so the Bonferroni count and the E1/E2/E4/E5 numbers are verifiable; (3) healthchecks.io URL in .env; (4) GCP upgrade decision before ~day 80.
# STATUS

**DATA SOURCE 2026-11-15:** cTrader Open API dropped (identity verification needed). Dukascopy rate-limited. OANDA practice is the research and live source.
**RESEARCH VERDICT 2026-11-15: NO EDGE FOUND** (v1 M15, v1 H1, E1, E2 all failed; holdout never opened). Awaiting Rayyan's choice of next direction (see chat): scoreboard engine vs stop vs new research.
**Built 2026-11-15:** live scanner (`python -m fxengine.live.scan`), sizing, institutional static dashboard (`python -m fxengine.dashboard.build` -> dashboard/index.html). Batch 2 (E4/E5) also FAILED. 42 tests pass.
**Built 2026-11-15 (later):** live loop (`fxengine.live.loop`), SQLite ledger, Telegram alerts, daily brief/EOD/audit, watchdog, deploy/install_vm.sh (UNTESTED on a real VM), trade-journal panel on dashboard. 48 tests pass. NOT yet run live: needs Telegram bot token + chat id.
**Dashboard v3 (multi-tab: overview, research, charts, positions, performance, journal, system) built; review prompt in docs/REVIEW_PROMPT.md.**
**Live dashboard server:** `start_dashboard.command` (double-click) or `python -m fxengine.dashboard.serve --open --refresh --auto 60` -> http://localhost:8787, rebuilds on every refresh.
**Audit prompt for an independent reviewer: docs/AUDIT_PROMPT.md. VM install (deploy/install_vm.sh) awaiting Rayyan's Step 1-3.**
**LIVE 2026-11-15:** VM fx-engine (GCP e2-micro us-central1) runs engine+dashboard+watchdog via systemd; dashboard on port 8787 over Tailscale (private IP, not published); research_once.sh started manually (check data/research_once.log). GCP free trial ends ~day 90: Rayyan must decide on upgrade (flag at day ~80). Waiting on Astra/Fable review feedback.
**2026-11-16:** batch 3 (E6/E7) built + tested + pushed (68 tests). Ops runner (self-update + whitelisted jobs queued in ops/jobs.txt, results pushed to branch `vm-results`) built; Rayyan must run ONCE on the VM: `cd ~/fx && git pull && bash deploy/install_ops.sh` (adds a deploy key on GitHub). After that: queue jobs by editing ops/jobs.txt and pushing. VM finding: 3-year M5 download had never run on the VM (R0 saw no data) -> queue `history` then `r0` then `batch3`.
**2026-11-16 night: Astra review (ASTRA_REVIEW_2026-11-16.md) implemented:** runner hardened (ids validated, quoted; jobs = systemd transient units with MemoryMax/nice/OOMScoreAdjust; unit-tracked kill; deploy pre-check + bad_remote; once-only notices; user-mode support + deploy/ops_migrate.sh, deploy/harden.sh for earlyoom/softdog/swappiness), tail reads + small row groups (loop/scan/dashboard), trials seeded, empty-research-window guard, FRED url fixed, phone chart layout, honest uptime/balance labels, serve backoff + 120s cache. 81 tests. NOT yet proven on the VM (it had not reported since the 19:42 reset). NEXT: confirm VM runs new runner; run `tests` job to prove jobs survive; then migrate_ops (root->owner) and re-queue history/r0/batch3.
**Current phase:** 2 machinery DONE (no real-data results yet); Phase 1 data BLOCKED on cTrader keys (app status: 'Submitted')
**Last updated:** 2026-11-27

## Reinforcement fixes (2026-11-27)
Merged two critical fixes to `src/fxengine/live/loop.py` and `src/fxengine/learn/reinforce.py`:
1. **Starvation prevention:** Added round-robin guarantee so each strategy publishes at least once every 72h, even if FAVOURED strategies fill the daily 5-setup limit. Prevents REDUCED strategies from being permanently starved.
2. **Early-reacting gate:** Raised minimum live trades to 15 before applying REDUCED or NOT_TAKEN actions, matching scorecard.py MIN_JUDGE. Prevents the reinforcement layer from acting on noisy early data.

Both fixes are reversible (recomputed nightly), preserve all gates/stops/sizing logic, and use the same code path for backtest/replay/live.

## Learning pipeline automation (2026-11-27)
Built comprehensive automation and monitoring for the learning loop:
- **monitor.py:** Tracks progress toward decision thresholds (15/30/40/60 trades per strategy). Alerts on Fridays when each strategy crosses a threshold.
- **learning_job.py:** Standalone ops job runner; can queue `learning` in ops/jobs.txt to run the full pipeline on-demand.
- **EVIDENCE_GATES.md:** Comprehensive gate thresholds and decision timeline (when each action triggers).
- **LEARNING_PIPELINE.md:** Full automation guide, monitoring instructions, and example strategy journey to 30 trades.

Live loop runs learning automatically every night at 21:20 UTC (shadow-replay, reinforce, scorecard, postmortem, monitor). Fridays get threshold alerts on Telegram. All reversible, deterministic code, zero Claude at runtime.

**Next:** Wait 2–4 weeks for 30+ trades per strategy to accumulate. Post-mortem will then identify SUPPORTED entry conditions (Bonferroni 5% corrected). Those that also pass offline history validation can become auto-filters (item D in LEARNING.md). After 60 pooled trades, exit rules can be promoted if SUPPORTED.

## Done
- Phase 0 plan/decisions (CLAUDE.md, docs/PLAN.md).
- Env: new cloud env `fx-engine-v2` allows datafeed.dukascopy.com (approved by Rayyan).
- Built + tested (7 tests pass, `.venv/bin/pytest`): candle close = open+tf
  (`data/timeframes.py`), no-look-ahead resampler (`data/resample.py`),
  stale-data gate (`data/freshness.py`).

## Also built (12 tests pass)
- decode (trendbar→bid OHLC), Parquet store (idempotent merge), quality report, .env reader,
  read-only cTrader fetcher + CLI (`fxengine.data.fetch`) — fetcher UNVERIFIED live.

## Phase 2 built (25 tests pass)
- engine/costs.py (v1 stressed costs), engine/tracker.py (lifecycle state machine, same code for
  backtest/replay/live, executable-side prices, halfway event), research/stats.py (bootstrap, Monte Carlo,
  Bonferroni, gate_b), research/split.py (walk-forward + enforced holdout), research/trials.py,
  docs/GATES.md LOCKED.

## Phase 3 (v1 setups) built, 34 tests pass
- features/indicators.py, setups/v1.py (asia_breakout, trend_pullback, range_reversion; FROZEN params),
  backtest/run.py (shared Tracker, cooldown per pair/type, stressed+normal cost, holdout hidden).
- Data: full 3y M5 for 10 pairs on Rayyan's Mac (data/ gitignored). Cloud OANDA proxy route failed (401), so research runs on Mac:
  `PYTHONPATH=src .venv/bin/python -m fxengine.backtest.run`
- Pause rule + cadence agreed in principle: daily pause check, weekly report, 2-weekly version changes (add to GATES.md).

## Blocker
(Resolved: OANDA practice data downloaded on Mac.) Dukascopy datafeed rate-limits (429/reset) and its official
bulk route is Requester-Pays (costs money). See docs/DATA_SOURCES.md.

## Waiting on Rayyan
- cTrader demo CREATED (GBP, £5,000; engine assumes £2,500). Next: Rayyan registers an Open API app
  (openapi.ctrader.com), grants READ-ONLY (accounts) scope, pastes keys into private `.env` on Mac/VM.
  Open API is TCP port 5035 (not HTTPS) so the cloud sandbox cannot reach it: data pulls run on Mac/VM.
- Google Cloud: Rayyan says signed up (2026-11-15); £1 monthly budget alert CREATED (confirmed by Rayyan). No server created yet (Phase 4).
- `/usage` figure.

## Exact next step (once data exists: fetch -> quality report -> then Phase 3 setups)
0. Remaining Phase 2 piece: backtest runner that loops signals->Tracker over real data + walk-forward report.

1. Retry Dukascopy ONE request later (single, spaced). If it works, write bi5 parser
   + slow downloader (1 worker, 1 req/2s, resumable) and verify against a known candle.
2. Otherwise build `data/ctrader.py` once Rayyan has Open API credentials, or OANDA practice.
3. Then: Parquet store, data-quality report, known-gaps log; finish Phase 1.
