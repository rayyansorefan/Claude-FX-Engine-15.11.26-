#!/usr/bin/env bash
# One-time: download 3 years of M5 prices, build H1/H4/M15, run every backtest so the dashboard shows real research.
set -e
cd "$(dirname "$0")/.."
export PYTHONPATH=src
mkdir -p data docs/results
.venv/bin/python -m fxengine.data.oanda_cli --start 2023-11-01
.venv/bin/python -m fxengine.data.build
.venv/bin/python -m fxengine.backtest.run M15
.venv/bin/python -m fxengine.backtest.run H1
.venv/bin/python -m fxengine.backtest.run_all
.venv/bin/python -m fxengine.backtest.run_batch2
echo "research done"
