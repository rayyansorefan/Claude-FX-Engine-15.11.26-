"""VM ops runner: lets the repo owner's `git push` deploy code and run WHITELISTED jobs on the VM, and pushes results back to
the `vm-results` branch. Runs every 2 minutes from a systemd timer. Research-only: it never touches broker credentials or orders.

Trust model: it executes code from the `engine` branch of the owner's own repo, so protect that branch (2FA, no force-push).
  * Job ids are validated (^[A-Za-z0-9_-]{1,32}$) and every path is shell-quoted; job names come from the fixed tables below,
    never from a file. ops/jobs.txt and ops/control.txt cannot contain commands.
  * Jobs run as systemd transient UNITS (own cgroup): they survive this oneshot service exiting, have a memory cap, run at lowest
    priority, are tracked by unit name (no PID reuse), and `kill` is `systemctl stop` (kills the whole process tree).
  * Two modes. As root (legacy install) jobs run `--uid=USER`; as the owner (after deploy/ops_migrate.sh) jobs run in the user's
    systemd manager and the few privileged commands go through `sudo -n` rules limited to restarting fxengine/fxdash.
  * Deploys are pre-checked (the new tree must import) and verified (services active, zero restarts after 90 s); on failure the
    old commit is restored and that remote commit is remembered as bad, so a broken push never loops."""
from __future__ import annotations
import fcntl, json, os, re, shlex, subprocess, time
from pathlib import Path

REPO = Path(os.environ.get("OPS_DIR", Path(__file__).resolve().parents[3]))
USER = os.environ.get("OPS_USER", "")
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
VERIFY_SECONDS = 90
JOBS_ROOT = {                      # maintenance needing root (only honoured when the runner is root); fixed strings
    "harden": "bash deploy/harden.sh",
    "migrate_ops": "bash deploy/ops_migrate.sh",
}
JOBS = {
    "history": ".venv/bin/python -m fxengine.data.oanda_cli --start 2023-11-01 && .venv/bin/python -m fxengine.data.build",
    "r0": ".venv/bin/python -m fxengine.backtest.run_m5",
    "batch3": "bash deploy/run_batch3.sh",
    "rates": ".venv/bin/python -m fxengine.data.rates",
    "tests": ".venv/bin/pytest -q",
    "full_research": "bash deploy/research_once.sh",
    "report": ".venv/bin/python -m fxengine.ops.report",
}
JOB_MEM = {"history": "450M", "r0": "600M", "batch3": "600M", "full_research": "600M", "tests": "500M"}   # default 300M
RESULT_GLOBS = ["docs/results/*.md", "docs/results/*.json", "docs/trials.jsonl", "data/ops_*.log", "data/ops_report.txt"]
STATE = REPO / "data" / "ops_state.json"
RESULTS_DIR = REPO.parent / "fx-results"


# ---------------------------------------------------------------- shell helpers
def sh(cmd: str, as_user=True, timeout=600) -> subprocess.CompletedProcess:
    """Run `cmd`. as_user=True: as the owner (runuser when we are root). as_user=False: privileged (root, or `sudo -n` if we are not)."""
    if IS_ROOT:
        full = ["runuser", "-u", USER, "--", "bash", "-lc", cmd] if (as_user and USER) else ["bash", "-lc", cmd]
    else:
        full = ["bash", "-lc", cmd if as_user else "sudo -n " + cmd]
    return subprocess.run(full, capture_output=True, text=True, timeout=timeout)


def uenv() -> str:
    """Environment for talking to the owner's systemd user manager when we are not root."""
    return "" if IS_ROOT else f"XDG_RUNTIME_DIR=/run/user/{os.getuid()} "


def sctl() -> str:
    return "systemctl " if IS_ROOT else f"{uenv()}systemctl --user "


# ---------------------------------------------------------------- state
def load_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except json.JSONDecodeError:
            pass
    return {"done": {}, "running": None}


def save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(STATE)                                        # atomic: never a half-written state file


