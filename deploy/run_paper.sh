#!/usr/bin/env bash
# PAPER betting dashboard (virtual £100, nothing goes to any bookmaker). Binds to the VM's Tailscale IP only, never public.
#   cd ~/bets && nohup bash deploy/run_paper.sh > data/paper.log 2>&1 &        then open  http://<tailscale ip>:8789
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src
echo 1000 > /proc/$$/oom_score_adj 2>/dev/null || true      # if memory ever runs out this goes first, never the FX engine
HOST="${PAPER_HOST:-$(tailscale ip -4 2>/dev/null | head -1)}"
[ -n "$HOST" ] || { echo "no Tailscale IP found: set PAPER_HOST=127.0.0.1 to bind locally"; exit 1; }
exec .venv/bin/python -m fxengine.bets.paper_serve --host "$HOST" --port 8789
