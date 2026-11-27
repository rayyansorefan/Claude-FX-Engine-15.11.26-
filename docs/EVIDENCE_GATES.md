# Evidence Gates: When Decisions Happen (pre-registered 2026-11-27)

All decisions are deterministic and reversible, recomputed nightly from scratch. Nothing changes rules, gates, stops, or risk. All strategies lose in research: FAVOURED = least bad, not proven profitable.

## Decision Timeline

| Trades per Strategy | Decision Point | What Happens | Code |
|---|---|---|---|
| **0–14** | LEARNING (no judgment) | Strategies accumulate data, no action | `scorecard.py` line 34 |
| **15+** | WEAK warning | If shrunk mean < −0.25R, label shown (still taken) | `scorecard.py` line 40–41 |
| **15–29** | Still collecting | Reinforcement applies REDUCED/NOT_TAKEN if weight < −0.20R or < −0.30R | `reinforce.py` lines 45–51 |
| **30** | Threshold for decision | Scorecard decides: CONFIRMED (lo > 0), SUSPENDED (hi < 0), or NEUTRAL/WEAK | `scorecard.py` line 36–39 |
| **30+** | CONFIRMED → Dashboard ✅ | Strategy labeled as winning; counted in weekly note | `scorecard.py` line 36 |
| **30+** | SUSPENDED → Probation ⛔ | New setups published and scored but NOT taken (lots = 0); recomputed nightly, reversible | `scorecard.py` line 38 |
| **60+** | Exit promotion eligible | Shadow-replay 60 pooled finished trades; promote candidate exit if CI lower bound > 0 AND offline history passed AND no change in last 14d | `review.py` line 60–70 (gates.md gate C) |
| **40+** | Rollback eligible | Champion (live exit) automatically rolled back if its own 40+ forward trades have CI upper < 0 vs frozen | `review.py` line 40–50 |

## Reinforce Layer (Autonomous, Every Night)

**Weight formula:** `(prior_mean × 40 + sum_of_live_results) / (40 + live_trades)`

| Weight Range | Action | Effect | Threshold |
|---|---|---|---|
| **w ≥ −0.05R** | FAVOURED | First call on daily slots (5) and free cash | `reinforce.py` line 37 |
| **−0.05 > w ≥ −0.20** | NORMAL | Ordered by weight after FAVOURED | `reinforce.py` line 37 |
| **−0.20 > w ≥ −0.30** | REDUCED | Taken at 50% size; announced | `reinforce.py` line 37 |
| **w < −0.30** | NOT TAKEN | Published and scored, not taken in account | `reinforce.py` line 37 |
| **Any w, < 15 live trades** | NORMAL (forced) | Suppress REDUCED/NOT_TAKEN until 15 trades (noise gate) | `reinforce.py` line 51 |

**Reversible:** recomputed nightly; a strategy that recovers is promoted back automatically.

## Starvation Prevention (New 2026-11-27)

**Problem:** If FAVOURED strategies fill all 5 daily slots, REDUCED/NORMAL strategies get zero trades, can't recover.

**Solution:** Round-robin guarantee in `loop.py` lines 131–144. After sorting by weight:
- If daily limit (5) is hit BUT a strategy hasn't published in 72+ hours, that strategy gets one slot.
- Ensures each strategy publishes at least once every 3 days (recovers via weight updates).

## Post-Mortem: When Do Patterns Become Supported?

| Trades per Strategy | Status | What's Ready |
|---|---|---|
| **1–29** | HYPOTHESIS (Benjamini-Hochberg 10% FDR) | Patterns visible, not yet reliable; displayed for learning |
| **30+** | Transition point | Post-mortem can now report SUPPORTED findings |
| **30+** | SUPPORTED (Bonferroni 5% FWE) | A condition separated winners from losers with p ≤ 0.05/m; can be a filter candidate if it also passed offline history study |

**Multiple-testing correction:** m = all comparisons in the report (12 per group, groups = pooled + per-strategy). SUPPORTED = Bonferroni-corrected p-value; HYPOTHESIS = Benjamini-Hochberg FDR 10%.

## Example: The 30-Trade Transition

**Scenario:** asia_breakout has 30 finished live trades.

1. **Scorecard.py** judges it → status is CONFIRMED (lo > 0), SUSPENDED (hi < 0), or NEUTRAL/WEAK
   - If SUSPENDED: new setups are still published/scored but lots_account = 0 (not taken).
   - Reversible: if range later includes 0, it's taken again.

2. **Post-Mortem.py** can now run SUPPORTED tests (30 trades minimum per condition/side).
   - Entry conditions (e.g., htf_with YES vs NO) are tested on these 30 trades.
   - If p ≤ 0.05/m: "SUPPORTED" (Bonferroni).
   - That condition is a candidate for auto-filter IF it also passed the offline entry-filter validation.

3. **Reinforce.py** continues updating weight nightly as new trades arrive.
   - If new trades are strong, weight improves, action upgrades (REDUCED → NORMAL → FAVOURED).

## Throughput Guard (No Starvation of Entry Quality)

**Check:** Daily. If filters removed > 50% of candidates over 7 days (≥ 6 candidates seen), switch them off automatically.

**Why:** Prevents the old engine's "stacked vetoes → no trades" failure.

**Code:** `learn/filters.py` and triggered in `schedule.py`.

## Gates Locked in CLAUDE.md / GATES.md

All thresholds below are frozen per version and can only change via pre-registration + offline test + Rayyan's approval:

- MIN_JUDGE = 15 trades (scorecard judgment threshold)
- MIN_DECIDE = 30 trades (scorecard decision threshold)
- 60 trades (exit promotion eligibility)
- 40 trades (rollback eligibility)
- 95% confidence interval for CONFIRMED/SUSPENDED (mean +/− 1.96 SD)
- Bonferroni correction (p ≤ 0.05/m) for SUPPORTED conditions
- 72-hour round-robin guarantee per strategy
- £20 risk cap per trade (never raised)
- REDUCED = 50% size (never 0, keeps broker minimum 0.01 lot)

## Never Changes (Research and Forward Test Untouched)

- Entry filters: may be switched on/off via ops/filters.json (announced), never auto-added to rules
- Exits: may be promoted via evidence gate (announced), never auto-added
- Targets, stops, risk: frozen; never auto-changed
- Rules themselves: entries/setups are pre-registered, never modified at runtime
