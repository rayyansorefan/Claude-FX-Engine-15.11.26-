# Data sources and known gaps

## Dukascopy (research history) — BLOCKED / UNRESOLVED (2026-11-15)
- Legacy `datafeed.dukascopy.com/...bi5` reachable from cloud session but returns
  HTTP 429 "Too Many Requests" and then connection resets (also the agent proxy
  dropped the tunnel). Message points to their data-export wiki.
- Their current official route is an S3 bucket on **Requester Pays** (AWS bills the
  downloader). That is NOT £0-safe: do not use without Rayyan's explicit OK.
- Terms of use for bulk automated download not verified. Do not hammer the server.
- Quote type: Dukascopy is its own ECN feed, not Pepperstone pricing.

## Pepperstone demo via cTrader Open API (preferred for price match) — NOT STARTED
- Needs a free Pepperstone demo + cTrader ID + Open API app (client id/secret, read-only
  scope). Provides trendbar history and live spots matching Pepperstone pricing.
- Must run from Rayyan's Mac/VM (OAuth in browser); credentials go in `.env`, never git.

## Other free fallbacks to check (not yet verified)
- OANDA practice API (candles with bid/ask; needs free practice account + token).
- Yahoo/Stooq daily/hourly (no bid/ask; research-grade only, weak for M5/M15).

## Known gaps (to complete once real data lands)
- Weekend gaps, holiday thin sessions, Dukascopy hourly gaps, DST shifts of server time.

## cTrader findings (2026-11-15)
- Trendbars are BID-only. Ask/spread must be modelled: record live bid/ask spreads from
  the demo feed going forward and use a conservative stressed spread for history.
- Open API = TCP/TLS port 5035 (demo.ctraderapi.com): unreachable from the cloud sandbox.
  Fetch runs on Mac/VM: `python -m fxengine.data.fetch --years 3`. Resumable.
- `data/ctrader.py` is UNVERIFIED against the live server until keys exist.
- Read-only by design; a test fails if any order/trading message name appears in src/.

## Update 2026-11-15
- cTrader Open API abandoned for now (identity verification required). Dukascopy M1 bid+ask via `fxengine.data.dukascopy_cli` from the user's Mac: real ask/bid, so spread is measured not assumed. `dukascopy.py` format UNVERIFIED until first Mac run.
- Dukascopy has no live feed (history only up to ~yesterday): live source for Phase 4 still to choose (free options to verify).

## Update 2026-11-15 (later)
- cTrader and Dukascopy code REMOVED (never verified, unused). OANDA practice is the only source. Spread is measured from the data (ask-bid) in the R0 cost mode.
