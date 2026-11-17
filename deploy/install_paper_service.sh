#!/usr/bin/env bash
# ONE-TIME, on the VM: make the paper-trading dashboard start at boot and restart itself if it stops (systemd service `bookiepaper`).
# Light by design: memory capped at 250 MB, first to be stopped if the VM runs short, never touches the FX services.
#   cd ~/bets && git pull -q --ff-only origin betting-wip && bash deploy/install_paper_service.sh
set -euo pipefail
cd "$(dirname "$0")/.."
D="$(pwd)"; U="$(id -un)"
[ -x .venv/bin/python ] || { echo "run deploy/install_bets.sh first (no .venv here)"; exit 1; }
sudo tee /etc/systemd/system/bookiepaper.service >/dev/null <<UNIT
[Unit]
Description=Bookie paper-trading dashboard (paper bets only, Tailscale-only)
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
User=$U
WorkingDirectory=$D
ExecStart=/bin/bash $D/deploy/run_paper.sh
Restart=on-failure
RestartSec=20
MemoryMax=250M
OOMScoreAdjust=1000
Nice=10

[Install]
WantedBy=multi-user.target
UNIT
pkill -f paper_serve 2>/dev/null || true; sleep 2           # stop any hand-started copy so the service owns the port
sudo systemctl daemon-reload
sudo systemctl enable --now bookiepaper
sleep 8
echo "service: $(systemctl is-active bookiepaper)   enabled at boot: $(systemctl is-enabled bookiepaper)"
ss -tlnp 2>/dev/null | grep 8789 | cut -c1-80 || echo "port 8789 not listening yet (check: journalctl -u bookiepaper -n 20)"
echo "fx services: $(systemctl is-active fxengine fxdash | tr '\n' ' ')   memory: $(free -m | awk '/Mem:/{print $7}') MB available"
