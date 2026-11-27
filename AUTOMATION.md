# FX Engine Automation & Monitoring (2026-11-27)

The engine runs fully autonomously on the VM. No Claude at runtime; all analysis/decisions/alerts = deterministic code.

## Live Loop (Continuous, Always Running)

**Where:** `src/fxengine/live/loop.py` runs on the VM (systemd service `fxengine`)

**What it does hourly (06:00–20:00 UTC, Monday–Friday):**
- Scan OANDA for entry signals on 10 FX pairs (M5 candles)
- Rank by rule score + strategy weight (autonomous reinforce layer)
- Publish ≤5 setups per day, one per pair, respecting round-robin starvation prevention
- Monitor active positions; alert on halfway (−0.5R) and outcome (exit rule applied)

**What happens daily at 21:20 UTC:**
- Shadow-replay all finished trades under exit rules (learning)
- Update strategy weights (reinforce)
- Judge strategy status (scorecard: LEARNING / WEAK / CONFIRMED / SUSPENDED)
- Analyze losses and entry separators (post-mortem)
- Track progress toward decision thresholds (monitor)
- Generate Telegram alerts and dashboard updates

**Friday 21:20 UTC (weekly):**
- Exit promotion: if 60+ trades + SUPPORTED separator + history validation passed → promote new exit
- Rollback: if live exit underperforms on 40+ own trades → rollback to previous
- Threshold alerts: which strategies crossed 15 / 30 / 40 / 60 trade milestones
- Learning summary: scoreboard, reinforcement state, post-mortem findings

## Operational Database

**Live ledger:** `data/engine.db` (SQLite WAL mode, atomic trades)
- `setups`: immutable setup record (run_id, pair, type, entry, target, stop, taken?)
- `outcomes`: finished trades (run_id, reason, net_r, path data: mfe_r, mae_r)
- `learning_log`: every decision + reason

**Files pushed to `vm-results` branch hourly by ops runner:**
- `docs/results/*.md` and `docs/results/*.json`: research outputs, postmortem, learning decisions
- `docs/trials.jsonl`: research trial registry (append-only)
- `data/ops_*.log`: job logs

## Automation Triggers

| When | What | Code | Output |
|---|---|---|---|
| **Every 2 min** | Ops runner polls and deploys code | `src/fxengine/ops/runner.py` on systemd timer | Telegram: deploy status, job start/finish |
| **Nightly 21:20** | Learning pipeline | `src/fxengine/live/schedule.py` → `learn/*.py` | Telegram: strategy changes, scorecard, post-mortem, monitor |
| **Friday 21:20** | Weekly decisions | `learn/review.py:decide()` | Telegram: exit promotion, rollback, threshold alerts |
| **On error** | Auto-alert | Loop exception handlers | Telegram: ⚠️ LEARNING FAILED; frozen exit stays |
| **On VM restart** | Auto-recover | systemd service restart policies | Database persists; learns from last state |

## Queuing Manual Jobs (via ops/jobs.txt)

Operations runner polls every 2 minutes and executes queued jobs one at a time. Push to `engine` branch to trigger deployment + job execution.

**Whitelisted jobs:**
```
history            # Download 3-year OANDA history
r0                 # Rerun M5 research (baseline cost model)
batch3             # Run experimental entries (E6, E7)
exits              # Run exit validation study
entries            # Run entry validation study
diagnose           # Run live loss diagnosis
report             # Compile research report + push results
learning           # Run full learning pipeline (new)
tests              # Run test suite
```

**Example:** Queue the learning job on-demand
```bash
# Edit ops/jobs.txt on your branch:
040 learning

git push origin engine  # Ops runner picks up in 2 min, job runs, results pushed to vm-results
```

**Check status:**
- `data/ops_heartbeat.txt` (updated every 10 min; shows running job and memory)
- `data/ops_040.log` (output of job 040)

## Monitoring Progress

**On the VM (live):**
```bash
# SSH to the VM
tail -f data/ops_heartbeat.txt          # Proof of life + current job
tail -f data/engine.log                 # Live loop logs (also in systemd journal)
sqlite3 data/engine.db "SELECT type, COUNT(*) FROM outcomes WHERE reason IN ('TARGET','STOP','TIMEOUT') GROUP BY type"  # Trade counts
```

**Telegram (automatic):**
- **Nightly 21:20 UTC:** Reinforce changes, scorecard status, post-mortem top finding, monitor progress
- **Friday 21:20 UTC:** Exit promotion/rollback decisions, threshold alerts, learning summary
- **On error:** ⚠️ alerts if any stage fails (loop continues)

**Dashboard (manual refresh):**
- http://your-tailscale-ip:8787 (port 8787)
- Tabs: Overview, Research, Charts, Positions, Performance, Journal, System
- Shows learning progress card: strategy counts (LEARNING / WEAK / NEUTRAL / CONFIRMED / SUSPENDED)

## Decision Gates (Pre-registered, Frozen)

All decision points are deterministic, reversible, logged, and announced. See `docs/EVIDENCE_GATES.md` for full thresholds.

