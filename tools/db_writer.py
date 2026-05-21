"""
db_writer.py — Layer 3 Tool: SQLite Read/Write

All DB operations for the applications table.
Never called directly by UI — only via navigation/pipeline.py.
"""

import sqlite3
import uuid
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

if os.getenv("VERCEL"):
    DB_PATH = Path("/tmp") / "applications.db"
    _orig = Path(__file__).parent.parent / "applications.db"
    if _orig.exists() and not DB_PATH.exists():
        import shutil
        try:
            shutil.copy(str(_orig), str(DB_PATH))
        except Exception:
            pass
else:
    DB_PATH = Path(__file__).parent.parent / os.getenv("DB_PATH", "./applications.db").lstrip("./")

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS applications (
    id                  TEXT PRIMARY KEY,
    job_title           TEXT NOT NULL,
    company             TEXT NOT NULL,
    job_description_raw TEXT NOT NULL,
    cv_text_original    TEXT DEFAULT '',
    cv_latex_generated  TEXT NOT NULL,
    cover_letter_path   TEXT,
    applied_date        TEXT,
    key_changes_summary TEXT,
    status              TEXT DEFAULT 'confirmed',
    created_at          TEXT NOT NULL
)
"""


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the applications table if it doesn't exist. Idempotent."""
    with _get_conn() as conn:
        conn.execute(CREATE_TABLE_SQL)
        # Migration: add cv_text_original column if missing (added May 2026)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(applications)").fetchall()}
        if "cv_text_original" not in cols:
            conn.execute("ALTER TABLE applications ADD COLUMN cv_text_original TEXT DEFAULT ''")
        conn.commit()


def save_application(
    job_title: str,
    company: str,
    job_description_raw: str,
    cv_text_original: str,
    cv_latex_generated: str,
    cover_letter_path: Optional[str],
    key_changes_summary: list,
    applied_date: Optional[str] = None,
) -> str:
    """
    Insert a confirmed application record.
    Returns the generated UUID string.
    """
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    summary_json = json.dumps(key_changes_summary)

    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO applications
            (id, job_title, company, job_description_raw, cv_text_original,
             cv_latex_generated, cover_letter_path, applied_date,
             key_changes_summary, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id, job_title, company, job_description_raw,
                cv_text_original, cv_latex_generated, cover_letter_path,
                applied_date, summary_json, "confirmed", now
            )
        )
        conn.commit()

    return record_id


def get_all_applications() -> list[dict]:
    """
    Return all applications ordered by created_at DESC.
    Excludes cv_latex_generated (too large for list view).
    """
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, job_title, company, applied_date, status, created_at,
                   key_changes_summary, cover_letter_path
            FROM applications
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_application(record_id: str) -> Optional[dict]:
    """Return full application record by UUID, or None if not found."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM applications WHERE id = ?", (record_id,)
        ).fetchone()
    return dict(row) if row else None


def update_status(record_id: str, status: str) -> bool:
    """
    Update the status field of an application.
    Valid statuses: 'confirmed', 'applied'
    Returns True on success, False if record not found.
    """
    allowed = {"confirmed", "applied"}
    if status not in allowed:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {allowed}")

    with _get_conn() as conn:
        result = conn.execute(
            "UPDATE applications SET status = ? WHERE id = ?",
            (status, record_id)
        )
        conn.commit()
        return result.rowcount > 0
