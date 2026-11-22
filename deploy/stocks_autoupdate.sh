#!/usr/bin/env bash
# Runs on the VM every 10 minutes (systemd timer, as root). Keeps BOTH engines on their newest tested code WITHOUT anyone pasting commands.
# Rules: fast-forward only (never overwrites local work); nothing is installed or tested here (every change is tested before it is pushed);
# Stocks (~/stocks on `stocks-wip`): waits while a stocks job runs, restarts only stocksdash.
# FX (~/fx on `engine`): restarts the dashboard for any src change and the live loop only if live/engine/data/feature code changed (it is restart-safe: all state is in SQLite, alerts are de-duplicated).
# Pause switch for FX: create ~/fx/data/autoupdate.pause to stop FX updates, delete it to resume.
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p data
log() { echo "[$(date -u '+%F %H:%M:%S')] $*" >> data/stocks_autoupdate.log; }
exec 8>data/stocks_update.lock
flock -n 8 || exit 0

update_stocks() {
  local U old
  U="$(stat -c %U .)"
  g() { runuser -u "$U" -- git "$@"; }
  g config core.fileMode false                          # a chmod on a script must never look like a local change that blocks the update
  g fetch -q origin stocks-wip 2>/dev/null || { log "fetch failed"; return; }
  [ "$(g rev-parse HEAD)" = "$(g rev-parse FETCH_HEAD)" ] && return
  if pgrep -f "fxengine.stocks.(scan|data|events|filingtext|run)|stocks_nightly|stocks_all" >/dev/null; then log "stocks job running: update waits"; return; fi
  old="$(g rev-parse --short HEAD)"
  if g merge -q --ff-only FETCH_HEAD 2>/dev/null; then
    log "updated $old -> $(g rev-parse --short HEAD)"
    systemctl restart stocksdash && log "stocksdash restarted"
  else
    log "cannot fast-forward (local changes?): left as it was"
  fi
}

update_fx() {
  local FXD FU fold changed
  FXD="$(cd .. && pwd)/fx"
  [ -d "$FXD/.git" ] || return
  [ -e "$FXD/data/autoupdate.pause" ] && return
  FU="$(stat -c %U "$FXD")"
  fxg() { runuser -u "$FU" -- git -C "$FXD" "$@"; }
  fxg config core.fileMode false
  fxg fetch -q origin engine 2>/dev/null || { log "fetch failed (FX)"; return; }
  [ "$(fxg rev-parse HEAD)" = "$(fxg rev-parse FETCH_HEAD)" ] && return
  fold="$(fxg rev-parse --short HEAD)"
  changed="$(fxg diff --name-only HEAD FETCH_HEAD)"
  if fxg merge -q --ff-only FETCH_HEAD 2>/dev/null; then
    log "FX updated $fold -> $(fxg rev-parse --short HEAD)"
    if echo "$changed" | grep -q '^src/'; then
      systemctl restart fxdash && log "fxdash restarted"
      if echo "$changed" | grep -Eq '^src/fxengine/(live|engine|data|features|learn|setups|calendar)'; then
        systemctl restart fxengine && log "fxengine restarted"
      fi
    fi
  else
    log "FX cannot fast-forward (local changes?): left as it was"
  fi
}

update_stocks
update_fx
exit 0
