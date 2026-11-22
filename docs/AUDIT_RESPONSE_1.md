# Response to the first audit: for Haiku to RE-AUDIT before anything is implemented

Status: NOTHING in this report has been deployed. The one drafted code change is shown as a diff at the end and is held back on a local branch until you (the auditor) and the owner have reviewed it. The report generator is not yet corrected either (see F2, F3).

Your job now: challenge my verdicts. Where I reject a finding, try to prove me wrong with evidence. Where I agree, tell me whether the proposed fix is sufficient or whether it creates a new risk. Same rules as before: read-only, no secrets, every claim needs file:line evidence, separate VERIFIED / NOT VERIFIED / SUSPECTED.

Code under audit: branch `stocks-wip` @ `b00ecd3` (Stocks + report generator + self-update) and branch `engine` @ `7a822f5` (FX). Repo is public: https://github.com/rayyansorefan/Claude-FX-Engine-15.11.26-

## Verdict table

| # | Your finding | My verdict | One-line reason |
|---|---|---|---|
| F1 | FX: duplicate NEW/TRIGGERED alerts (6) | CONFIRMED as a risk; root cause UNVERIFIED; metric misread | The dedupe works only on event number, which can shift after a data gap |
| F2 | Stocks: account cash is negative (-GBP 102) | REJECTED (evidence below) | You compared the COST of positions with the BALANCE; cash = balance minus market VALUE |
| F3 | FX: OANDA down, data feed broken | PARTLY: 5 failed cycles in 7 days is real; "broken" is not shown | Needs the failure timeline; cycles continued; but alerting threshold deserves review |
| F4 | "Account fully leveraged" (GBP 2,500 in positions) | REJECTED | Fully invested is not leveraged; leverage would mean cash below zero |
| F5 | 60 Stocks setups skipped for cash | EXPECTED by design, but a real limitation | Cash-limited account (4 positions of GBP 625); owner decision pending |
| F6 | "Could not verify" items | Partly answerable now | 56 tests is stale (now 220); the holdout log lives on the VM |

## F1: FX duplicate alerts

What the report line means: `fxengine/stocks/auditbundle.py` (fx_section) counts GROUPS `(run_id, kind)` that have more than one alert row for kind in (NEW, TRIGGERED). "6" therefore means six (setup, kind) pairs were duplicated, NOT one setup with six duplicates. The report prints only the count, not the rows, so the cause cannot be seen. That is a defect in my report.

Mechanism I found (src/fxengine/live/loop.py, `track()` and `_alert()`):
- `alerts` has PRIMARY KEY (run_id, idx) (live/db.py:9-10). Uniqueness is per EVENT NUMBER, not per alert kind.
- `track()` skips events whose number is below the count of events already stored (`have`), and replays the setup from M5 bars every cycle (`replay`, loop.py ~line 56-80).
- If bars arrive late or are re-downloaded (for example after a data gap or an OANDA error), the replay can yield a different event list. New events get numbers >= `have`, so a TRIGGERED event can be sent again under a new number.
- I cannot prove this is what happened: the ledger is on the VM. It is the hypothesis that fits.

Proposed fix (drafted, NOT applied): one alert per (setup, kind), enforced in `_alert()`; later attempts are recorded as `SUPPRESSED-<kind>` so the cause can be investigated. Diff at the end. Test: tests/test_account_no_leverage.py::test_one_alert_of_each_kind_per_setup_even_if_a_replay_shifts_the_event_numbers (passes in the draft).

Questions for you (re-audit):
1. Is there any legitimate case where the same kind should be sent twice for one setup (for example HALFWAY after a re-entry, PROTECTED, a second TRIGGERED after a cancel and refill)? If yes, the rule is too strict.
2. Does `retry_unsent()` (loop.py, after `track`) interact badly with the guard (it re-sends rows with ok=0)?
3. Are there other paths that can send an owner message without going through `_alert()` (stale/recovered, engine_error, halfway)? Those have their own dedupe; check them.
4. Suggest the minimal extra logging that would let the owner prove the root cause.

## F2: "Stocks account has negative cash"

Your reasoning: positions cost GBP 2,500, balance GBP 2,398 -> cash -GBP 102. This mixes two quantities. Balance = cash + current market VALUE of positions (account.py `simulate`, curve). After prices fall the balance is below the cost basis, but cash is untouched. Cash cannot go negative because every entry is sized by `shares = min(RISK/dist, 25% of equity / price, cash / price)` (src/fxengine/stocks/sizing.py:21) and `cash -= cost` happens only after that (account.py:110); exits add proceeds (account.py:90).

Evidence: tests/test_stocks.py::test_paper_account_cash_never_goes_negative_even_when_prices_fall_and_positions_cost_the_whole_account (added with this report; a test only, no behaviour change): 8 setups, each wanting the GBP 625 cap, all positions then lose about 6%: cost = GBP 2,500, balance below 2,500, value below cost, cash >= 0. The existing test test_paper_account_never_spends_cash_it_does_not_have_and_takes_the_strongest_first shows 4 x GBP 625 are taken and 4 skipped.

My own fault: the report line `money in positions GBP X of the account (must never exceed it)` (auditbundle.py:75) compares COST with the account. After a loss that reads like a violation. Proposed fix: print cost, current value, and cash = balance - value, and flag only cash < 0.

Questions for you: (a) Can you find any path by which cash goes negative: currency conversion moving between entry and exit day, an exit price below the converted entry, rounding, or a position entered twice through two rules? (b) Is the 25% cap computed on equity at the OPEN of entry day consistently with what is later displayed? (c) Is a fully invested account with a cash buffer of zero a risk worth reporting as a design issue (it is: any new setup is skipped until a position closes)?

