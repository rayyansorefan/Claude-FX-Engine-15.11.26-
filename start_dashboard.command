#!/bin/bash
# Double-click to start your private dashboard. It opens in your browser; refresh the page to update.
cd "$(dirname "$0")"
git pull -q 2>/dev/null
PYTHONPATH=src .venv/bin/python -m fxengine.dashboard.serve --open --refresh --auto 60
