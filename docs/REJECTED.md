# Rejected ideas (with evidence)
- 2026-11-15 asia_breakout / trend_pullback / range_reversion, v1 params, M15: net expectancy negative
  in every year and pair group, even at normal costs (see docs/results/phase3_v1_M15_summary.md).
  Cause: ~zero gross edge and costs ~0.1-0.2R per trade because M15 stops are only ~10-12 pips.
- 2026-11-15 same three setups on H1: still negative (-0.16R stressed, -0.11R normal), every year 2024-2026.
  Cost reduction alone does not create an edge. Do not tune these; next experiments must test a different idea.
- 2026-11-15 E1 (H4 currency-strength momentum) and E2 (H4 Donchian trend, wide stops), pre-registered in
  docs/EXPERIMENTS.md: run_all verdict "NO EDGE FOUND" - both failed the pre-registered pass rule; E3 not due
  (neither was close enough). Per-experiment numbers are in docs/results/experiments_summary.md on the Mac only.
  Trials logged so far: 8. Conclusion: no simple public-data FX setup tested (5 setup/timeframe combos) beats stressed costs.