## F3: OANDA 401 errors

What the report shows: 5 failed live-loop cycles in 7 days (latest 20 Nov 21:00), with an HTTP 401 note. That is real and must be understood. What it does NOT show: that the feed is "broken". The loop kept cycling (status counts in the report), and the engine alerts only after 3 consecutive failed cycles (live/loop.py:234, `n == 3 or n % ERR_ALERT_EVERY == 0`), so an isolated 401 is silent by design.

Unknowns I need your help with: were the 5 failures consecutive or scattered? Did cycles succeed afterwards? Did the data gap lead to the replay changes in F1 (a link between F3 and F1)? Is 401 (unauthorised) rather than 429/5xx a sign of a token problem (rotation, expiry) and not a transient fault? A token is the owner's to regenerate; nothing in the repo can fix it.

Proposed fix (not applied): the report prints failures per day, the longest consecutive failure streak and the time since the last success; an owner alert when 401s recur (not only after 3 in a row).

## F4 and F5

F4 is rejected as stated (fully invested is not leverage; leverage is cash below zero, see F2). F5 is true and by design: the account is GBP 2,500 and a position is capped at GBP 625 (25%), so at most four stocks fit; setups beyond that are skipped for cash (account.py `skipped`) but still tracked and scored (history.jsonl). The owner has not yet decided whether to change the account size or the cap. Please assess: does skipping distort the forward test? (My view: the research is unaffected because every signal is still tracked and closed with the same backtest code; only the money account is affected.)

## F6: could-not-verify items you listed

- 56 tests: stale; the suite is now 220 on `stocks-wip` and 130 on `engine`. Run them.
- Holdout log (docs/stocks_holdout_log.txt) lives on the VM; the opening is also recorded in docs/STOCKS_PLAN.md. If the holdout was opened more than once, that file would show it.
- Duplicate-alert root cause needs the SQLite ledger on the VM (not in git).

## Things I found myself (disclosing for your re-audit)

1. VM self-update was blocked by a chmod on the update script (git saw a local change). Fixed and pushed (deploy/stocks_autoupdate.sh, install_stocks_auto.sh, with a regression test using real git repos). Please check the fix for other ways a local change could block the fast-forward.
2. Memory: the nightly job is limited to 350 MB. My measurement on synthetic data (all symbols with 6,500 days) was about 490 MB (download) and 750 MB (scan) at 435 symbols, and about 720 MB and 1.3 GB at 763 symbols. The extra 328 US companies were switched off for that reason (universe.py, STOCKS_EXTENDED). The 435-symbol size has run on the VM, but I have not checked it against the 350 MB cap with real data. Please look at the nightly log in the report.
3. FX no-leverage replay (live/account.py `replay`) values past positions with the CURRENT exchange rates, not the rates of that day, and assumes the stored GBP-20-risk lots were exactly GBP 20 (they are floored to 0.01, so actual risk is slightly lower). Both are approximations; judge whether they matter.
4. `dashboard/build.py set_acct` falls back to the plain GBP-20-risk view if fewer than 4 price files are available (to avoid showing zeros). In that case the page is silently NOT capped. Is that acceptable or should it say so on the page?
5. Stocks live job: on 19 Nov it bought at yesterday's open in markets not yet open and in excluded countries. Fixed (live.py `plan_live` today-check and allowed lists) and tested on made-up quotes only; Telegram messages for those wrong buys were already sent and cannot be recalled.
6. The auto-update runs as root, pulls two branches and restarts services. Anyone who can push to those branches controls the VM. Review the trust model (the repo is public; push rights belong to the owner only).
7. Report-generator tests only use synthetic data; the real ledgers have not been checked against them.

## Specific re-audit tasks (in this order)

1. Re-read src/fxengine/live/loop.py (`track`, `_alert`, `retry_unsent`, `publish`) and live/db.py; judge F1's mechanism and the draft below. Try to produce a duplicate with a short script using a temp SQLite file (do not touch real data).
2. Re-verify F2 by running the new test and by writing your own adversarial scenario for negative cash in stocks/account.py (different currencies, exits, same-day entries and exits).
3. Run both test suites; report counts and any failure.
4. Review deploy/stocks_autoupdate.sh and stocks/health.py for new failure modes.
5. Re-check your "verified safe" list against the current code (for example "no double-buys; stale sessions blocked" refers to code that changed on 19 Nov and 22 Nov).
6. Produce the same output structure as before, plus a new section "Disagreements with the response" listing where you still think I am wrong and why.

## Appendix: drafted change (NOT APPLIED), for F1

```diff
--- a/src/fxengine/live/loop.py
+++ b/src/fxengine/live/loop.py
@@ def _alert(conn, env, send, c, idx, kind, text, event_ts, now, expires=None):
+    if conn.execute("SELECT 1 FROM alerts WHERE run_id=? AND kind=? AND idx<>?", (c["run_id"], kind, idx)).fetchone():
+        # Hard rule: ONE alert of each kind per setup. (dedupe was by event number only)
+        conn.execute("INSERT OR REPLACE INTO alerts VALUES(?,?,?,?,?,?,?,?,?)", (c["run_id"], idx, "SUPPRESSED-" + kind, str(event_ts), str(pd.Timestamp(now)), 0.0, 0, 1, "(duplicate suppressed)"))
+        conn.commit()
+        return True
     ok = send(env, text)
```
Held on a local branch (`fx-no-leverage`, not pushed). The corrected report generator (print the duplicate rows, cash from value, failure timeline) is also not yet written.
