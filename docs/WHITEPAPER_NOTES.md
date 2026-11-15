# Notes on "OANDA FX Research Engine — Technical and performance audit" (white paper, 15 Nov 2026)
That paper audits the OLD engine (not reused here). Its verdict: research infrastructure exists; reliable end-to-end
operation and a profitable edge are UNPROVEN; zero independently scored pair-days; £0 dependable income; "preserve as
a research platform; reconsider when there is an executable positive forward record and measured reliability".
Its four acceptance tests for any future work, and where v2 stands:
1. Measure operation (>=10 weekday sessions, expected vs actual slots, provider errors separated) -> Gate A; NOT built yet.
2. Verify handoff (common ID source->trigger->alert->served page; receipt after expiry = late) -> run_id design + Gate A; NOT built yet.
3. One change at a time, comparable cohorts, preserve missed entries/no-fills -> done in research (trial registry, frozen params).
4. Prove net economics (sample floors, stressed net expectancy, uncertainty by day, vs cash/challenger, independent review)
   -> bootstrap+penalty done; GATES.md tightened 2026-11-15 to independent pair-days (see change log).
Open issues the paper raises that v2 shares: OANDA-to-Pepperstone pricing gap (costs only modelled); public repo exposes
results/execution records (access-governance); provider 401/instability risk; GitHub scheduling unreliable (we avoid it).
Lessons already applied: candle open != close (tests), no stacked vetoes (setup frequency measured), zero LLM in the loop.
