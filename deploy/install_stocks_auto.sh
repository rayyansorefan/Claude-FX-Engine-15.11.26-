#!/usr/bin/env bash
# ONE-TIME on the VM: makes the Stocks side look after itself.
#  - stocksauto.timer (every 10 min): pulls the newest stocks-wip and restarts the Stocks dashboard (fast-forward only; waits for running jobs; never touches FX).
#  - stockshealth.timer (every 15 min): checks the 5-minute job, the nightly scan, the dashboards, the FX loop heartbeat, memory and disk; Telegram message once a day per problem.
#   cd ~/stocks && git pull -q --ff-only origin stocks-wip && bash deploy/install_stocks_auto.sh
set -euo pipefail
cd "$(dirname "$0")/.."
D="$(pwd)"; U="$(id -un)"
[ -x .venv/bin/python ] || { echo "run deploy/install_stocks.sh first"; exit 1; }
git config core.fileMode false                       # the timer runs the script with bash: no chmod needed, and a mode change must never block a pull
sudo tee /etc/systemd/system/stocksauto.service >/dev/null <<UNIT
[Unit]
Description=Stocks: pull the newest code and restart the Stocks dashboard

[Service]
Type=oneshot
ExecStart=/bin/bash $D/deploy/stocks_autoupdate.sh
Nice=15
TimeoutStartSec=120
UNIT
sudo tee /etc/systemd/system/stocksauto.timer >/dev/null <<UNIT
[Unit]
Description=Stocks self-update every 10 minutes

[Timer]
OnBootSec=3min
OnUnitActiveSec=10min

[Install]
WantedBy=timers.target
UNIT
sudo tee /etc/systemd/system/stockshealth.service >/dev/null <<UNIT
[Unit]
Description=Self-check of both engines (read-only, Telegram on problems)

[Service]
Type=oneshot
User=$U
WorkingDirectory=$D
Environment=PYTHONPATH=$D/src
ExecStart=$D/.venv/bin/python -m fxengine.stocks.health
MemoryMax=80M
OOMScoreAdjust=1000
Nice=15
TimeoutStartSec=60
UNIT
sudo tee /etc/systemd/system/stockshealth.timer >/dev/null <<UNIT
[Unit]
Description=Self-check every 15 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min

[Install]
WantedBy=timers.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now stocksauto.timer stockshealth.timer
sudo systemctl start stockshealth.service || true
echo "auto-update: $(systemctl is-active stocksauto.timer)   self-check: $(systemctl is-active stockshealth.timer)"
cat docs/results/stocks_health.json 2>/dev/null || true; echo
