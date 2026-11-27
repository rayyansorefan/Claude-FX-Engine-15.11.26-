# Learning Pipeline: Setup & Automation (2026-11-27)

The engine automatically learns from live trades without Claude at runtime. All decisions are reversible (recomputed nightly), nothing changes rules/stops/risk.

## Running Automatically (Live Loop)

The live loop (`fxengine.live.loop`) runs continuously on the VM and calls the learning pipeline daily at **21:20 UTC** (every night). No manual intervention needed; it's in `src/fxengine/live/schedule.py`.

**What happens nightly at 21:20 UTC:**
1. Shadow-replay: every finished trade replayed under exit rules
2. Reinforce: strategy weights updated based on live results
3. Scorecard: strategy status (LEARNING/NEUTRAL/WEAK/CONFIRMED/SUSPENDED)
4. Post-mortem: loss anatomy and entry condition separators
5. Monitor: progress toward decision thresholds

**Fridays at 21:20 UTC (weekly review):**
- Exit promotion decisions (if 60+ pooled trades exist)
- Rollback decisions (if champion underperforms)
- Learning summary Telegram message

## Running Manually (Ops Job)

Queue the `learning` job in `ops/jobs.txt` to run the pipeline outside the daily schedule (useful for testing or on-demand analysis):

```
040 learning
```

This runs all 5 pipeline stages and saves reports to `docs/results/`. Logs go to `data/ops_040.log`. Run via ops runner (deployed VM) every 2 minutes.

## Monitoring Progress: When Does Each Decision Happen?

**Use `monitor.py` output** (printed in Telegram on Fridays):

```
🧪 LEARNING PIPELINE PROGRESS:
  asia_breakout: 12 trades (need 3 more for JUDGMENT)
  trend_pullback: 8 trades (need 7 more for JUDGMENT)
  range_reversion: 32 trades [NEUTRAL] · exit promotion in 28 trades
  E1_strength: 50 trades [NEUTRAL] · exits eligible · rollback eligible at 40+ trades
  
⏳ Post-mortem: 102 pooled trades. Hypotheses visible (Benjamini-Hochberg 10%); SUPPORTED needs 60.
```

**Key thresholds:**
- **15 trades:** Scorecard can judge (LEARNING → WEAK/NEUTRAL)
- **30 trades:** Scorecard makes decisions (CONFIRMED or SUSPENDED)
- **40 trades:** Rollback threshold (live exit monitored)
- **60 trades:** Exit promotion eligible (if SUPPORTED in post-mortem and history validation passed)

## What Each Pipeline Stage Does

### 1. Shadow-Replay (Daily, run_m5 cost model)
- Every finished trade replayed through exit rules A1-C3
- Scores the difference vs frozen exit (R, stored in `shadow`)
- Triggers exit promotion decisions on Fridays

**Output:** `docs/results/exits_*.json` (rule scores)

### 2. Reinforce (Deterministic, Reversible)
- Weight = (history_prior × 40 + live_results) / (40 + live_trades)
- Action: FAVOURED (w ≥ -0.05R) → NORMAL → REDUCED (< -0.20R) → NOT_TAKEN (< -0.30R)
- With < 15 trades: suppress REDUCED/NOT_TAKEN (noise gate)
- Announced nightly if action changes

**Output:** Telegram message on action changes

### 3. Scorecard (Per strategy, from finished trades)
- LEARNING: < 15 trades (no judgment)
- WEAK: 15+ trades, shrunk mean < -0.25R (warning, still taken)
- NEUTRAL/CONFIRMED: 15–30+ trades (label only)
- SUSPENDED: 30+ trades, 95% CI entirely < 0 (not taken, still published/scored)

**Output:** `docs/results/scorecard.json`, Telegram note (Fridays)

### 4. Post-Mortem (Loss anatomy + separators)
- Loss anatomy: wrong_from_start / faded / timeout / other
- Separators: each entry condition tested on pass vs fail trades
- HYPOTHESIS: 8+ each side, Benjamini-Hochberg 10% (shown; nothing happens)
- SUPPORTED: 30+ each side, Bonferroni 5% (candidate for filter, if history validation also passed)

**Output:** `docs/results/postmortem.md`, Telegram 3-line note (Fridays)

### 5. Monitor (Progress tracker)
- When each strategy hits 15 / 30 / 40 / 60 trades
- When pools hit thresholds for SUPPORTED conditions
- Timeline estimate (trades to next decision)

**Output:** Telegram Fridays, stored in monitoring state

## Exit Promotion (Fridays at 21:20 UTC)

