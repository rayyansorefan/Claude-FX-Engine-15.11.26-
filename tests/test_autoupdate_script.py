import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "stocks_autoupdate.sh"


def sh(cmd, cwd, env=None):
    return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, env=env, check=True).stdout


def _setup(tmp):
    """remote repos for stocks-wip and engine, clones ~/stocks and ~/fx, and fake runuser/systemctl/pgrep so nothing real is touched."""
    bin_ = tmp / "bin"; bin_.mkdir()
    (bin_ / "runuser").write_text('#!/bin/bash\nshift 3\nexec "$@"\n')
    (bin_ / "systemctl").write_text(f'#!/bin/bash\necho "$@" >> {tmp}/systemctl.log\n')
    (bin_ / "pgrep").write_text('#!/bin/bash\nexit 1\n')
    for f in bin_.iterdir():
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    git = "git -c user.email=t@t -c user.name=t"
    for name, branch in (("stocks", "stocks-wip"), ("fx", "engine")):
        origin = tmp / f"{name}_origin.git"
        sh(f"git init -q --bare {origin}", tmp)
        work = tmp / f"{name}_work"
        sh(f"git init -q -b {branch} {work}", tmp)
        (work / "src/fxengine/live").mkdir(parents=True); (work / "src/fxengine/live/a.py").write_text("1\n")
        (work / "src/fxengine/dashboard").mkdir(parents=True); (work / "src/fxengine/dashboard/b.py").write_text("1\n")
        (work / "docs").mkdir(); (work / "docs/n.md").write_text("1\n")
        if name == "stocks":
            (work / "deploy").mkdir(); (work / "deploy/stocks_autoupdate.sh").write_text(SCRIPT.read_text())
        sh(f"{git} add -A && {git} commit -qm first && git remote add origin {origin} && git push -q origin {branch}", work)
        sh(f"git clone -q -b {branch} {origin} {tmp / name}", tmp)
    return bin_, git


def _run(tmp, bin_):
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}")
    subprocess.run(["bash", str(tmp / "stocks/deploy/stocks_autoupdate.sh")], cwd=tmp / "stocks", env=env, capture_output=True, text=True)
    log = (tmp / "systemctl.log").read_text().split("\n") if (tmp / "systemctl.log").exists() else []
    return [x for x in log if x]


def _push(tmp, git, name, branch, path, content):
    w = tmp / f"{name}_work"
    (w / path).write_text(content)
    sh(f"{git} add -A && {git} commit -qm change && git push -q origin {branch}", w)


def test_autoupdate_pulls_both_repos_and_restarts_only_what_changed(tmp_path):
    bin_, git = _setup(tmp_path)
    assert _run(tmp_path, bin_) == []                                                     # nothing new: nothing restarted
    _push(tmp_path, git, "fx", "engine", "docs/n.md", "2\n")                              # docs only: pulled, nothing restarted
    assert _run(tmp_path, bin_) == [] and (tmp_path / "fx/docs/n.md").read_text() == "2\n"
    _push(tmp_path, git, "fx", "engine", "src/fxengine/dashboard/b.py", "2\n")            # dashboard code: only fxdash
    assert _run(tmp_path, bin_) == ["restart fxdash"]
    (tmp_path / "systemctl.log").unlink()
    _push(tmp_path, git, "fx", "engine", "src/fxengine/live/a.py", "2\n")                 # live loop code: dashboard AND loop
    assert _run(tmp_path, bin_) == ["restart fxdash", "restart fxengine"]
    (tmp_path / "systemctl.log").unlink()
    _push(tmp_path, git, "stocks", "stocks-wip", "src/fxengine/live/a.py", "9\n")          # Stocks change: only stocksdash, FX untouched
    assert _run(tmp_path, bin_) == ["restart stocksdash"]


def test_autoupdate_pause_switch_and_local_changes_are_respected(tmp_path):
    bin_, git = _setup(tmp_path)
    (tmp_path / "fx/data").mkdir(); (tmp_path / "fx/data/autoupdate.pause").write_text("")
    _push(tmp_path, git, "fx", "engine", "src/fxengine/live/a.py", "2\n")
    assert _run(tmp_path, bin_) == [] and (tmp_path / "fx/src/fxengine/live/a.py").read_text() == "1\n"      # paused: not touched
    (tmp_path / "fx/data/autoupdate.pause").unlink()
    (tmp_path / "fx/src/fxengine/live/a.py").write_text("local edit\n"); sh(f"{git} commit -qam local", tmp_path / "fx")     # diverged local commit: cannot fast-forward
    assert _run(tmp_path, bin_) == [] and (tmp_path / "fx/src/fxengine/live/a.py").read_text() == "local edit\n"
    assert "cannot fast-forward" in (tmp_path / "stocks/data/stocks_autoupdate.log").read_text()
