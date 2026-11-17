"""SQLite ledger: immutable setup records, lifecycle events, alerts (with latency), cycles. One run_id throughout."""
import json, sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS setups(run_id TEXT PRIMARY KEY, created_at TEXT, expires_at TEXT, pair TEXT, type TEXT, tf TEXT,
  day TEXT, record TEXT);
CREATE TABLE IF NOT EXISTS events(run_id TEXT, idx INTEGER, ts TEXT, frm TEXT, to_state TEXT, detail TEXT, PRIMARY KEY(run_id, idx));
CREATE TABLE IF NOT EXISTS alerts(run_id TEXT, idx INTEGER, kind TEXT, event_ts TEXT, sent_at TEXT, latency_s REAL, late INTEGER,
  ok INTEGER, text TEXT, PRIMARY KEY(run_id, idx));
CREATE TABLE IF NOT EXISTS outcomes(run_id TEXT PRIMARY KEY, reason TEXT, net_r REAL, fill REAL, exit REAL, resolved_at TEXT);
CREATE TABLE IF NOT EXISTS cycles(ts TEXT, ok INTEGER, status TEXT, data_age_min REAL, duration_s REAL, note TEXT);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
"""


def connect(path="data/engine.db"):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    have = {r[1] for r in c.execute("PRAGMA table_info(outcomes)")}
    for col in ("gross_r", "mfe_r", "mae_r"):                    # diagnostics added later: migrate in place, never lose rows
        if col not in have:
            c.execute(f"ALTER TABLE outcomes ADD COLUMN {col} REAL")
    c.commit()
    return c


def kv_get(c, k, default=None):
    r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def kv_set(c, k, v):
    c.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, str(v)))
    c.commit()


def add_setup(c, run_id, rec: dict) -> bool:
    """Insert once; the record is never updated (immutable). Returns False if it already existed."""
    try:
        c.execute("INSERT INTO setups VALUES(?,?,?,?,?,?,?,?)", (run_id, rec["created"], rec["expires"], rec["pair"],
                  rec["type"], rec["tf"], rec["created"][:10], json.dumps(rec, sort_keys=True)))
        c.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def active_setups(c):
    return [json.loads(r["record"]) | {"run_id": r["run_id"]} for r in c.execute(
        "SELECT run_id, record FROM setups WHERE run_id NOT IN (SELECT run_id FROM outcomes) ORDER BY created_at")]
