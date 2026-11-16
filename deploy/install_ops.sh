#!/usr/bin/env bash
# ONE-TIME on the VM: lets the repo owner's `git push` deploy code and run whitelisted jobs, and pushes results to branch vm-results.
# Run:  cd ~/fx && git pull && bash deploy/install_ops.sh
set -euo pipefail
cd "$(dirname "$0")/.."
D="$(pwd)"; U="$(whoami)"
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
if [ ! -f "$HOME/.ssh/fx_deploy" ]; then ssh-keygen -q -t ed25519 -N "" -C "fx-vm-deploy" -f "$HOME/.ssh/fx_deploy"; fi
echo
echo "=== STEP FOR YOU (2 minutes) ==="
echo "1) Open https://github.com/rayyansorefan/Claude-FX-Engine-15.11.26-/settings/keys"
echo "2) Click 'Add deploy key'. Title: fx-vm. Paste the key below. TICK 'Allow write access'. Click 'Add key'."
echo
cat "$HOME/.ssh/fx_deploy.pub"
echo
read -r -p "Press Enter once the key is added on GitHub... " _
git config --global --add safe.directory "$D" || true
sudo tee /etc/systemd/system/fxops.service >/dev/null <<UNIT
[Unit]
Description=FX ops runner (self-update + whitelisted jobs)
[Service]
Type=oneshot
Environment=OPS_USER=$U
Environment=OPS_DIR=$D
Environment=PYTHONPATH=$D/src
WorkingDirectory=$D
ExecStart=$D/.venv/bin/python -m fxengine.ops.runner
UNIT
sudo tee /etc/systemd/system/fxops.timer >/dev/null <<UNIT
[Timer]
OnBootSec=2min
OnUnitActiveSec=2min
[Install]
WantedBy=timers.target
UNIT
sudo systemctl daemon-reload && sudo systemctl enable --now fxops.timer
echo "Ops runner installed. From now on the engine updates itself from GitHub and runs queued jobs. Nothing else to paste."
