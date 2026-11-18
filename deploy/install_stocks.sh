#!/usr/bin/env bash
# ONE-TIME on the VM, ONE paste: clones the stocks branch into its own folder (~/stocks, never touching ~/fx), installs it, sets up a private dashboard service
# (Tailscale only, port 8790, 150 MB cap, first to be stopped if memory runs short) and starts the first full run in the background.
#   git -C ~/bets fetch -q origin stocks-wip && git -C ~/bets show origin/stocks-wip:deploy/install_stocks.sh | bash
set -euo pipefail
D="$HOME/stocks"; U="$(id -un)"
[ -d "$D/.git" ] || git clone -q --branch stocks-wip "$(git -C "$HOME/bets" remote get-url origin)" "$D"
cd "$D"; git pull -q --ff-only origin stocks-wip
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --no-cache-dir pandas numpy pyarrow requests
mkdir -p data docs/results
sudo tee /etc/systemd/system/stocksdash.service >/dev/null <<UNIT
[Unit]
Description=Stocks research dashboard (read-only, Tailscale-only)
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
User=$U
WorkingDirectory=$D
Environment=PYTHONPATH=src
ExecStart=/bin/bash -c 'exec .venv/bin/python -m fxengine.stocks.serve --host "\$(tailscale ip -4 | head -1)" --port 8790'
Restart=on-failure
RestartSec=20
MemoryMax=150M
OOMScoreAdjust=1000
Nice=10

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload && sudo systemctl enable --now stocksdash
setsid nohup bash deploy/stocks_all.sh > data/stocks_all.log 2>&1 < /dev/null &
sleep 3
echo "installed. dashboard service: $(systemctl is-active stocksdash). The first run starts by itself (about 5-10 minutes; it waits if the VM is busy)."
echo "open http://$(tailscale ip -4 | head -1):8790 in a while, or later run:  cat ~/stocks/data/stocks_report.txt"
