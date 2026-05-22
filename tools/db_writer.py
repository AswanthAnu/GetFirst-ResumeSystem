"""
db_writer.py — Layer 3 Tool: SQLite Read/Write

All DB operations for the applications table.
Never called directly by UI — only via navigation/pipeline.py.

Vercel Blob integration:
  - On Vercel, the DB lives in /tmp which is ephemeral.
  - _pull_db_from_blob() downloads the latest DB from Blob before reads.
  - _sync_db_to_blob() uploads the DB to Blob after every write.
  - Both functions are no-ops locally (no BLOB_READ_WRITE_TOKEN set).
"""

import sqlite3
import uuid
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ─── DB Path ──────────────────────────────────────────────────────────────────

if os.getenv("VERCEL"):
    DB_PATH = Path("/tmp") / "applications.db"
else:
    DB_PATH = Path(__file__).parent.parent / os.getenv("DB_PATH", "./applications.db").lstrip("./")

# ─── Vercel Blob DB Sync ──────────────────────────────────────────────────────

_LAST_PULL_TIME = 0.0
_PULL_INTERVAL = 10.0  # seconds — avoid hammering Blob on every request


def _pull_db_from_blob() -> None:
    """Download applications.db from Vercel Blob into /tmp (Vercel only)."""
    global _LAST_PULL_TIME
    if not os.getenv("VERCEL") or not os.getenv("BLOB_READ_WRITE_TOKEN"):
        return

    now = time.time()
    if now - _LAST_PULL_TIME < _PULL_INTERVAL:
        return  # Throttle: skip if pulled recently

    try:
        from vercel import blob
        res = blob.list_objects(prefix="db/applications.db")
        if res.blobs:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            blob.download_file(
                res.blobs[0].url,
                str(DB_PATH),
                access="private",
                overwrite=True,
            )
            print("DB: pulled applications.db from Vercel Blob.")
            _LAST_PULL_TIME = now
    except Exception as e:
        print(f"DB Warning: failed to pull from Vercel Blob: {e}")


def _sync_db_to_blob() -> None:
    """Upload applications.db to Vercel Blob (Vercel only, after every write)."""
    if not os.getenv("VERCEL") or not os.getenv("BLOB_READ_WRITE_TOKEN"):
        return
    try:
        from vercel import blob
        if DB_PATH.exists():
            with open(DB_PATH, "rb") as f:
                blob.put(
                    path="db/applications.db",
                    body=f,
                    access="private",
                    overwrite=True,
                )
            print("DB: backed up applications.db to Vercel Blob.")
    except Exception as e:
        print(f"DB Warning: failed to sync to Vercel Blob: {e}")


# ─── Schema ───────────────────────────────────────────────────────────────────

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
    _pull_db_from_blob()
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
    _sync_db_to_blob()


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

    _sync_db_to_blob()
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
        success = result.rowcount > 0

    if success:
        _sync_db_to_blob()
    return success
