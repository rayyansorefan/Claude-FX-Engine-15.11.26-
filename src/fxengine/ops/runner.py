"""VM ops runner: lets the repo owner's `git push` deploy code and run WHITELISTED jobs on the VM, and pushes results back to
the `vm-results` branch so they can be read without anyone copy-pasting. Runs every 2 minutes from a systemd timer (as root;
git and jobs are executed as OPS_USER). Research-only: it never touches broker credentials or orders.
Security model: it executes code from the `engine` branch of the owner's own repo (the same trust as `git pull`). Jobs are
chosen by NAME from the fixed table below; ops/jobs.txt cannot contain arbitrary commands."""
from __future__ import annotations
import fcntl, json, os, subprocess, time
from pathlib import Path

REPO = Path(os.environ.get("OPS_DIR", Path(__file__).resolve().parents[3]))
USER = os.environ.get("OPS_USER", "")
PY = f"{REPO}/.venv/bin/python"
ENV = f"cd {REPO} && export PYTHONPATH=src && "
JOBS = {
    "history": ".venv/bin/python -m fxengine.data.oanda_cli --start 2023-11-01 && .venv/bin/python -m fxengine.data.build",
    "r0": ".venv/bin/python -m fxengine.backtest.run_m5",
    "batch3": "bash deploy/run_batch3.sh",
    "rates": ".venv/bin/python -m fxengine.data.rates",
    "tests": ".venv/bin/pytest -q",
    "full_research": "bash deploy/research_once.sh",
    "report": ".venv/bin/python -m fxengine.ops.report",
}
RESULT_GLOBS = ["docs/results/*.md", "docs/results/*.json", "docs/trials.jsonl", "data/ops_*.log", "data/ops_report.txt"]
STATE = REPO / "data" / "ops_state.json"
RESULTS_DIR = REPO.parent / "fx-results"


def sh(cmd: str, as_user=True, timeout=600) -> subprocess.CompletedProcess:
    full = ["runuser", "-u", USER, "--", "bash", "-lc", cmd] if (as_user and USER) else ["bash", "-lc", cmd]
    return subprocess.run(full, capture_output=True, text=True, timeout=timeout)


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"done": {}, "running": None}


def save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1))


def parse_jobs(text: str):
    """'id job' per line; unknown job names are ignored (and reported), comments allowed."""
    out, bad = [], []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            bad.append(line)
        elif parts[1] not in JOBS:
            bad.append(line)
        else:
            out.append((parts[0], parts[1]))
    return out, bad


def pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def notify(text: str):
    try:
        from ..envfile import load_env
        from ..live import telegram
        telegram.send(load_env(str(REPO / ".env")), text)
    except Exception:
        pass


def sync_code(run=sh) -> str:
    """Pull new commits from origin/engine, install deps if needed, restart services, roll back if they fail to start."""
    run(f"cd {REPO} && git fetch -q origin engine")
    local = run(f"cd {REPO} && git rev-parse HEAD").stdout.strip()
    remote = run(f"cd {REPO} && git rev-parse origin/engine").stdout.strip()
    if not remote or local == remote:
        return "up-to-date"
    changed = run(f"cd {REPO} && git diff --name-only {local} {remote}").stdout.split()
    m = run(f"cd {REPO} && git merge --ff-only origin/engine")
    if m.returncode != 0:
        notify("🔴 OPS · could not fast-forward the code (local changes on the VM?). Not updated.")
        return "merge-failed"
    if any(c in ("pyproject.toml",) or c.startswith("requirements") for c in changed):
        run(f"cd {REPO} && .venv/bin/pip install -q pandas numpy pyarrow requests pytest")
    if any(c.startswith("src/") for c in changed):
        run("systemctl restart fxengine fxdash", as_user=False)
        time.sleep(25)
        ok = run("systemctl is-active fxengine fxdash", as_user=False).stdout.split() == ["active", "active"]
        if not ok:
            run(f"cd {REPO} && git reset -q --hard {local}")
            run("systemctl restart fxengine fxdash", as_user=False)
            notify(f"🔴 OPS · new code ({remote[:7]}) failed to start. Rolled back to {local[:7]}.")
            return "rolled-back"
        notify(f"🟢 OPS · deployed {remote[:7]} (engine and dashboard restarted)")
    return "deployed"


