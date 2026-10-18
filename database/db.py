"""SQLite database manager for SmartGuard-Vision.

Names are ALWAYS stored as separate first_name / last_name columns so they map
directly onto the audit table: LastName | FirstName | Student Number | Date | Time | Status.
A new connection is opened per call, so it is safe from both the UI and video threads.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, Iterator, List, Optional, Tuple

from core import config

STATUS_PENDING = "Pending"
STATUS_AUTO = "Auto-Verified"
STATUS_MANUAL = "Manual Override"
VALID_STATUSES = (STATUS_PENDING, STATUS_AUTO, STATUS_MANUAL)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS violations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL,
    student_id          TEXT NOT NULL DEFAULT '',
    first_name          TEXT NOT NULL DEFAULT '',
    last_name           TEXT NOT NULL DEFAULT '',
    violation_type      TEXT NOT NULL DEFAULT '',
    snapshot_path       TEXT NOT NULL DEFAULT '',
    verification_status TEXT NOT NULL DEFAULT 'Pending'
        CHECK (verification_status IN ('Pending', 'Auto-Verified', 'Manual Override'))
);
CREATE INDEX IF NOT EXISTS idx_violations_timestamp ON violations(timestamp);
CREATE INDEX IF NOT EXISTS idx_violations_status    ON violations(verification_status);
CREATE INDEX IF NOT EXISTS idx_violations_student   ON violations(student_id);
"""


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path or config.DATABASE_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _clean(value: Optional[str]) -> str:
    return (value or "").strip()


def _check_status(status: str) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid verification_status {status!r}; expected one of {VALID_STATUSES}")


# --------------------------------------------------------------------- setup
def init_db(db_path: Optional[str] = None) -> None:
    """Create the table and indexes if missing (safe to call on every launch)."""
    with _connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)


# -------------------------------------------------------------------- writes
def log_violation(violation_type: str,
                  snapshot_path: str = "",
                  student_id: str = "",
                  first_name: str = "",
                  last_name: str = "",
                  status: str = STATUS_PENDING,
                  timestamp: Optional[str] = None,
                  db_path: Optional[str] = None) -> int:
    """Insert a record and return its id.

    AI flags someone    -> log_violation("No Lanyard", snapshot_path=path)
    Guard types details -> log_violation("Manual Entry", student_id=..., first_name=...,
                                         last_name=..., status=STATUS_MANUAL)
    """
    _check_status(status)
    ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO violations (timestamp, student_id, first_name, last_name, "
            "violation_type, snapshot_path, verification_status) VALUES (?,?,?,?,?,?,?)",
            (ts, _clean(student_id), _clean(first_name).title(), _clean(last_name).title(),
             _clean(violation_type), snapshot_path or "", status),
        )
        return cur.lastrowid


def resolve_violation(violation_id: int, status: str, student_id: str,
                      first_name: str, last_name: str,
                      db_path: Optional[str] = None) -> bool:
    """Attach an identity to a queued record (Tier 2 OCR / Tier 3 manual). True if updated."""
    _check_status(status)
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE violations SET verification_status=?, student_id=?, first_name=?, last_name=? "
            "WHERE id=?",
            (status, _clean(student_id), _clean(first_name).title(), _clean(last_name).title(),
             violation_id),
        )
        return cur.rowcount > 0


def delete_violation(violation_id: int, db_path: Optional[str] = None) -> bool:
    with _connect(db_path) as conn:
        return conn.execute("DELETE FROM violations WHERE id=?", (violation_id,)).rowcount > 0


# --------------------------------------------------------------------- reads
def get_violation(violation_id: int, db_path: Optional[str] = None) -> Optional[Dict]:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM violations WHERE id=?", (violation_id,)).fetchone()
        return dict(row) if row else None


def fetch_pending(db_path: Optional[str] = None) -> List[Dict]:
    """Records waiting in the side queue, oldest first."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM violations WHERE verification_status=? ORDER BY id ASC",
            (STATUS_PENDING,),
        ).fetchall()
        return [dict(r) for r in rows]


def _filters(search: str, date_from: str, date_to: str):
    sql, args = "", []
    if date_from:
        sql += " AND substr(timestamp, 1, 10) >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND substr(timestamp, 1, 10) <= ?"
        args.append(date_to)
    if search.strip():
        sql += " AND (last_name LIKE ? OR first_name LIKE ? OR student_id LIKE ?)"
        args += [f"%{search.strip()}%"] * 3
    return sql, args


def fetch_table_rows(search: str = "", date_from: str = "", date_to: str = "",
                     db_path: Optional[str] = None) -> List[Tuple]:
    """Rows for the UI audit table, newest first.

    Tuple: (id, last_name, first_name, student_id, date, time, status)
    id is first so the UI can keep it as hidden row data for edit/delete.
    date_from / date_to are 'YYYY-MM-DD' (inclusive).
    """
    where, args = _filters(search, date_from, date_to)
    sql = ("SELECT id, last_name, first_name, student_id, "
           "substr(timestamp, 1, 10), substr(timestamp, 12, 8), verification_status "
           "FROM violations WHERE 1=1" + where + " ORDER BY timestamp DESC, id DESC")
    with _connect(db_path) as conn:
        return [tuple(r) for r in conn.execute(sql, args).fetchall()]


def fetch_all_for_export(search: str = "", date_from: str = "", date_to: str = "",
                         db_path: Optional[str] = None) -> List[Dict]:
    """Full records (incl. violation_type, snapshot_path) for PDF/Excel export."""
    where, args = _filters(search, date_from, date_to)
    sql = "SELECT * FROM violations WHERE 1=1" + where + " ORDER BY timestamp DESC, id DESC"
    with _connect(db_path) as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


if __name__ == "__main__":
    init_db()
    print(f"Database ready at {config.DATABASE_PATH}")