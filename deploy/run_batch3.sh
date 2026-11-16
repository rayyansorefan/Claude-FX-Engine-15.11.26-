#!/usr/bin/env bash
# Run batch 3 on the VM (E6 daily momentum, E7 carry). Safe to run while the live loop is running (price files are locked).
# Usage: cd ~/fx && git pull && bash deploy/run_batch3.sh            (takes a while on the e2-micro: run it with nohup)
#        nohup bash deploy/run_batch3.sh > data/batch3.log 2>&1 &
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src
mkdir -p data docs/results
# 1) rates for E7 (free FRED CSVs). If a series id is wrong or a gap exists the report says so and E7 is skipped, E6 still runs.
.venv/bin/python -m fxengine.data.rates || echo "RATES FETCH FAILED: E7 will be skipped (see message above)"
# 2) E6 (+ E7 if the rates file is clean)
.venv/bin/python -m fxengine.backtest.run_batch3 all
echo "batch 3 done"
