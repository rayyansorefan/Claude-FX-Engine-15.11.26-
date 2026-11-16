# Day-1 audit — Monday 16 Nov 2026 (first live session)
Written for Rayyan. Blunt on purpose. Numbers marked (PENDING) are filled in from the VM report once it arrives.

## Scoreboard
| Area | Result | Verdict |
|---|---|---|
| Research | 7 strategy variants (M15/H1/H4) all negative after stressed costs; holdout sealed and untouched; R0 (M5 rerun) and E6/E7 NOT yet valid | No edge found so far; the stronger tests have not run on real data yet |
| Live engine reliability | At 14:25 UTC: 236 cycles, 134 OK (57%). Then the VM froze 14:36 -> ~19:45 (about 5 h blind) | FAIL against Gate A (99%). Real number, reported honestly |
| Alerts | 14 sent, 0 unsent, 0 late at 14:25. Telegram path works | Pass so far |
| Setups | 5 published, 0 resolved at 14:25 (all labelled UNPROVEN) | Too early to score |
| Dashboard | Rebuilt 3 times today; now one card per trade, readable charts, instant load | Acceptable now; far too many iterations |
| Cost | GBP 0 spent | Pass |

## What went wrong (root causes, not excuses)
1. **OANDA token invalidated twice (13:50-14:20 and again ~14:35).** One token only; any generate/revoke elsewhere kills the VM's. The engine kept erroring; the alert after 3 errors did not tell Rayyan what to do. Fix: retry on transient 401; alert text must say exactly what to click. Still open: find the cause of the second 401.
2. **3-year price history never ran on the VM.** The installer's background run failed silently (log directory did not exist) and nobody checked. R0 therefore saw ~90 days, all inside the hidden holdout window, and printed "no data". Fix: the installer now creates the directory; jobs report success/failure by Telegram; health report job exists.
3. **The job queue kept going after a failure.** A failed download was followed by a re-test on half-downloaded data (hours of wasted CPU, misleading output). Fix: a failed job now pauses the queue; I can kill a job remotely.
4. **A heavy research job starved a 1 GB VM -> the whole server froze for ~5 hours.** The live engine, dashboard and update runner all died with it. This is my design mistake: no memory budget. Fix: heavy jobs run at lowest priority and an earlyoom watchdog kills the biggest process before the machine freezes (installs on next boot).
5. **The dashboard rebuilt from scratch on every visit** (the VM service had no cache). Slow and fragile. Fix: serve the last finished page instantly and rebuild in the background.
6. **No off-host dead-man alert.** Rayyan declined it. Today's 5-hour silence is exactly what it catches; the decision stands, but it should be on the record that it would have turned a 5-hour blind spot into a 10-minute one.

## What went wrong on my side (process)
- I presented the first dashboards as finished without checking them against the original brief (uptime, next cycle, live P&L, readable charts were missing or unusable). Three redesigns followed.
- I said things "deploy automatically / fix themselves" without stating the condition (only while the server is alive).
- I asked for pastes and screenshots I could have avoided by building the remote runner first.
- Fix: UI acceptance checklist (docs/UI_ACCEPTANCE.md) must pass before anything is shown; every "done" claim must cite a test or a VM report.

## What worked
- Honest research machinery: no-look-ahead tests, shared tracker for backtest/live, locked gates, trial registry, sealed holdout. It stopped a losing strategy being shipped.
- Self-updating VM (git push deploys, auto-rollback) and the results-back channel (branch vm-results): the first time the loop closed without copy-paste.
- Telegram alerts: short, 3 lines, delivered.

## Tomorrow (autonomous unless stated)
1. 06:30 UTC: read the VM report; confirm cycles OK, no 401, memory guard active (job 012).
2. Finish the 3-year history download (resumes per pair), then R0 (M5 rerun), then E6/E7. Run heavy jobs at low priority; watch memory.
3. Read results; give Rayyan the plain verdict: does "no edge" survive measured costs and the random-entry baseline? Does E6/E7 beat its challenger?
4. Investigate the second 401 (ask Rayyan once whether the token was regenerated).
5. Reliability numbers go in the weekly report: cycle success, longest outage, alert latency.
6. Not before tomorrow: GCP free-trial decision (day ~80), repository privacy, dead-man alert (Rayyan's call).
