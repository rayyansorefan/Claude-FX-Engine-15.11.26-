#!/usr/bin/env bash
# ONE command for the whole stocks refresh on the VM: wait for a quiet VM -> download free daily prices -> run the pre-registered research -> scan today's setups
# and re-check the earlier ones -> write ONE report (data/stocks_report.txt). Never starts while a heavy FX job runs or memory is short; never touches the FX services.
#   cd ~/stocks && nohup setsid bash deploy/stocks_all.sh > data/stocks_all.log 2>&1 &        later:  cat ~/stocks/data/stocks_report.txt
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p data
exec 9>data/stocks_job.lock                                    # ONE stocks job at a time: a second copy exits at once instead of running in parallel
flock -n 9 || { echo "[$(date -u +%H:%M:%S)] another stocks job is already running: exiting (nothing changed)"; exit 0; }
export PYTHONPATH=src
R=data/stocks_report.txt
log() { echo "[$(date -u +%H:%M:%S)] $*"; }
fail() { log "STOPPED: $*"; echo "STOPPED: $*" > "$R"; exit 1; }
echo 1000 > /proc/$$/oom_score_adj 2>/dev/null || true      # if memory ever runs out this goes first, never the FX engine
mkdir -p data/stocks docs/results
git pull -q --ff-only origin stocks-wip || fail "git pull failed"
log "code: $(git log --oneline | head -1)"
systemctl is-active --quiet fxengine && systemctl is-active --quiet fxdash || fail "FX engine/dashboard not active: not starting anything"
ok=0
for i in $(seq 1 120); do
  busy=$(pgrep -f "backtest.run_m5|backtest.run_batch|backtest.run_all|oanda_cli|fxengine.data.build|run_batch3|research_once|run_bets|bets.run|stocks.run|stocks.data" | wc -l)
  avail=$(free -m | awk '/Mem:/{print $7}')
  if [ "$busy" -eq 0 ] && [ "$avail" -ge 250 ]; then ok=1; break; fi
  log "waiting: heavy jobs running=$busy, memory available=${avail}MB (need 0 and >=250)"; sleep 30
done
[ "$ok" = 1 ] || fail "VM stayed busy for 60 minutes: not started, FX untouched"
log "downloading prices (cached files are reused; a rerun only fetches what is missing or old)"
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
$PY -m fxengine.stocks.data > data/stocks_data.log 2>&1; rc1=$?
log "download exit code $rc1"
if [ -s data/stocks/sec_contact.txt ]; then $PY -m fxengine.stocks.events > data/stocks_events.log 2>&1; log "earnings/filings fetch exit code $?"; else log "no SEC contact file: earnings layer skipped (see data/stocks/sec_contact.txt)"; fi
$PY -m fxengine.stocks.run > data/stocks_run.log 2>&1; rc2=$?
log "research exit code $rc2"
$PY -m fxengine.stocks.filters > data/stocks_filters.log 2>&1; log "entry-filter study exit code $?"
$PY -m fxengine.stocks.scan > data/stocks_scan.log 2>&1; rc3=$?
log "scan exit code $rc3"
{ echo "download:$rc1 research:$rc2 scan:$rc3   finished: $(date -u '+%F %T') UTC   code: $(git log --oneline | head -1)"
  echo; echo "== DATA =="; tail -3 data/stocks_data.log
  echo; echo "== EARNINGS / FILINGS =="; tail -2 data/stocks_events.log 2>&1
  echo; echo "== RESEARCH =="; cat docs/results/stocks.md 2>&1
  echo; echo "== ENTRY-FILTER STUDY =="; tail -8 data/stocks_filters.log 2>&1 | cut -c1-200
  echo; echo "== SCAN =="; tail -2 data/stocks_scan.log
  echo; echo "== VM =="; free -m | sed -n 2p; echo "fx services: $(systemctl is-active fxengine fxdash | tr '\n' ' ')"; } > "$R"
log "DONE. Report: cat data/stocks_report.txt"
