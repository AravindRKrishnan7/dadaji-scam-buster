"""SQLite storage for case files and their complaints.

One row per call. The whole case file is stored as JSON, so adding a field to CaseFile
needs no database change. A few columns are copied out of it so they can be queried.
sqlite3 comes with Python: the database is just a file, with no server to run.
"""
import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from backend import config
from backend.case_file import CaseFile

SCHEMA = """CREATE TABLE IF NOT EXISTS cases (
    session_id  TEXT PRIMARY KEY,
    persona     TEXT NOT NULL,
    started_at  REAL NOT NULL,
    ended_at    REAL,
    turns       INTEGER NOT NULL,
    scam_type   TEXT,
    risk_score  INTEGER,
    case_json   TEXT NOT NULL,
    report_json TEXT
)"""

# Insert, or update the row if this call is already saved. A missing report keeps the old one.
UPSERT = """INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(session_id) DO UPDATE SET
    ended_at = excluded.ended_at, turns = excluded.turns, scam_type = excluded.scam_type,
    risk_score = excluded.risk_score, case_json = excluded.case_json,
    report_json = COALESCE(excluded.report_json, cases.report_json)"""


def _connect() -> sqlite3.Connection:
    path = Path(config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    return conn


def save_sync(case: CaseFile, report: dict | None = None):
    with closing(_connect()) as conn, conn:  # the inner "with conn" commits
        conn.execute(UPSERT, (case.session_id, case.persona, case.started_at, case.ended_at,
                              case.turns, case.scam_type, case.risk_score, case.model_dump_json(),
                              json.dumps(report) if report else None))


def load_sync(session_id: str) -> tuple[CaseFile, dict | None] | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT case_json, report_json FROM cases WHERE session_id = ?",
                           (session_id,)).fetchone()
    if row is None:
        return None
    return CaseFile.model_validate_json(row[0]), json.loads(row[1]) if row[1] else None


def stats_sync() -> dict:
    """Ended calls where the scammer said something, and the total time Dadaji kept them busy."""
    with closing(_connect()) as conn:
        calls, seconds = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(ended_at - started_at), 0) FROM cases"
            " WHERE ended_at IS NOT NULL AND turns > 0").fetchone()
    return {"calls": calls, "seconds": round(seconds)}


# sqlite3 blocks while it reads or writes the file. Running it in a worker thread keeps the
# server free to handle other requests (and WebSocket pushes) meanwhile.
async def save(case: CaseFile, report: dict | None = None):
    await asyncio.to_thread(save_sync, case, report)


async def load(session_id: str) -> tuple[CaseFile, dict | None] | None:
    return await asyncio.to_thread(load_sync, session_id)


async def stats() -> dict:
    return await asyncio.to_thread(stats_sync)
