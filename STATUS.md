# STATUS

**Current phase:** 1 (Data) — partly done, BLOCKED on a history source
**Last updated:** 2026-11-15

## Done
- Phase 0 plan/decisions (CLAUDE.md, docs/PLAN.md).
- Env: new cloud env `fx-engine-v2` allows datafeed.dukascopy.com (approved by Rayyan).
- Built + tested (7 tests pass, `.venv/bin/pytest`): candle close = open+tf
  (`data/timeframes.py`), no-look-ahead resampler (`data/resample.py`),
  stale-data gate (`data/freshness.py`).

## Blocker
No M1 bid/ask history yet. Dukascopy datafeed rate-limits (429/reset) and its official
bulk route is Requester-Pays (costs money). See docs/DATA_SOURCES.md.

## Waiting on Rayyan
- cTrader demo CREATED (GBP, £5,000; engine assumes £2,500). Next: Rayyan registers an Open API app
  (openapi.ctrader.com), grants READ-ONLY (accounts) scope, pastes keys into private `.env` on Mac/VM.
  Open API is TCP port 5035 (not HTTPS) so the cloud sandbox cannot reach it: data pulls run on Mac/VM.
- Google Cloud card yes/no (needed before Phase 4).
- `/usage` figure.

## Exact next step
1. Retry Dukascopy ONE request later (single, spaced). If it works, write bi5 parser
   + slow downloader (1 worker, 1 req/2s, resumable) and verify against a known candle.
2. Otherwise build `data/ctrader.py` once Rayyan has Open API credentials, or OANDA practice.
3. Then: Parquet store, data-quality report, known-gaps log; finish Phase 1.