| Threshold | What Happens | Reversible? |
|---|---|---|
| **15 trades** | Scorecard can judge (LEARNING → WEAK/NEUTRAL) | Yes (fewer trades = back to LEARNING) |
| **30 trades** | Scorecard decides (CONFIRMED or SUSPENDED) | Yes (95% CI recomputed nightly) |
| **30+ each side** | Post-mortem separators move to SUPPORTED | Yes (new data can change verdict) |
| **40 trades** | Rollback eligibility starts (live exit monitored) | Yes (auto-rollback if underperforms) |
| **60+ trades** | Exit promotion gate opens | Yes (needs Bonferroni + history + no-change-14d) |

## Alerts: What Each Message Means

**Nightly at 21:20 UTC:**
- `🧭 LEARNING · asia_breakout NORMAL → REDUCED`: Strategy weight dropped below threshold; size halved
- `📊 SCORECARD · X trades across Y strategies`: Finished trades summary
- `🧪 LEARNING PIPELINE PROGRESS`: How many trades to next threshold per strategy
- `🔎 POST-MORTEM · X losses, Y wins`: Loss anatomy and best separator

**Friday 21:20 UTC (weekly):**
- `✅ EXIT PROMOTED: B2 (trailing, 3-bar) chosen`: New exit rule deployed
- `🔄 EXIT ROLLED BACK: returning to A1`: Live exit underperformed; reverted
- `🎯 asia_breakout hit 30 trades: SUSPENDED ⛔`: Strategy crossed decision threshold
- `⚠️ LEARNING · review failed (KeyError)`: A learning stage crashed (loop continues with frozen exit)

**On deploy:**
- `🟢 OPS · deployed abcd123 (engine and dashboard restarted)`: New code live
- `🔴 OPS · new code does not import`: Code change failed precheck; stayed on old version
- `🛠 JOB started · exits (id 035)`: Job queued from ops/jobs.txt started
- `✅ JOB done · exits · 4.2 min`: Job finished successfully
- `❌ JOB FAILED, queue paused · exits · 2.1 min`: Job failed; push `resume <token>` to ops/control.txt to continue

## If Something Goes Wrong

**Live loop crashes:**
- Systemd auto-restarts (3 retries within 1 min)
- If permanently broken: check `systemctl status fxengine` on the VM
- Database is safe; trades are persisted

**A learning stage fails (scorecard, reinforce, post-mortem):**
- Learning job continues; stage is skipped; alert sent
- Frozen exit stays in force; next nightly run tries again
- Manual check: `tail data/engine.log | grep -i learning`

**A job fails in ops runner:**
- Queue pauses (no more jobs run until resumed)
- Push `resume <token>` to ops/control.txt with a NEW token each time
- Check log: `tail data/ops_NNN.log`
- Previous data not lost; can re-run after fixing

**VM runs out of disk:**
- Logs and results compress automatically
- Check: `df -h` (reported in ops_heartbeat.txt)
- Clear old `data/*.log` files if needed

## Zero Claude at Runtime

Every decision in the loop is deterministic and reproducible:
- Entry rules frozen (no auto-change; pre-registered only)
- Exit promotion gates documented (60 trades + SUPPORTED + history validation + no-change-14d)
- Reinforce layer: formula is `(prior×40 + live_results)/(40 + live_trades)`
- Scorecard: 95% confidence intervals, Bonferroni correction
- Post-mortem: SUPPORTED = Bonferroni 5%, HYPOTHESIS = Benjamini-Hochberg 10%

All changes are:
- Announced on Telegram with reason
- Logged in `learning_log` table
- Reversible (nightly recompute from scratch)
- Never touch risk cap (£20), leverage (zero), rules, stops, or targets

## Next: Reaching Decision Points

**When 30 trades per strategy accumulate (2–4 weeks):**
- Scorecard makes decisions: CONFIRMED ✅ or SUSPENDED ⛔
- Post-mortem can report SUPPORTED entry separators
- Monitor alerts announce threshold crossings

**When 60 pooled trades exist:**
- Exit promotion gate opens (if shadows show candidate rule better than frozen)
- Offline history validation must also pass
- Announcement: "EXIT PROMOTED" (new exit deployed) or "no promotion" (gates not met)

**After 2–4 weeks of 30+ trades:**
- Extract loss patterns from post-mortem (SUPPORTED separators)
- Design new strategy idea from patterns
- Pre-register in GATES.md, test on history
- If valid: add to entry rules and deploy

## Exact Next Step (for Rayyan)

1. **Confirm VM is healthy:** Check `data/ops_heartbeat.txt` on the VM (updated every 10 min)
2. **Wait for data:** Live loop runs 06:00–20:00 UTC, publishes ≤5 setups/day
3. **Monitor progress:** Telegram Fridays will announce threshold crossings (15 / 30 / 40 / 60 trades)
4. **At 30 trades per strategy:** Scorecard decides; post-mortem identifies separators
5. **At 60 pooled trades:** Exit promotion gate opens; Telegram announces decision

No manual intervention needed. All automatic. If anything breaks, Telegram will alert.
