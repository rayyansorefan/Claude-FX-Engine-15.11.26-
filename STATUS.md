# STATUS

**Current phase:** 0 complete → next is Phase 1 (Data)
**Last updated:** 2026-11-15

## Done
- Phase 0: requirements agreed, decisions recorded in CLAUDE.md, plan in docs/PLAN.md.

## Waiting on Rayyan
- Yes/No to Google Cloud card verification (needed before Phase 4 only).
- `/usage` figure at start of each session.

## Exact next step
Phase 1: create `src/fxengine/data/` — Dukascopy bid/ask M1 downloader → Parquet,
resample to M5/M15/H1 with close = open + timeframe, look-ahead unit tests,
freshness checks, `docs/DATA_SOURCES.md` with known gaps. No credentials needed.
