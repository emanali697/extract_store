"""
SQLite persistence for jobs — survives backend restarts.

Schema is intentionally simple: one row per job, JSON blobs for stages/results
so we don't have to keep the DB schema in sync with every field tweak.

The DB file lives at backend/state.db. Concurrent access is fine for our load
(low write rate, single uvicorn worker). If we ever scale out we should move
to Firestore or Postgres.
"""
from __future__ import annotations
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from config import BASE_DIR

DB_PATH = BASE_DIR / "state.db"

_lock = threading.Lock()


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,
    video_path    TEXT,
    street_name   TEXT,
    city          TEXT,
    district      TEXT,
    speed_mode    TEXT,
    enable_places INTEGER,
    enable_status INTEGER,
    status        TEXT,
    error         TEXT,
    output_dir    TEXT,
    stages_json   TEXT,
    results_json  TEXT,
    created_at    REAL,
    updated_at    REAL
);
"""


@contextmanager
def _conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.executescript(SCHEMA)


def upsert_job(job) -> None:
    """Persist a Job dataclass."""
    import time as _t
    with _lock, _conn() as c:
        c.execute(
            """
            INSERT INTO jobs(
                job_id, video_path, street_name, city, district,
                speed_mode, enable_places, enable_status,
                status, error, output_dir,
                stages_json, results_json, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET
                video_path   = excluded.video_path,
                street_name  = excluded.street_name,
                city         = excluded.city,
                district     = excluded.district,
                speed_mode   = excluded.speed_mode,
                enable_places= excluded.enable_places,
                enable_status= excluded.enable_status,
                status       = excluded.status,
                error        = excluded.error,
                output_dir   = excluded.output_dir,
                stages_json  = excluded.stages_json,
                results_json = excluded.results_json,
                updated_at   = excluded.updated_at
            """,
            (
                job.job_id, job.video_path, job.street_name, job.city, job.district,
                job.speed_mode, int(job.enable_places), int(job.enable_status),
                job.status, job.error, job.output_dir,
                json.dumps(job.stages, default=str),
                json.dumps(job.results, default=str) if job.results else None,
                getattr(job, "created_at", _t.time()), _t.time(),
            ),
        )


def load_all_jobs():
    """Return list of dicts ready to be hydrated into Job dataclasses."""
    with _conn() as c:
        rows = c.execute("SELECT * FROM jobs ORDER BY created_at").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["stages"] = json.loads(d.pop("stages_json") or "{}")
        # JSON object keys are strings — convert back to int for stages
        d["stages"] = {int(k): v for k, v in d["stages"].items()}
        rj = d.pop("results_json")
        d["results"] = json.loads(rj) if rj else None
        d["enable_places"] = bool(d.get("enable_places"))
        d["enable_status"] = bool(d.get("enable_status"))
        out.append(d)
    return out


def delete_job(job_id: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
