# FX Engine v2 — plan

| # | Phase | Deliverable | Done when |
|---|---|---|---|
| 1 | Data | Dukascopy history → Parquet; candle timing correct; freshness gates; source gap log | tests pass, data-quality report |
| 2 | Backtest + replay | One event-driven core for backtest/replay/live; costs (spread, swap, stressed slippage); walk-forward, untouched holdout, Monte Carlo, multiple-testing penalty; lock GATES.md | replay == backtest, look-ahead tests pass |
| 3 | Setups + indicators | 3–4 setup types; indicator families added one at a time on out-of-sample value; halfway HOLD/EXIT rule tested; filter marginal effects + setup frequency | honest results report |
| 4 | Live loop + alerts | Cloud VM, supervised process, watchdog, heartbeat + dead-man alert, Telegram brief/updates/EOD, alert latency | 2 clean weekdays |
| 5 | Dashboard | Health light, setup cards with mini charts, strength heatmap, session timeline, funnel, R curve, by-type results, reliability | readable on phone + Mac |
| 6 | Audit + forward test | Twice-daily audit (5 lines), weekly report, 10-session Gate A run, Gate B scoring | gate numbers reported |

## Draft gates (final version locked in docs/GATES.md during Phase 2, before any forward test)
- **A Reliability:** ≥99% scheduled cycles complete over 10 weekday sessions; in-session data
  never >5 min old; 100% complete lifecycle records; all alerts before expiry; 0 look-ahead failures.
- **B Economics:** ≥100 scored setups, positive net expectancy after stressed costs,
  95% bootstrap interval reported (pass requires lower bound > 0).
- **C:** if B passes, report plainly. Real-money decision is Rayyan's alone.
