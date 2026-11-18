#!/usr/bin/env bash
# Nightly stocks job (weekdays, after the US close): refresh prices, scan today's setups, close finished forward-test trades, rebuild the FX-dashboard Stocks tab.
# Light (no research rerun). Waits for a quiet VM; never touches the FX services; if anything is off it logs and stops.
set -uo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src
PY=.venv/bin/python
L=data/stocks_nightly.log
log() { echo "[$(date -u '+%F %H:%M:%S')] $*" >> "$L"; }
systemctl is-active --quiet fxengine && systemctl is-active --quiet fxdash || { log "FX services not active: skipped"; exit 0; }
for i in $(seq 1 60); do
  busy=$(pgrep -f "backtest.run_m5|backtest.run_batch|backtest.run_all|oanda_cli|fxengine.data.build|run_batch3|research_once|run_bets|bets.run|stocks.run|stocks.data|stocks_all" | wc -l)
  avail=$(free -m | awk '/Mem:/{print $7}')
  [ "$busy" -eq 0 ] && [ "$avail" -ge 250 ] && break
  sleep 30
done
[ "${busy:-1}" -eq 0 ] && [ "${avail:-0}" -ge 250 ] || { log "VM busy for 30 minutes: skipped tonight"; exit 0; }
$PY -m fxengine.stocks.data > data/stocks_data.log 2>&1 || log "price download exit code $?"
log "prices: $(tail -1 data/stocks_data.log | cut -c1-120)"
$PY -m fxengine.stocks.scan > data/stocks_scan.log 2>&1 || log "scan exit code $?"
log "scan: $(tail -1 data/stocks_scan.log | cut -c1-140)"
$PY -m fxengine.stocks.tab > /dev/null 2>&1 || log "tab fragment not refreshed"
log "done"
