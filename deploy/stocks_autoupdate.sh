#!/usr/bin/env bash
# Runs on the VM every 10 minutes (systemd timer, as root). Keeps ~/stocks on the newest `stocks-wip` WITHOUT anyone pasting commands:
# fast-forward only (never overwrites local work), never while a stocks job is running, restarts only the Stocks dashboard, never touches the FX services.
set -uo pipefail
cd "$(dirname "$0")/.."
U="$(stat -c %U .)"
run() { runuser -u "$U" -- "$@"; }
mkdir -p data
log() { echo "[$(date -u '+%F %H:%M:%S')] $*" >> data/stocks_autoupdate.log; }
exec 8>data/stocks_update.lock
flock -n 8 || exit 0
run git fetch -q origin stocks-wip 2>/dev/null || { log "fetch failed"; exit 0; }
[ "$(run git rev-parse HEAD)" = "$(run git rev-parse FETCH_HEAD)" ] && exit 0
if pgrep -f "fxengine.stocks.(scan|data|events|filingtext|run)|stocks_nightly|stocks_all" >/dev/null; then log "stocks job running: update waits"; exit 0; fi
old="$(run git rev-parse --short HEAD)"
if run git merge -q --ff-only FETCH_HEAD 2>/dev/null; then
  log "updated $old -> $(run git rev-parse --short HEAD)"
  systemctl restart stocksdash && log "stocksdash restarted"
else
  log "cannot fast-forward (local changes?): left as it was"
fi
