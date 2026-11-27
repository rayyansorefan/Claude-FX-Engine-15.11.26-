# Finding Profitability: Strategy Ideas (2026-11-27)

## Why Current Strategies Fail (Evidence from Research)

**Cost destroys the edge.** M15 stops = 10–12 pips = 0.1–0.2R cost per trade. All 5 live strategies have net negative expectancy even at normal costs (not stressed). No amount of data collection will fix this.

**Solution:** We need strategies where:
1. The gross edge (before costs) is **meaningfully positive** (> 0.3R minimum)
2. Stops are **wider** (allow costs to be a smaller fraction of edge)
3. OR trade **higher timeframes** where stops widen but fewer setups exist
4. OR exploit **specific regimes** where edge is concentrated (avoid choppy markets entirely)

## Pre-Registered Ideas to Test (Offline First)

### Idea A: Volatility-Regime Filter (Highest Priority)

**Hypothesis:** The edge varies by market regime. Choppy/sideways markets = all strategies lose. Trending markets = breakout works.

**Test:** Add regime gate before publishing any setup.
- If ATR(20, H1) < 20th percentile (choppy): don't publish any setup that day
- If ATR(20, H1) > 80th percentile (explosive): publish breakout only (not reversion)
- If ATR(20, H1) in middle: publish all

**Expected effect:** Reduce losers (avoid choppy days); concentrate winners (trade only explosive days).

**How to test:** Rerun M5 backtest on each of the 5 live strategies, filtered by regime. See if average R improves.

**Gate:** Chopping Index or Keltner Channel width on H1. Code: `learn/filters.py ATOMS` already has vol_not_low; add regime test.

---

### Idea B: Session-Time Filter (Medium Priority)

**Hypothesis:** Some pairs trade better at certain hours (London open = volatility spike for EURUSD/GBPUSD, Asian pairs during Tokyo hours, etc.).

**Test:** Only publish setups during the pair's optimal session.
- EURUSD/GBPUSD: 08:00–11:00 UTC (London open ramp)
- USDJPY: 21:00–00:00 UTC (New York open) OR 00:00–09:00 UTC (Tokyo)
- Carry pairs (AUDUSD, NZDUSD): 20:00–04:00 UTC (Sydney/Asian overlap)

**Expected effect:** Higher win rate + wider average winning move (setups hit target faster when volatility is there).

**How to test:** Rerun M5 backtest filtered by session hours. See if Sharpe improves.

**Gate:** `fxengine.calendar` already has market hours; add per-pair optimal session table.

---

### Idea C: Higher Timeframe Alignment (Medium Priority)

**Hypothesis:** Entries that align with the H4 or Daily trend underperform because they go against the prevailing structure. Entries that align win more.

**Test:** Only enter breakouts when the H4 is also in a breakout pattern (channel breakout on H4 = same direction breakout on M5).

**Expected effect:** Fewer but higher-win-rate setups. Total edge: depends on volume trade-off.

**How to test:** Rerun M5 backtest with H4 alignment gate. Count setups, wins, average R.

**Gate:** HTF check already in range_reversion via `learn/filters.py` (htf_with). Extend to other strategies.

---

### Idea D: News Blackout (Lower Priority, Needs External Data)

**Hypothesis:** Entries 1 hour before / 2 hours after major economic events (Fed, BOE, ECB) are noise. Skip them.

**Test:** Add economic calendar check. Skip setups during scheduled news windows.

**Expected effect:** Reduce whipsaws; higher Sharpe.

**Problem:** Needs free calendar data (docs/DATA_SOURCES.md lists candidates). Currently unsourced.

---

## Immediate Action Plan

### Phase 1: Test Idea A (Volatility Regime) — Offline, This Week
1. Grab current M5 backtest data (from `data/engine.db` on VM or local copy).
2. Add regime ATR gate to `learn/filters.py`.
3. Rerun `fxengine.backtest.run_m5` with regime filter enabled (ops/jobs.txt: `r0_regime`).
4. Compare average R, Sharpe, win rate vs unfiltered R0.
5. If ATR gate improves edge: pre-register in GATES.md, deploy to live.

**Output:** Rerun report (docs/results/r0_regime_summary.md). Decision: deploy or drop.

### Phase 2: Test Idea B (Session Hours) — Offline, Parallel to Phase 1
1. Add session gate to `learn/filters.py` (per-pair optimal hours table).
2. Rerun backtest with session filter.
3. Compare.

---

## Why This Matters

**Without fixing the idea, the post-mortem will only confirm:** "All 5 strategies lose. SUPPORTED entry conditions don't exist."

**With a profitable strategy:**
1. Post-mortem finds SUPPORTED entry separators that actually improve edge.
2. Exit promotion finds better exits on profitable setups (not on losers).
3. Live reinforcement layer rewards the profitable strategy (weight moves up, FAVOURED status).
4. After 4 weeks, we've made money, not just confirmed we lose slower than other ways.

---

## Files to Create / Update

- `src/fxengine/learn/filters.py`: Add `regime_filter` and `session_filter` ATOMS
- `ops/jobs.txt`: Queue `r0_regime` and `r0_session` jobs (new rerun variants)
- `docs/results/r0_regime_summary.md`: Output from regime test
- `GATES.md`: Lock in regime/session gates once they pass backtest
- `docs/EXPERIMENTS.md`: Pre-register A/B/C as E8/E9/E10

---

## Success Metric

**A strategy is worth deploying live if:**
- Backtest average R > +0.1R stressed (beats costs)
- Drawdown < 1R per 10 setups (manageable risk)
- Win rate > 45% (better than coin flip)
- Sharpe > 0.5 (consistent)

**Current 5 strategies:** All fail on average R (net negative). No amount of live data collection fixes that.

**We need to test new ideas NOW, not wait 4 weeks.**