**Gate:** 60 finished pooled trades + SUPPORTED separator in post-mortem + passed offline history validation + no change in last 14 days

If all pass:
- Candidate exit rule is selected
- Frozen exit updated to new rule
- Announced in Telegram: "EXIT PROMOTED"
- All new setups use the new exit; old ones keep their original exit

**Rollback (automatic, reversible):**
- If champion (live exit)'s own 40+ forward trades have 95% CI upper bound < 0: automatically rolled back
- Reverts to previous exit
- Announced in Telegram: "EXIT ROLLED BACK"

## Entry Filter Application (Optional, needs pre-registration)

**Gate:** SUPPORTED separator in post-mortem + passed offline entry-filter validation + per-strategy throughput < 50% removed in 7 days + no change in last 14 days

If all pass:
- Filter is switched on in `ops/filters.json`
- Applied to new setups of that strategy
- Announced in Telegram: "FILTER APPLIED"
- Logged in `learning_log` and `docs/results/filters_applied.md`

**Veto:** `ops/filters_veto.json` or Rayyan telling the engineer; vetoed filters never re-applied.

**Auto-removal:** If filter's own forward trades show its pass group doing WORSE or throughput guard trips.

## Alert Thresholds (Telegram)

**Nightly at 21:20 UTC:**
- Reinforce: strategy action changed (NORMAL → REDUCED, etc.)

**Friday 21:20 UTC:**
- Scorecard: `CONFIRMED` and `SUSPENDED` strategies
- Monitor: progress toward 30 / 60 / 40 trades per strategy
- Exit decision: PROMOTED / ROLLED BACK (if gates pass)
- Filter decision: APPLIED / REMOVED (if gates pass)
- Post-mortem: best separator (SUPPORTED or HYPOTHESIS)

**Other:**
- Learning errors: "⚠️ LEARNING · review failed" if any stage crashes

## Logs and State

**Live database:** `data/engine.db`
- `setups`: every published setup (immutable)
- `outcomes`: every finished trade (run_id, reason, net_r)
- `learning_log`: every decision + reason

**Docs:**
- `docs/results/postmortem.md`: loss anatomy + separators (re-written daily)
- `docs/results/exits_*.json`: shadow-replay scores
- `docs/results/filters_applied.md`: when filters were applied
- `docs/trials.jsonl`: research trial registry (append-only)

**Telegram:**
- 3–5 messages nightly at 21:20 (learning stage summaries)
- Weekly summary on Fridays (decisions, monitor progress, scorecard)

## Example: One Strategy's Journey to 30 Trades

**Days 1–7:** 15 trades accumulated
- Scorecard judges it → WEAK (shrunk mean < -0.25R)
- Reinforcement may apply REDUCED (w < -0.20R)
- Telegram nightly: "🧭 LEARNING · asia_breakout NORMAL → REDUCED (weight −0.22R, live: 3 wins in 15)"
- Monitor shows: "14 trades to 30-trade decision"

**Day 10:** 30 trades total
- Scorecard re-judges → decision made (CONFIRMED if lo > 0, SUSPENDED if hi < 0, else NEUTRAL)
- Telegram Friday: "SCORECARD · 1 confirmed ✅ · 0 suspended ⛔"
- If SUSPENDED: new setups still published/scored but not taken (lots = 0)
- If CONFIRMED: label shown; first-call-on-cash logic (later, if cash is tight)

**Days 11–60:** More trades
- Reinforce continues updating weight nightly
- Post-mortem collects 30+ finished trades per strategy
- Separators now reportable (move from HYPOTHESIS to SUPPORTED at 30 each side, p ≤ 0.05/m)
- If a separator is SUPPORTED and history validation passed: becomes filter candidate

**Day 60:** 60 pooled trades
- Exit promotion gate opens: shadow replay 60 trades, test candidate exits
- If champion (live exit) underperforms, rollback triggered
- If candidate passes all gates → new exit promoted
- Telegram: "🚀 EXIT PROMOTED: B2 (trailing, 3-bar) chosen"

## Restart After VM Reboot

The live loop auto-restarts on VM reboot (systemd service `fxengine`). Database and all state are persisted in `data/engine.db` and `data/engine.db-shm` (WAL). The learning pipeline continues from the last state; no history is lost.

**Check VM health:** `data/ops_heartbeat.txt` (updated every 10 min by ops runner)

## Offline: Testing Learning Locally

Run the learning job on your machine against a local copy of the database:

```bash
cd ~/fx && PYTHONPATH=src python -m fxengine.ops.learning_job
```

Outputs reports to `docs/results/` just like the VM does.
