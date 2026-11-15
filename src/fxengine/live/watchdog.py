"""Run every 5 min by a systemd timer: if the heartbeat is older than 12 min on a weekday market hour, restart the loop and tell you."""
import json, subprocess
import pandas as pd
from pathlib import Path
from ..envfile import load_env
from .telegram import send
from .loop import market_closed


def main():
    now = pd.Timestamp.now(tz="UTC")
    if market_closed(now):
        return
    hb = Path("data/heartbeat.json")
    age = 999 if not hb.exists() else (now - pd.Timestamp(json.loads(hb.read_text())["ts"])).total_seconds() / 60
    if age > 12:
        subprocess.run(["systemctl", "restart", "fxengine"], check=False)
        send(load_env(), f"🔴 WATCHDOG · engine silent {age:.0f} min, restarted it.")


if __name__ == "__main__":
    main()
