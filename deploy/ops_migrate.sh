#!/usr/bin/env bash
# Run as ROOT once (ops job `migrate_ops`). Moves the ops runner from root to the owner so a push to `engine` can no longer
# become root: the runner keeps only four narrowly-scoped sudo rules (restart/inspect the two services, install earlyoom).
set -euo pipefail
U="${OPS_USER:?OPS_USER not set}"
D="${OPS_DIR:?OPS_DIR not set}"
loginctl enable-linger "$U"                                   # the owner's systemd manager runs without a login (jobs run there)
cat > /etc/sudoers.d/fxengine <<EOF
$U ALL=(root) NOPASSWD: /usr/bin/systemctl restart fxengine fxdash, /usr/bin/systemctl is-active fxengine fxdash, /usr/bin/systemctl show -p NRestarts --value fxengine, /usr/bin/systemctl reboot
EOF
chmod 440 /etc/sudoers.d/fxengine
visudo -cf /etc/sudoers.d/fxengine
cat > /etc/systemd/system/fxops.service <<EOF
[Unit]
Description=FX ops runner (self-update + whitelisted jobs), runs as $U
[Service]
Type=oneshot
User=$U
Environment=OPS_USER=$U
Environment=OPS_DIR=$D
Environment=PYTHONPATH=$D/src
WorkingDirectory=$D
ExecStart=$D/.venv/bin/python -m fxengine.ops.runner
EOF
chown -R "$U:$U" "$D/data" 2>/dev/null || true
systemctl daemon-reload
systemctl restart fxops.timer
echo "ops runner now runs as $U"
