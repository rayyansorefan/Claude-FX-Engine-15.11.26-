# Self-learning loop (pre-registered 2026-11-17, requested by Rayyan: positive reinforcement and self-learning are fundamental)
Deterministic code only (zero Claude at runtime). Parameters stay frozen per version; the engine adapts ONLY through this scheduled, evidence-gated loop.

1. **Record** every trade with its path (best / worst point) and a plain-English review (History tab).
2. **Shadow-replay** (daily 21:20 GMT): every finished, filled live trade is replayed under the frozen exit and under 9 candidate exit rules (A1-A3 break-even, B1-B3 trailing,
   C1-C3 keep-a-share), same prices, same tracker. Stored in `shadow`.
3. **Reinforce**: a scoreboard of paired gains/losses (rule minus frozen, R) on NEW trades only, with clustered confidence ranges.
4. **Promote** (Friday review, announced on Telegram) a rule for NEW setups only if ALL hold: >= 60 finished live trades; lower bound of its clustered CI > 0 at alpha 0.05/9;
   the offline walk-forward exit test (docs/results/exits.json) chose the SAME rule and passed on unseen history under both cost models; no promotion/rollback in the last 14 days.
   The setup keeps the exit rule it was published with (stored in its immutable record). Only stop-TIGHTENING rules are eligible, so no trade can lose more than its original stop.
5. **Roll back** automatically (announced) if the champion's own forward trades (>= 40) have a CI upper bound < 0 versus the frozen exit.
6. Entries, filters, targets and sizing are NOT auto-changed: they need a pre-registered offline test and Rayyan's go-ahead.
7. Every decision is logged (`learning_log`, docs/results/learning.md). Alerts: PROMOTED / ROLLED BACK / PROFIT PROTECTED (first stop move per trade).

## No bottlenecks (lesson from the old engine: stacked vetoes meant it stopped trading)
- Entry filters: at most 2 conditions per rule, each chosen filter must keep >= 40% of historical trades, and none is applied without passing validation AND a deliberate, announced switch (ops/filters.json).
- Throughput guard (weekly review): if filters remove more than 50% of candidates over 7 days (>= 6 candidates seen), they are switched off automatically and Rayyan is told.
- Setup frequency is measured, not assumed: the dashboard/Telegram weekly note reports published vs filtered counts.
