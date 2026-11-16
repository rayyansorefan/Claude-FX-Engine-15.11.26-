import json, types
from pathlib import Path
import pytest
from fxengine.ops import runner as R


class Fake:
    """Scripted stand-in for runner.sh: records commands, returns canned stdout by substring match."""
    def __init__(self, replies=None):
        self.cmds, self.replies = [], replies or {}

    def __call__(self, cmd, as_user=True, timeout=600):
        self.cmds.append(cmd)
        for k, v in self.replies.items():
            if k in cmd:
                out, rc = v if isinstance(v, tuple) else (v, 0)
                return types.SimpleNamespace(stdout=out, stderr="", returncode=rc)
        return types.SimpleNamespace(stdout="", stderr="", returncode=0)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "REPO", tmp_path)
    monkeypatch.setattr(R, "STATE", tmp_path / "data" / "ops_state.json")
    monkeypatch.setattr(R, "RESULTS_DIR", tmp_path.parent / "fx-results-test")
    monkeypatch.setattr(R, "notify", lambda t: sent.append(t))
    (tmp_path / "ops").mkdir()
    sent.clear()
    return tmp_path


sent = []


def test_parse_jobs_whitelist_only():
    q, bad = R.parse_jobs("# c\n001 report\n002 rm\n003 r0 # trailing\nbroken line here\n004 history\n")
    assert q == [("001", "report"), ("003", "r0"), ("004", "history")]
    assert len(bad) == 2                                   # unknown job name and malformed line are rejected, never executed


def test_no_commands_come_from_the_file():
    for cmd in R.JOBS.values():
        assert "$(" not in cmd and "`" not in cmd and ";" not in cmd.replace("; echo", "")   # fixed strings only


def test_job_runs_once_in_order_then_finalizes_and_pushes(repo, monkeypatch):
    (repo / "ops" / "jobs.txt").write_text("001 report\n002 r0\n")
    fake = Fake({"git rev-parse HEAD": "aaa", "git rev-parse origin/engine": "aaa", "echo $!": "4242\n"})
    monkeypatch.setattr(R, "pid_alive", lambda pid: False)
    out = R.tick(fake)
    assert out["running"]["id"] == "001" and any("report" in s for s in sent)
    (repo / "data").mkdir(exist_ok=True)
    (repo / "data" / "ops_001.rc").write_text("0\n")
    (repo / "data" / "ops_001.log").write_text("line1\nall good\n")
    out = R.tick(fake)                                       # previous job finished -> finalized, results pushed, NEXT job starts
    st = json.loads((repo / "data" / "ops_state.json").read_text())
    assert st["done"]["001"]["rc"] == 0 and out["finished"] is True and out["running"]["id"] == "002"
    assert any("done" in s and "report" in s for s in sent)
    # a third tick with the same queue does not restart finished ids
    (repo / "data" / "ops_002.rc").write_text("1\n")
    R.tick(fake)
    st = json.loads((repo / "data" / "ops_state.json").read_text())
    assert st["done"]["002"]["rc"] == 1 and st["running"] is None and any("FAILED" in s for s in sent)
    n = len([c for c in fake.cmds if "nohup" in c])
    R.tick(fake)
    assert len([c for c in fake.cmds if "nohup" in c]) == n


def test_only_one_job_at_a_time(repo, monkeypatch):
    (repo / "ops" / "jobs.txt").write_text("001 r0\n002 batch3\n")
    fake = Fake({"git rev-parse HEAD": "a", "git rev-parse origin/engine": "a", "echo $!": "7\n"})
    monkeypatch.setattr(R, "pid_alive", lambda pid: True)
    R.tick(fake); R.tick(fake)
    assert len([c for c in fake.cmds if "nohup" in c]) == 1


def test_sync_deploys_restarts_and_rolls_back_on_failure(repo):
    ok = Fake({"git rev-parse HEAD": "old", "git rev-parse origin/engine": "new", "git diff --name-only": "src/fxengine/x.py\n",
               "is-active": "active\nactive\n"})
    R.time.sleep = lambda s: None
    assert R.sync_code(ok) == "deployed" and any("systemctl restart" in c for c in ok.cmds)
    bad = Fake({"git rev-parse HEAD": "old", "git rev-parse origin/engine": "new", "git diff --name-only": "src/fxengine/x.py\n",
                "is-active": "failed\nactive\n"})
    assert R.sync_code(bad) == "rolled-back" and any("reset -q --hard old" in c for c in bad.cmds)
    same = Fake({"git rev-parse HEAD": "x", "git rev-parse origin/engine": "x"})
    assert R.sync_code(same) == "up-to-date"
    docs_only = Fake({"git rev-parse HEAD": "a", "git rev-parse origin/engine": "b", "git diff --name-only": "docs/x.md\n"})
    assert R.sync_code(docs_only) == "deployed" and not any("systemctl restart" in c for c in docs_only.cmds)
