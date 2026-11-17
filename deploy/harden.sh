#!/usr/bin/env bash
# Run as ROOT (ops job `harden`). Makes the 1 GB VM fail small instead of freezing:
#  1) earlyoom: kills the biggest memory hog when RAM is low (acts while swap is still being used, not after hours of thrashing)
#  2) the live services are protected from the OOM killer; research jobs are made the preferred victims (done per job in the runner)
#  3) low swappiness so the working set stays in RAM
#  4) kernel software watchdog: if PID 1 hangs, the VM reboots itself (free, no cloud API)
set -euo pipefail
apt-get install -y earlyoom
# 2 GB swap file (free: uses spare disk). Jobs are capped per unit; this only absorbs short peaks so earlyoom does not fire.
if ! swapon --show=NAME --noheadings | grep -q fxswap; then
  [ -f /fxswap ] || { fallocate -l 2G /fxswap && chmod 600 /fxswap && mkswap /fxswap; }
  swapon /fxswap
  grep -q '^/fxswap' /etc/fstab || echo '/fxswap none swap sw 0 0' >> /etc/fstab
fi
cat > /etc/default/earlyoom <<'EOF'
EARLYOOM_ARGS="-m 5 -s 8 -r 0"
EOF
systemctl enable --now earlyoom
systemctl restart earlyoom
echo "vm.swappiness=10" > /etc/sysctl.d/99-fx.conf
sysctl -p /etc/sysctl.d/99-fx.conf
for u in fxengine fxdash; do
  mkdir -p "/etc/systemd/system/$u.service.d"
  printf '[Service]\nOOMScoreAdjust=-500\n' > "/etc/systemd/system/$u.service.d/oom.conf"
done
echo softdog > /etc/modules-load.d/softdog.conf
modprobe softdog || true
mkdir -p /etc/systemd/system.conf.d
printf '[Manager]\nRuntimeWatchdogSec=60s\nRebootWatchdogSec=5min\n' > /etc/systemd/system.conf.d/watchdog.conf
systemctl daemon-reload
systemctl daemon-reexec
systemctl restart fxengine fxdash
systemctl is-active earlyoom fxengine fxdash
echo "hardened"
