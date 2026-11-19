# FX Engine v2 — instructions for Claude

Owner: Rayyan (UK, product owner, not a developer). Explain in plain English, short.
Do it yourself where possible; otherwise give click-by-click steps.

## What this is
Research-only FX engine. Publishes ≤5 ranked setups/day, monitors them, alerts on
state changes via Telegram, scores every setup as a hypothetical. NEVER places,
modifies or closes orders. NEVER holds trading credentials (read-only data only).
No code reused from the old ChatGPT engine.

## Hard rules
- £0 budget. Free tools only. Flag anything needing a card BEFORE using it.
- Zero Claude usage at runtime. All analysis/alerts/dashboard/audit = deterministic code.
- Never suggest buying Claude credits. On usage limit: stop at a clean checkpoint,
  write exact next step in STATUS.md.
- One phase per session. Keep this file < 100 lines. Write big outputs to files.
- Never commit secrets (tokens, keys, account IDs). Repo may be public. Use `.env` (gitignored).
- Candle close time = open time + timeframe. Never use a candle before its close.
- Stale data fails loudly (oldest pair > 12 min). Dashboard always shows data age. Market hours in New York time (`fxengine.calendar`).
- Live loop = one supervised long-running process. GitHub Actions only as backup.
- Every setup: immutable record, one run_id from creation → alerts → outcome.
- Same code path for backtest, replay and live: `engine.tracker.track_arrays` on M5 bars (research rerun R0 and live loop).
- Parameters frozen per version. One change at a time. Adapt only at scheduled
  offline walk-forward reviews.
- Never loosen a gate without telling Rayyan. Report negative results plainly.

## Key decisions (Phase 0, 2026-11-15)
- Account (2026-11-19, Rayyan): NO leverage/margin; only the £2,500 is used. Lots held = min(£20-risk lots, lots the FREE cash can fully pay for) (live/account.py); £20 is a cap, not a target; unaffordable setups are still published and scored, just not 'taken'. Earlier: treat as £2,500 (real demo is £5,000 GBP on Pepperstone cTrader UK DEMO; login kept out of git). Risk per trade = £20 (1R). Lot size computed from stop distance.
- Halfway check: at −0.5R send one HOLD/EXIT message from a pre-set rule. Must beat
  plain holding in backtest, else labelled "unproven".
- Universe: EURUSD GBPUSD USDJPY USDCHF AUDUSD USDCAD NZDUSD EURGBP EURJPY GBPJPY.
- Runtime (LIVE since 2026-11-15): Google Cloud e2-micro free tier, us-central1, Debian 13, systemd services
  `fxengine` (live loop), `fxdash` (dashboard), `fxwatchdog.timer`. Private access via Tailscale only
  (dashboard on port 8787 at the VM's Tailscale IP; never write that IP into the repo). Installer: deploy/install_vm.sh. GCP free trial ends ~90 days: Rayyan must
  decide on upgrading (billed account) around day 80; flag it. Never open public ports.
- Alerts: Telegram bot, max 3 lines per message.
- Dashboard: dashboard/build.py renders one self-contained HTML (inline SVG, 7 tabs); dashboard/serve.py rebuilds it
  on every refresh. Served privately (Tailscale). No GitHub Pages, no public URL. Never show invented numbers.
- Data: OANDA practice REST (read-only), bid/ask M5, 10 pairs. Dukascopy blocked (429); cTrader needs KYC (dropped).
  OANDA token + Telegram token live only in .env (never commit). Credentials via the secure form or `read -s`.

## Status of research (2026-11-15)
- 7 strategy variants ALL failed (docs/REJECTED.md). Holdout (>=2026-05-15) never opened. Live setups are labelled UNPROVEN.
- Next work is in docs/HANDOVER.md. Run tests: `PYTHONPATH=src .venv/bin/pytest -q` (56 pass). Update the VM: `bash deploy/update_vm.sh`.

## Layout
- `src/fxengine/` package: data/, features/, setups/, engine/, backtest/, live/,
  alerts/, dashboard/, audit/
- `tests/` pytest. `data/` (gitignored) SQLite + Parquet. `docs/` plans, gates, logs.
- `docs/PLAN.md` phase plan · `docs/GATES.md` pre-registered gates (lock in Phase 2)
- `docs/REJECTED.md` rejected indicators · `docs/DATA_SOURCES.md` sources + known gaps

## Workflow
- Work on branch `engine`; commit often with tests passing.
- Learning loop (docs/LEARNING.md): shadow-replay exits, scheduled evidence-gated promotion, auto-rollback; entries/sizing never auto-change.
- Update STATUS.md at the end of every session and at every checkpoint.
- Python 3.11+, pandas, numpy, pyarrow, requests, sqlite3, pytest. Keep deps minimal.
