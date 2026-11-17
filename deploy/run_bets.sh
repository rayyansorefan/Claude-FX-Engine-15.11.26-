#!/usr/bin/env bash
# Betting research, one command: download free football-data.co.uk CSVs (Bet365 + Pinnacle odds), then run the 6 pre-registered rules.
# Research only: never logs in to Bet365, never places a bet. Runs from ANY clone (use deploy/install_bets.sh for a separate one).
# Usage:  bash deploy/run_bets.sh              (full: download + research; ~6 min of polite 1s-per-file downloading)
#         bash deploy/run_bets.sh research     (reuse data/bets/matches.parquet, just rerun the rules)
#         nohup bash deploy/run_bets.sh > data/bets.log 2>&1 &
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
echo 1000 > /proc/$$/oom_score_adj 2>/dev/null || true   # if memory ever runs out the kernel stops THIS job first, never the FX engine
mkdir -p data/bets docs/results
if [ "${1:-all}" != "research" ]; then
  $PY -m fxengine.bets.data            # writes data/bets/matches.parquet + gaps.txt; a bad file is listed, never fatal
  echo "gaps: $(wc -l < data/bets/gaps.txt) files unavailable (see data/bets/gaps.txt)"
fi
$PY -m fxengine.bets.run                # writes docs/results/bets.{md,json}; appends the 6 rules to docs/bets_trials.jsonl once
echo "betting research done -> docs/results/bets.md and docs/results/bets.html (the dashboard)"
