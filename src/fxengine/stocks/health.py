"""Self-check for both engines, run by the VM every 15 minutes. If anything is stale or down it sends ONE Telegram message per problem per day, so you never have to look.
Read-only: it only looks (file ages, service states, memory, disk) and never restarts or changes anything on the FX side.
Checks: Stocks 5-minute live job fresh (weekday market hours) · Stocks nightly scan ran after the last US close · stocksdash running · FX live loop heartbeat fresh (market hours) · fxengine/fxdash running ·
memory and disk. Messages are 3 lines at most, like every other alert. Writes docs/results/stocks_health.json for the System tab."""
from __future__ import annotations
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from . import alerts

LIVE_MAX_AGE_MIN = 20
FX_MAX_AGE_MIN = 20
MARKET_HOURS = (6, 22)                    # UTC, weekdays: when the 5-minute stocks job and the FX loop should be producing fresh data
NIGHTLY_AT = (22, 45)                     # UTC, weekdays


def last_nightly_due(now: datetime) -> datetime:
    """The most recent weekday 22:45 UTC that is already more than 90 minutes in the past (the scan should have finished by then)."""
    d = now.replace(hour=NIGHTLY_AT[0], minute=NIGHTLY_AT[1], second=0, microsecond=0)
    while d + timedelta(minutes=90) > now or d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _age_min(p: Path, now: datetime) -> float | None:
    try:
        return (now - datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)).total_seconds() / 60
    except OSError:
        return None


def market_open_window(now: datetime) -> bool:
    return now.weekday() < 5 and MARKET_HOURS[0] <= now.hour < MARKET_HOURS[1]


def service_active(name: str) -> bool | None:
    try:
        r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "active"
    except Exception:
        return None                                       # cannot tell: never raise a false alarm


def check(now: datetime, root: Path = Path("."), fx_root: Path = Path("../fx"), active=service_active, mem_mb: float | None = None, disk_pct: float | None = None) -> list[tuple[str, str]]:
    """List of (problem key, plain-English message). Empty = everything is fine."""
    out = []
    res = root / "docs/results"
    if market_open_window(now):
        a = _age_min(res / "stocks_live.json", now)
        if a is None or a > LIVE_MAX_AGE_MIN:
            out.append(("stocks-live", f"Stocks live job has not updated for {'a long time' if a is None else f'{a:.0f} minutes'}. Paper buys and sells are paused until it runs again."))
        hb = fx_root / "data/heartbeat.json"
        h = _age_min(hb, now)
        if h is not None and h > FX_MAX_AGE_MIN:
            out.append(("fx-heartbeat", f"FX live loop has not reported for {h:.0f} minutes. New FX setups are paused until it runs again."))
    due = last_nightly_due(now)
    n = _age_min(res / "stocks_setups.json", now)
    if n is None or (now - timedelta(minutes=n)) < due - timedelta(minutes=5):
        out.append(("stocks-nightly", f"Stocks nightly scan has not completed since {due:%a %d %b}'s close. Today's new setups and the final record are missing."))
    for svc, key, nice in (("stocksdash", "svc-stocksdash", "Stocks dashboard"), ("fxengine", "svc-fxengine", "FX live loop"), ("fxdash", "svc-fxdash", "FX dashboard")):
        if active(svc) is False:
            out.append((key, f"{nice} is not running."))
    if mem_mb is not None and mem_mb < 60:
        out.append(("memory", f"The VM is almost out of memory ({mem_mb:.0f} MB free): jobs may be killed."))
    if disk_pct is not None and disk_pct > 90:
        out.append(("disk", f"The VM disk is {disk_pct:.0f}% full."))
    return out


def _mem_free_mb() -> float | None:
    try:
        for ln in Path("/proc/meminfo").read_text().splitlines():
            if ln.startswith("MemAvailable:"):
                return int(ln.split()[1]) / 1024
    except OSError:
        return None
    return None


def run(now: datetime | None = None, root: Path = Path("."), fx_root: Path | None = None, env: dict | None = None, post=None, sent_path: Path = alerts.SENT, active=service_active) -> dict:
    now = now or datetime.now(timezone.utc)
    fx_root = fx_root if fx_root is not None else root.resolve().parent / "fx"
    du = shutil.disk_usage(root)
    problems = check(now, root, fx_root, active, _mem_free_mb(), du.used / du.total * 100)
    env = alerts.load_env(root / ".env") if env is None else env
    done = set(json.loads(sent_path.read_text())) if sent_path.exists() else set()
    sent = 0
    for key, msg in problems:
        k = f"health|{key}|{now:%Y-%m-%d}"
        if k in done:
            continue
        if alerts.send(env, "\n".join(["🔴 ENGINE CHECK", msg, "The VM checks itself every 15 minutes; this is sent once a day per problem."][:3]), post):
            done.add(k)
            sent += 1
    if sent:
        sent_path.parent.mkdir(parents=True, exist_ok=True)
        sent_path.write_text(json.dumps(sorted(done)[-3000:]))
    out = root / "docs/results/stocks_health.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(asof=f"{now:%Y-%m-%d %H:%M} UTC", ok=not problems, problems=[m for _, m in problems])))
    return dict(problems=[k for k, _ in problems], alerts_sent=sent)


if __name__ == "__main__":
    print(run())
