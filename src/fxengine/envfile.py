"""Tiny .env reader (no extra dependency). Secrets live only in .env (gitignored)."""
from pathlib import Path


def load_env(path=".env") -> dict:
    out = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out
