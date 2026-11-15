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