def parse_jobs(text: str):
    """'<id> <job>' per line. The id must match ID_RE and the job must be whitelisted; anything else is reported and ignored."""
    out, bad = [], []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2 or not ID_RE.fullmatch(parts[0]) or (parts[1] not in JOBS and parts[1] not in JOBS_ROOT):
            bad.append(line)
        else:
            out.append((parts[0], parts[1]))
    return out, bad


def notify(text: str):
    try:
        from ..envfile import load_env
        from ..live import telegram
        telegram.send(load_env(str(REPO / ".env")), text)
    except Exception:
        pass


def notify_once(st, key, text):
    """Tell the owner about a distinct problem once, not every 2 minutes."""
    seen = st.setdefault("notified", [])
    if key not in seen:
        seen.append(key)
        del seen[:-50]
        notify(text)


# ---------------------------------------------------------------- code deployment
def _tracked_trials():
    f = REPO / "docs" / "trials.jsonl"
    return f.read_text().splitlines() if f.exists() else []


def _heal_worktree(run):
    """The VM must have no local code changes. Jobs write tracked files (docs/trials.jsonl, docs/results/*), which would block a
    fast-forward: discard those edits but KEEP any VM-only trial-registry lines (the registry is append-only history)."""
    mine = _tracked_trials()
    q = shlex.quote(str(REPO))
    run(f"cd {q} && git checkout -- .")
    # an UNTRACKED copy of a file that upstream now tracks would make the merge abort ("would be overwritten"): clear it
    run(f"cd {q} && for f in docs/trials.jsonl; do git ls-files --error-unmatch $f >/dev/null 2>&1 || rm -f $f; done")
    return mine


def _restore_trials(mine):
    f = REPO / "docs" / "trials.jsonl"
    have = set(f.read_text().splitlines()) if f.exists() else set()
    extra = [l for l in mine if l.strip() and l not in have]
    if extra:
        with f.open("a") as fh:
            fh.write("\n".join(extra) + "\n")


def precheck(remote, run) -> bool:
    """Would the fetched tree even import? Checked in a temp dir BEFORE touching the live checkout."""
    d = "/tmp/fxchk"
    r = run(f"rm -rf {d} && mkdir -p {d} && cd {shlex.quote(str(REPO))} && git archive {shlex.quote(remote)} src | tar -x -C {d} && "
            f"PYTHONPATH={d}/src {shlex.quote(str(REPO))}/.venv/bin/python -c "
            f"'import fxengine.live.loop, fxengine.ops.runner, fxengine.dashboard.serve, fxengine.ops.report'")
    return r.returncode == 0


def services_healthy(run) -> bool:
    a = run("systemctl is-active fxengine fxdash", as_user=False).stdout.split() == ["active", "active"]
    n = run("systemctl show -p NRestarts --value fxengine", as_user=False).stdout.strip()
    return a and n in ("0", "")


def sync_code(st, run=sh) -> str:
    """Pull new commits from origin/engine; install deps; restart services; verify; roll back (once) on failure."""
    if st.get("running"):
        return "busy"                                                # never change code under a running multi-step job
    q = shlex.quote(str(REPO))
    run(f"cd {q} && git fetch -q origin engine")
    local = run(f"cd {q} && git rev-parse HEAD").stdout.strip()
    remote = run(f"cd {q} && git rev-parse origin/engine").stdout.strip()
    if not remote or local == remote:
        return "up-to-date"
    if remote == st.get("bad_remote"):
        return "skipped-known-bad"
    if not precheck(remote, run):
        st["bad_remote"] = remote
        notify_once(st, f"precheck-{remote}", f"🔴 OPS · new code ({remote[:7]}) does not import. Not deployed; staying on {local[:7]}.")
        return "precheck-failed"
    changed = run(f"cd {q} && git diff --name-only {local} {remote}").stdout.split()
    mine = _heal_worktree(run)
    m = run(f"cd {q} && git merge --ff-only {shlex.quote(remote)}")
    _restore_trials(mine)
    if m.returncode != 0:
        st["bad_remote"] = remote
        notify_once(st, f"merge-{remote}", f"🔴 OPS · could not fast-forward to {remote[:7]}: {m.stderr.strip()[-120:]}")
        return "merge-failed"
    if any(c == "pyproject.toml" or c.startswith("requirements") for c in changed):
        run(f"cd {q} && .venv/bin/pip install -q pandas numpy pyarrow requests pytest")
    if any(c.startswith("src/") or c.startswith("deploy/") for c in changed):
        run("systemctl restart fxengine fxdash", as_user=False)
        time.sleep(VERIFY_SECONDS)
        if not services_healthy(run):
            run(f"cd {q} && git reset -q --hard {shlex.quote(local)}")
            run("systemctl restart fxengine fxdash", as_user=False)
            st["bad_remote"] = remote
            notify_once(st, f"rollback-{remote}", f"🔴 OPS · new code ({remote[:7]}) failed after restart. Rolled back to {local[:7]}.")
            return "rolled-back"
        notify(f"🟢 OPS · deployed {remote[:7]} (engine and dashboard restarted)")
    st.pop("bad_remote", None)
    return "deployed"


