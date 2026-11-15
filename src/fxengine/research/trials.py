"""Trial registry: every variant/parameter set ever evaluated is appended here, so the
multiple-testing penalty counts honestly. File is committed."""
import json
from pathlib import Path

REG = Path("docs/trials.jsonl")


def log_trial(name: str, params: dict, note: str = "", reg: Path = REG) -> int:
    reg.parent.mkdir(parents=True, exist_ok=True)
    with reg.open("a") as f:
        f.write(json.dumps({"name": name, "params": params, "note": note}, sort_keys=True) + "\n")
    return count_trials(reg)


def count_trials(reg: Path = REG) -> int:
    return sum(1 for _ in reg.open()) if reg.exists() else 0
