#!/usr/bin/env bash
# ONE-TIME on the VM: run the nightly stocks job automatically on weekday evenings (22:45 UTC, after the US close) via a systemd timer.
# Light: memory capped at 350 MB, first to be stopped if the VM runs short, never touches the FX services.
#   cd ~/stocks && git pull -q --ff-only origin stocks-wip && bash deploy/install_stocks_timer.sh
set -euo pipefail
cd "$(dirname "$0")/.."
D="$(pwd)"; U="$(id -un)"
[ -x .venv/bin/python ] || { echo "run deploy/install_stocks.sh first"; exit 1; }
sudo tee /etc/systemd/system/stocksnightly.service >/dev/null <<UNIT
[Unit]
Description=Stocks nightly scan + forward test (research only)

[Service]
Type=oneshot
User=$U
WorkingDirectory=$D
ExecStart=/bin/bash $D/deploy/stocks_nightly.sh
MemoryMax=350M
OOMScoreAdjust=1000
Nice=15
TimeoutStartSec=3600
UNIT
sudo tee /etc/systemd/system/stocksnightly.timer >/dev/null <<UNIT
[Unit]
Description=Stocks nightly job, weekdays after the US close

[Timer]
OnCalendar=Mon..Fri 22:45:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now stocksnightly.timer
echo "timer: $(systemctl is-active stocksnightly.timer)   enabled: $(systemctl is-enabled stocksnightly.timer)"
systemctl list-timers stocksnightly.timer --no-pager | head -3 | cut -c1-110
