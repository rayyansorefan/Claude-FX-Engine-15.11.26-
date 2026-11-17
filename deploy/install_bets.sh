#!/usr/bin/env bash
# One-time, on the VM: a SEPARATE clone of the betting branch so the live FX engine (branch `engine`, ~/fx) is never touched.
#   bash ~/fx/deploy/install_bets.sh        then:   cd ~/bets && nohup bash deploy/run_bets.sh > data/bets.log 2>&1 &
set -euo pipefail
D="$HOME/bets"
[ -d "$D/.git" ] || git clone -q --branch betting-wip "$(git -C "$(dirname "$0")/.." remote get-url origin)" "$D"
cd "$D"; git pull -q --ff-only origin betting-wip
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q pandas numpy pyarrow requests pytest
PYTHONPATH=src .venv/bin/pytest -q tests/test_bets.py
mkdir -p data/bets docs/results
echo "ready: cd ~/bets && nohup bash deploy/run_bets.sh > data/bets.log 2>&1 &   (then read docs/results/bets.md)"