# ---------------------------------------------------------------- jobs (systemd transient units)
def unit_name(jid) -> str:
    return f"fxjob-{jid}"


def unit_active(jid, run=sh) -> bool:
    r = run(f"{sctl()}is-active {unit_name(jid)}", as_user=IS_ROOT is False)
    return r.stdout.strip() in ("active", "activating", "deactivating", "reloading")


def start_job(jid, name, st, run=sh):
    if not ID_RE.fullmatch(jid):
        raise ValueError("bad job id")
    root_job = name in JOBS_ROOT
    if root_job and not IS_ROOT:
        st["running"] = None
        notify_once(st, f"rootjob-{jid}", f"🔴 JOB refused · {name} needs the root runner (id {jid})")
        st.setdefault("done", {})[jid] = {"job": name, "rc": 126, "minutes": 0}
        save_state(st)
        return
    body = JOBS_ROOT[name] if root_job else JOBS[name]
    log = REPO / "data" / f"ops_{jid}.log"
    rc = REPO / "data" / f"ops_{jid}.rc"
    log.parent.mkdir(parents=True, exist_ok=True)
    rc.unlink(missing_ok=True)
    inner = f"{body}; echo $? > {shlex.quote(str(rc))}"
    props = [f"-p WorkingDirectory={shlex.quote(str(REPO))}", "-E PYTHONPATH=src", "--collect", "--nice=19", "-p IOSchedulingClass=idle",
             f"-p StandardOutput=append:{shlex.quote(str(log))}", f"-p StandardError=append:{shlex.quote(str(log))}"]
    if root_job:
        props += [f"-E OPS_USER={shlex.quote(USER)}", f"-E OPS_DIR={shlex.quote(str(REPO))}"]
    if not root_job:
        props += [f"-p MemoryMax={JOB_MEM.get(name, '300M')}", "-p MemorySwapMax=256M", "-p OOMScoreAdjust=500"]
    who = f"--uid={shlex.quote(USER)} --gid={shlex.quote(USER)} " if (IS_ROOT and not root_job and USER) else ""
    base = "systemd-run " if IS_ROOT else f"{uenv()}systemd-run --user "
    cmd = f"{base}--unit={unit_name(jid)} {who}{' '.join(props)} bash -c {shlex.quote(inner)}"
    r = run(cmd, as_user=not IS_ROOT)
    st["running"] = {"id": jid, "job": name, "unit": unit_name(jid), "start": time.time(), "launched": r.returncode == 0}
    save_state(st)
    if r.returncode != 0:
        notify(f"🔴 JOB did not start · {name} (id {jid}): {r.stderr.strip()[-100:]}")
    else:
        notify(f"🛠 JOB started · {name} (id {jid})")


def finalize(st):
    r = st["running"]
    rcf = REPO / "data" / f"ops_{r['id']}.rc"
    txt = rcf.read_text().strip() if rcf.exists() else ""
    rc = int(txt) if txt.lstrip("-").isdigit() else -1               # no rc file = the job was killed or the VM rebooted
    st["done"][r["id"]] = {"job": r["job"], "rc": rc, "minutes": round((time.time() - r["start"]) / 60, 1)}
    st["running"] = None
    if rc != 0:
        st["halted"] = True                                          # a failed job stops the queue until the owner resumes it
    save_state(st)
    tail = ""
    log = REPO / "data" / f"ops_{r['id']}.log"
    if log.exists():
        lines = [l for l in log.read_text(errors="replace").splitlines() if l.strip()]
        tail = lines[-1][:90] if lines else ""
    notify(f"{'✅' if rc == 0 else '❌'} JOB {'done' if rc == 0 else 'FAILED, queue paused'} · {r['job']} · {st['done'][r['id']]['minutes']} min\n{tail}")
    return rc


