import pytest


@pytest.fixture(autouse=True)
def _never_write_runtime_files_into_the_repo(tmp_path_factory, monkeypatch):
    """The live loop writes docs/results/live_positions.md every cycle. Tests must never write it into the repository (it got committed once)."""
    try:
        from fxengine.live import positions
        monkeypatch.setattr(positions, "OUT", tmp_path_factory.mktemp("rt") / "live_positions.md")
    except Exception:
        pass
    yield
