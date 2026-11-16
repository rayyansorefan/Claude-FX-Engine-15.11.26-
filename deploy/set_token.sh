#!/usr/bin/env bash
# Replace the OANDA token on the VM (hidden input) and restart the engine. Usage: bash ~/fx/deploy/set_token.sh
set -euo pipefail
cd "$(dirname "$0")/.."
read -rs -p "Paste new OANDA token, then Enter: " T; echo
[ -n "$T" ] || { echo "empty token, nothing changed"; exit 1; }
sed -i '/^OANDA_TOKEN=/d' .env
printf 'OANDA_TOKEN=%s\n' "$T" >> .env
chmod 600 .env
sudo systemctl restart fxengine
echo "saved. New prices should arrive within 5 minutes (a new token can take a few minutes to activate)."
