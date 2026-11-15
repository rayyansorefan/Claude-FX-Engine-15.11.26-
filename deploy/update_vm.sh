#!/usr/bin/env bash
# Update the running VM to the latest `engine` branch: pull, install, test, restart. Copy-paste on the VM:
#   cd ~/fx && bash deploy/update_vm.sh
set -euo pipefail
cd "$(dirname "$0")/.."
git pull -q
.venv/bin/pip install -q pandas numpy pyarrow requests pytest
PYTHONPATH=src .venv/bin/pytest -q
sudo systemctl restart fxengine fxdash
sudo systemctl --no-pager --lines=3 status fxengine fxdash | grep -E "Active|fx"
grep -q '^HC_PING_URL=' .env || echo "NOTE: no HC_PING_URL in .env -> no off-host dead-man alert. Add a free healthchecks.io ping URL."
# verify every price file opens (a corrupt file would show up here)
PYTHONPATH=src .venv/bin/python - <<'PY'
from fxengine.data import store
from fxengine.live.scan import PAIRS
bad = []
for s in PAIRS:
    for tf in ("M5", "H1", "H4"):
        try:
            store.load(s, tf)
        except Exception as e:
            bad.append((s, tf, type(e).__name__))
print("price files OK" if not bad else f"CORRUPT price files, delete and re-download: {bad}")
PY
