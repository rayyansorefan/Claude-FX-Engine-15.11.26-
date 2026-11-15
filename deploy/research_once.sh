#!/usr/bin/env bash
# One-time: download 3 years of M5 prices, build M15/H1/H4, run every backtest and the M5-resolution rerun (R0),
# so the dashboard's Research and Performance tabs show real research. Safe to run while the live loop runs.
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
.venv/bin/python -m fxengine.backtest.run_m5
echo "research done"
