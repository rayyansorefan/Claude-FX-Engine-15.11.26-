#!/usr/bin/env bash
# One-shot installer for a fresh Debian/Ubuntu VM (e.g. Google Cloud e2-micro). NOT YET TESTED on a real VM.
set -euo pipefail
sudo apt-get update -y && sudo apt-get install -y python3-venv git curl
# 2 GB swap so the small free VM never runs out of memory
if [ ! -f /swapfile ]; then sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile && echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null; fi
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
# private access: Tailscale (free). Only your own devices can reach the dashboard; nothing is public.
curl -fsSL https://tailscale.com/install.sh | sh
echo "A link will appear. Open it on your Mac, sign in with Google, approve this machine."
sudo tailscale up
TSIP="$(tailscale ip -4 | head -n1)"
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
sudo tee /etc/systemd/system/fxdash.service >/dev/null <<UNIT
[Unit]
Description=FX dashboard (private, Tailscale only)
After=network-online.target tailscaled.service
[Service]
User=$U
WorkingDirectory=$D
Environment=PYTHONPATH=$D/src
ExecStart=$D/.venv/bin/python -m fxengine.dashboard.serve --host $TSIP
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
sudo systemctl daemon-reload && sudo systemctl enable --now fxengine.service fxdash.service fxwatchdog.timer
# one-time research history (3 years of prices + all backtests) so the Research and Performance tabs fill in; runs in the background
nohup bash deploy/research_once.sh > data/research_once.log 2>&1 &
echo "Installed. Dashboard: http://$TSIP:8787  (open it from any device signed in to your Tailscale)."
echo "The Research tab fills in after ~20-30 minutes (see data/research_once.log)."
