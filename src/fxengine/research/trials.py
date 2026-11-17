"""Trial registry: every variant/parameter set ever evaluated is appended to docs/trials.jsonl, so the multiple-testing
penalty counts honestly. docs/trials_seed.jsonl (committed) holds the historical trials; it is merged in on first use,
so the live file can stay untracked on the VM without ever colliding with a tracked file."""
import json
from pathlib import Path

REG = Path("docs/trials.jsonl")


def _names(f: Path):
    return [json.loads(l)["name"] for l in f.read_text().splitlines() if l.strip()] if f.exists() else []


def ensure_seed(reg: Path = REG) -> None:
    """Append any seeded historical trial that is not in the registry yet (idempotent)."""
    seed = reg.with_name(reg.stem + "_seed" + reg.suffix)
    if not seed.exists():
        return
    have = set(_names(reg))
    missing = [l for l in seed.read_text().splitlines() if l.strip() and json.loads(l)["name"] not in have]
    if missing:
        reg.parent.mkdir(parents=True, exist_ok=True)
        with reg.open("a") as f:
            f.write("\n".join(missing) + "\n")


def log_trial(name: str, params: dict, note: str = "", reg: Path = REG) -> int:
    ensure_seed(reg)
    reg.parent.mkdir(parents=True, exist_ok=True)
    with reg.open("a") as f:
        f.write(json.dumps({"name": name, "params": params, "note": note}, sort_keys=True) + "\n")
    return count_trials(reg)


def count_trials(reg: Path = REG) -> int:
    ensure_seed(reg)
    return len(_names(reg))
