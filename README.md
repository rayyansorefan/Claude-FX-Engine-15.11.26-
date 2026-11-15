# FX Engine v2 — research-only FX setup engine (never places orders)

Publishes at most 5 ranked setups a day from frozen, pre-registered rules, monitors them, alerts on state changes
via Telegram, and scores every setup as a hypothetical with executable-side prices and costs. Zero AI at runtime.

Research verdict (2026-11-15): no edge found in 7 simple public-data FX rule sets; everything the live loop publishes is labelled UNPROVEN.
See `docs/GATES.md`, `docs/EXPERIMENTS.md`, `docs/REJECTED.md`, `docs/results/`.

- Run tests: `PYTHONPATH=src .venv/bin/pytest -q`
- Live loop: `PYTHONPATH=src python -m fxengine.live.loop` (needs `.env`: OANDA_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, HC_PING_URL)
- Dashboard: `PYTHONPATH=src python -m fxengine.dashboard.serve` (private; the VM serves it over Tailscale only)
- Research rerun at M5 resolution with challenger: `PYTHONPATH=src python -m fxengine.backtest.run_m5`
- VM: `deploy/install_vm.sh` (fresh machine), `deploy/update_vm.sh` (pull, test, restart)

Secrets live only in `.env` (gitignored). The repository may be public: never commit tokens, IPs or account details.
