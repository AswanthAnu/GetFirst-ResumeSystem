"""
test_db.py — Phase 2 Handshake: SQLite DB Connection Test

Run: python tools/test_db.py
Expected output: SQLite OK. DB initialized. Write/read/delete cycle passed.
"""

import sys
import os

# Fix Windows CP1252 encoding for Unicode output
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    print("❌ python-dotenv not installed. Run: pip install python-dotenv")
    sys.exit(1)

import sqlite3

DB_PATH = os.getenv("DB_PATH", "./applications.db")


def test_db() -> bool:
    db_path = Path(__file__).parent.parent / DB_PATH.lstrip("./")

    try:
        # Step 1: Create/connect
        print(f"   → Connecting to {db_path} ...")
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Step 2: Create table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id                  TEXT PRIMARY KEY,
                job_title           TEXT NOT NULL,
                company             TEXT NOT NULL,
                job_description_raw TEXT NOT NULL,
                cv_latex_generated  TEXT NOT NULL,
                cover_letter_path   TEXT,
                applied_date        TEXT,
                key_changes_summary TEXT,
                status              TEXT DEFAULT 'confirmed',
                created_at          TEXT NOT NULL
            )
        """)
        conn.commit()
        print("   → Table initialized ✓")

        # Step 3: Write a test record
        test_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO applications
            (id, job_title, company, job_description_raw, cv_latex_generated,
             cover_letter_path, applied_date, key_changes_summary, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            test_id, "__TEST__", "__TEST_COMPANY__",
            "test_jd", "test_latex", None, None,
            '["test change"]', "confirmed", now
        ))
        conn.commit()
        print("   → Test record written ✓")

        # Step 4: Read it back
        cursor.execute("SELECT id, job_title FROM applications WHERE id = ?", (test_id,))
        row = cursor.fetchone()
        assert row is not None, "Record not found after write"
        assert row[0] == test_id
        assert row[1] == "__TEST__"
        print("   → Test record read back ✓")

        # Step 5: Delete test record
        cursor.execute("DELETE FROM applications WHERE id = ?", (test_id,))
        conn.commit()
        print("   → Test record deleted ✓")

        conn.close()
        print(f"✅ SQLite OK. DB at: {db_path}")
        return True

    except AssertionError as e:
        print(f"❌ Data integrity failure: {e}")
        return False
    except sqlite3.Error as e:
        print(f"❌ SQLite error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("Phase 2 — SQLite DB Handshake Test")
    print("=" * 50)
    success = test_db()
    sys.exit(0 if success else 1)