def push_results(st, run=sh) -> str:
    """Copy result files into a separate clone and push them to the vm-results branch (needs the write deploy key)."""
    key = Path(f"/home/{USER}") if USER else Path.home()
    url = "git@github.com:rayyansorefan/Claude-FX-Engine-15.11.26-.git"
    ssh = f"GIT_SSH_COMMAND='ssh -i {key}/.ssh/fx_deploy -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new'"
    rd = shlex.quote(str(RESULTS_DIR))
    if not (RESULTS_DIR / ".git").exists():
        r = run(f"{ssh} git clone -q --branch vm-results --single-branch {url} {rd} || "
                f"({ssh} git clone -q {url} {rd} && cd {rd} && git checkout -q -b vm-results)")
        if r.returncode != 0:
            err = "clone-failed: " + r.stderr[-200:]
            notify_once(st, "push-" + err[:60], f"🔴 OPS · cannot reach GitHub with the deploy key ({err[-90:]}). Results are not being pushed.")
            return err
    files = " ".join(RESULT_GLOBS)
    run(f"cd {shlex.quote(str(REPO))} && for f in {files}; do [ -e $f ] && cp --parents $f {rd}/; done; true")
    r = run(f"cd {rd} && git add -A && (git diff --cached --quiet || git -c user.name=fx-vm -c user.email=fx-vm@localhost commit -q -m 'VM results {time.strftime('%Y-%m-%d %H:%M')}') && {ssh} git push -q origin vm-results")
    if r.returncode != 0:
        err = "push-failed: " + r.stderr[-200:]
        notify_once(st, "push-" + err[:60], f"🔴 OPS · pushing results failed ({err[-90:]}).")
        return err
    return "pushed"


def control(st, run=sh):
    """ops/control.txt (owner-controlled via git): `kill <job-id>` stops that job; `resume <token>` lets a halted queue continue
    (only while nothing is running). A line applies once, by its literal text: use a NEW token for every resume."""
    f = REPO / "ops" / "control.txt"
    if not f.exists():
        return
    done = st.setdefault("control_done", [])
    for line in f.read_text().splitlines():
        key = line.split("#")[0].strip()
        parts = key.split()
        if len(parts) != 2 or key in done or not ID_RE.fullmatch(parts[1]):
            continue
        verb, arg = parts
        if verb == "kill":
            r = st.get("running")
            if r and r["id"] == arg:
                run(f"{sctl()}stop {unit_name(arg)}", as_user=not IS_ROOT)
                notify(f"🛑 JOB stopped · {r['job']} (id {r['id']})")
            done.append(key)
        elif verb == "resume" and not st.get("running"):
            st["halted"] = False
            notify("▶️ JOB queue resumed")
            done.append(key)
    save_state(st)


def tick(run=sh):
    st = load_state()
    sync = sync_code(st, run)
    jobs_file = REPO / "ops" / "jobs.txt"
    finished = False
    if st.get("running") and not unit_active(st["running"]["id"], run):
        finalize(st)
        finished = True
    control(st, run)
    if not st.get("running") and not st.get("halted") and jobs_file.exists():
        queue, bad = parse_jobs(jobs_file.read_text())
        if bad:
            notify_once(st, "badjobs-" + "|".join(bad)[:80], f"⚠️ OPS · ignored {len(bad)} invalid line(s) in ops/jobs.txt")
        for jid, name in queue:
            if jid not in st["done"]:
                start_job(jid, name, st, run)
                break
    pushed = push_results(st, run) if finished else "skipped"
    save_state(st)
    return dict(sync=sync, running=st.get("running"), finished=finished, pushed=pushed)


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
