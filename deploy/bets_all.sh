#!/usr/bin/env bash
# ONE command for the whole betting refresh on the VM: update code -> wait until the VM is quiet -> rebuild data + research -> restart the paper
# server -> write ONE report file (data/bets_report.txt). Never starts while a heavy FX job runs or memory is short; never touches the FX services.
#   cd ~/bets && git pull -q --ff-only origin betting-wip && nohup setsid bash deploy/bets_all.sh > data/bets_all.log 2>&1 &
#   later:  cat ~/bets/data/bets_report.txt
set -uo pipefail
cd "$(dirname "$0")/.."
R=data/bets_report.txt
log() { echo "[$(date -u +%H:%M:%S)] $*"; }
fail() { log "STOPPED: $*"; echo "STOPPED: $*" > "$R"; exit 1; }
git pull -q --ff-only origin betting-wip || fail "git pull failed"
log "code: $(git log --oneline | head -1)"
systemctl is-active --quiet fxengine && systemctl is-active --quiet fxdash || fail "FX engine/dashboard not active: not starting anything; check the FX engine first"
pkill -f paper_serve 2>/dev/null; sleep 2
ok=0
for i in $(seq 1 120); do                                    # wait up to 60 min for quiet
  busy=$(pgrep -f "backtest.run_m5|backtest.run_batch|backtest.run_all|oanda_cli|fxengine.data.build|run_batch3|research_once|bets.run|bets.data|run_bets" | wc -l)
  avail=$(free -m | awk '/Mem:/{print $7}')
  if [ "$busy" -eq 0 ] && [ "$avail" -ge 300 ]; then ok=1; break; fi
  log "waiting: heavy jobs running=$busy, memory available=${avail}MB (need 0 and >=300)"; sleep 30
done
[ "$ok" = 1 ] || fail "VM stayed busy for 60 minutes: not started, FX untouched"
log "VM quiet: rebuilding data and running the research"
bash deploy/run_bets.sh > data/bets.log 2>&1; rc=$?
log "research exit code $rc"
setsid nohup bash deploy/run_paper.sh > data/paper.log 2>&1 < /dev/null &
sleep 10
{ echo "research exit code: $rc    finished: $(date -u '+%F %T') UTC    code: $(git log --oneline | head -1)"
  echo; echo "== PINNACLE/BET365 PRICE COVERAGE BY SEASON =="; cat data/bets/coverage.txt 2>&1
  echo; echo "== RESULTS =="; cat docs/results/bets.md 2>&1
  echo; echo "== LOG TAIL =="; tail -4 data/bets.log
  echo; echo "== PAPER SERVER =="; tail -2 data/paper.log
  echo; echo "== VM =="; free -m | sed -n 2p; echo "fx services: $(systemctl is-active fxengine fxdash | tr '\n' ' ')"; } > "$R"
log "DONE. Report: cat data/bets_report.txt"
