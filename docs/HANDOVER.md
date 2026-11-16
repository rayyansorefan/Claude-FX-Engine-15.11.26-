# Handover (written 2026-11-15) — read CLAUDE.md and STATUS.md first
Owner: Rayyan (non-developer, frustrated by step-by-step asks: act autonomously, verify your own work, show screenshots for UI,
give copy-paste blocks, never paste secrets, never tell him to run things on his Mac that the VM can do).

## Where things run
- VM `fx-engine` (GCP us-central1-c, e2-micro). SSH via Google console button. Repo at ~/fx (branch engine). `.env` holds OANDA_TOKEN,
  TELEGRAM_TOKEN, TELEGRAM_CHAT_ID (chmod 600). Update: `cd ~/fx && git pull && sudo systemctl restart fxengine fxdash`.
- Cloud sandbox (Claude session) cannot reach OANDA (proxy 401 even after request_credential). Develop+test here with synthetic data;
  real runs happen on the VM. The VM is the source of truth for data/ and data/engine.db.
- Mac has an old copy at ~/fx (not needed).

## Known open items (priority order)
0. Astra review 2026-11-15 implemented in code (see STATUS.md top line). Left for Rayyan: run `bash deploy/update_vm.sh` on the VM, then R0 (`PYTHONPATH=src nohup .venv/bin/python -m fxengine.backtest.run_m5 > data/r0.log 2>&1 &`), add HC_PING_URL to .env, decide on repo privacy, copy docs/trials.jsonl + docs/results/* from the VM into git.
1. Fable review still pending. Prompts: docs/AUDIT_PROMPT.md, docs/ASTRA_PROMPT.md.
2. Confirm research_once.sh finished on the VM (data/research_once.log says "research done"); dashboard Research/Performance tabs depend on it.
3. Cost-validity worry: ADDRESSED by R0's 'measured' cost mode (real OANDA ask-bid, no commission), logged as one trial. Read the R0 table on the Research tab.
4. Live loop has never seen a market session: watch the first Monday (alerts, ledger, audit). Fix anything that breaks.
5. Untested ideas: market structure/key levels, news blackout (needs free calendar), E3 filters.
6. GCP free trial ends ~day 90 (~mid Feb 2027): remind Rayyan ~day 80 about the upgrade decision (billed account risk vs moving host).
7. Halfway HOLD/EXIT rule is unproven; keep it labelled so.
8. Repo is public: never commit secrets, results are visible. Consider moving research outputs off the public repo.

## Rules to keep
Pre-register before running; one change at a time; log every trial (docs/trials.jsonl); never loosen gates silently (tell Rayyan);
never open the holdout casually; zero LLM at runtime; no order placement ever.

## Owner decisions (2026-11-16)
- Healthchecks.io dead-man alert: DECLINED by Rayyan. Do not nag. Known gap: no off-host alert if the VM dies; Gate A (reliability) cannot be fully met without it. Report that honestly in weekly reports.
- Git history rewrite for the early cTrader-details note: DECLINED. Leave history as is; do not ask again. Never write personal remarks into the repo.