def start_job(jid, name, st, run=sh):
    log = REPO / "data" / f"ops_{jid}.log"
    rc = REPO / "data" / f"ops_{jid}.rc"
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = f"{ENV}nohup bash -c '{JOBS[name]}; echo $? > {rc}' > {log} 2>&1 & echo $!"
    r = run(cmd)
    pid = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else None
    st["running"] = {"id": jid, "job": name, "pid": pid, "start": time.time()}
    save_state(st)
    notify(f"🛠 JOB started · {name} (id {jid})")


def finalize(st):
    r = st["running"]
    rcf = REPO / "data" / f"ops_{r['id']}.rc"
    rc = int(rcf.read_text().strip()) if rcf.exists() and rcf.read_text().strip().lstrip("-").isdigit() else -1
    st["done"][r["id"]] = {"job": r["job"], "rc": rc, "minutes": round((time.time() - r["start"]) / 60, 1)}
    st["running"] = None
    save_state(st)
    tail = ""
    log = REPO / "data" / f"ops_{r['id']}.log"
    if log.exists():
        lines = [l for l in log.read_text().splitlines() if l.strip()]
        tail = lines[-1][:90] if lines else ""
    notify(f"{'✅' if rc == 0 else '❌'} JOB {'done' if rc == 0 else 'FAILED'} · {r['job']} · {st['done'][r['id']]['minutes']} min\n{tail}")
    return rc


def push_results(run=sh) -> str:
    """Copy result files into a separate clone and push them to the vm-results branch (needs the write deploy key)."""
    key = Path.home() if not USER else Path(f"/home/{USER}")
    url = "git@github.com:rayyansorefan/Claude-FX-Engine-15.11.26-.git"
    ssh = f"GIT_SSH_COMMAND='ssh -i {key}/.ssh/fx_deploy -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new'"
    if not (RESULTS_DIR / ".git").exists():
        r = run(f"{ssh} git clone -q --branch vm-results --single-branch {url} {RESULTS_DIR} || "
                f"({ssh} git clone -q {url} {RESULTS_DIR} && cd {RESULTS_DIR} && git checkout -q -b vm-results)")
        if r.returncode != 0:
            return "clone-failed: " + r.stderr[-200:]
    files = " ".join(RESULT_GLOBS)
    run(f"cd {REPO} && for f in {files}; do [ -e $f ] && cp --parents $f {RESULTS_DIR}/; done; true")
    r = run(f"cd {RESULTS_DIR} && git add -A && (git diff --cached --quiet || git -c user.name=fx-vm -c user.email=fx-vm@localhost commit -q -m 'VM results {time.strftime('%Y-%m-%d %H:%M')}') && {ssh} git push -q origin vm-results")
    return "pushed" if r.returncode == 0 else "push-failed: " + r.stderr[-200:]


def tick(run=sh):
    st = load_state()
    sync = sync_code(run)
    jobs_file = REPO / "ops" / "jobs.txt"
    finished = False
    if st["running"] and not pid_alive(st["running"]["pid"]):
        finalize(st)
        finished = True
    if not st["running"] and jobs_file.exists():
        queue, bad = parse_jobs(jobs_file.read_text())
        for jid, name in queue:
            if jid not in st["done"]:
                start_job(jid, name, st, run)
                break
    pushed = push_results(run) if finished else "skipped"
    return dict(sync=sync, running=st["running"], finished=finished, pushed=pushed)


def main():
    REPO.joinpath("data").mkdir(exist_ok=True)
    with open(REPO / "data" / "ops.lock", "w") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        print(json.dumps(tick(), default=str))


if __name__ == "__main__":
    main()
