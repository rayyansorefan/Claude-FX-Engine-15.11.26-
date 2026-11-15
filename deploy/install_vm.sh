#!/usr/bin/env bash
# One-shot installer for a fresh Debian/Ubuntu VM (e.g. Google Cloud e2-micro). NOT YET TESTED on a real VM.
set -euo pipefail
sudo apt-get update -y && sudo apt-get install -y python3-venv git
[ -d fx ] || git clone --branch engine https://github.com/rayyansorefan/Claude-FX-Engine-15.11.26-.git fx
cd fx && git pull -q
python3 -m venv .venv && .venv/bin/pip install -q pandas numpy pyarrow requests
if [ ! -f .env ]; then
  read -rs -p "Paste OANDA practice token (hidden), Enter: " OT; echo
  read -rs -p "Paste Telegram bot token (hidden), Enter: " TT; echo
  printf 'OANDA_TOKEN=%s\nTELEGRAM_TOKEN=%s\n' "$OT" "$TT" > .env && chmod 600 .env
fi
echo "Open your bot in Telegram, press Start, send 'hi', then press Enter here."; read -r _
PYTHONPATH=src .venv/bin/python -m fxengine.live.telegram_setup
D="$(pwd)"; U="$(whoami)"
sudo tee /etc/systemd/system/fxengine.service >/dev/null <<UNIT
[Unit]
Description=FX research engine (read-only, no orders)
After=network-online.target
[Service]
User=$U
WorkingDirectory=$D
Environment=PYTHONPATH=$D/src
ExecStart=$D/.venv/bin/python -m fxengine.live.loop
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
UNIT
sudo tee /etc/systemd/system/fxwatchdog.service >/dev/null <<UNIT
[Service]
Type=oneshot
WorkingDirectory=$D
Environment=PYTHONPATH=$D/src
ExecStart=$D/.venv/bin/python -m fxengine.live.watchdog
UNIT
sudo tee /etc/systemd/system/fxwatchdog.timer >/dev/null <<UNIT
[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
[Install]
WantedBy=timers.target
UNIT
sudo systemctl daemon-reload && sudo systemctl enable --now fxengine.service fxwatchdog.timer
echo "Installed. Check: sudo systemctl status fxengine"
