"""SQLite database manager for SmartGuard-Vision (two tables).

students : one row per real person        (student_id, first_name, last_name)
records  : one row per checkpoint event   (date, time, violation, status, ...)

Names are ALWAYS separate first_name / last_name columns, and date and time are
separate columns, so everything maps 1:1 onto the audit table and the PDF sheet:
    LastName | FirstName | Student Number | Date | Time | Violation | Status

A new connection is opened per call, so it is safe from the UI and video threads.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, Iterator, List, Optional, Tuple

from core import config

STATUS_PENDING = "Pending"
STATUS_AUTO = "Auto-Verified"
STATUS_MANUAL = "Manual Override"

METHOD_AI = "AI"                 # flagged by the camera, identity not known yet
METHOD_SCAN = "ID/COR Scan"      # Tier 2: OCR
METHOD_MANUAL = "Manual"         # Tier 3: guard typed it in

_SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    student_id  TEXT PRIMARY KEY,
    first_name  TEXT NOT NULL,
    last_name   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id          TEXT REFERENCES students(student_id) ON UPDATE CASCADE,  -- NULL until identified
    log_date            TEXT NOT NULL,                                           -- YYYY-MM-DD
    log_time            TEXT NOT NULL,                                           -- HH:MM:SS
    violation_type      TEXT NOT NULL DEFAULT '',
    snapshot_path       TEXT NOT NULL DEFAULT '',
    verification_method TEXT NOT NULL DEFAULT 'AI'
        CHECK (verification_method IN ('AI', 'ID/COR Scan', 'Manual')),
    verification_status TEXT NOT NULL DEFAULT 'Pending'
        CHECK (verification_status IN ('Pending', 'Auto-Verified', 'Manual Override'))
);
CREATE INDEX IF NOT EXISTS idx_records_date    ON records(log_date, log_time);
CREATE INDEX IF NOT EXISTS idx_records_status  ON records(verification_status);
CREATE INDEX IF NOT EXISTS idx_records_student ON records(student_id);
CREATE INDEX IF NOT EXISTS idx_students_last   ON students(last_name, first_name);
"""

# Shared SELECT: LEFT JOIN so unidentified (Pending) records still appear with blank names.
_VIEW_SELECT = """
SELECT r.id,
       COALESCE(s.last_name, '')  AS last_name,
       COALESCE(s.first_name, '') AS first_name,
       COALESCE(r.student_id, '') AS student_id,
       r.log_date, r.log_time,
       r.violation_type, r.verification_method, r.verification_status
FROM records r
LEFT JOIN students s ON s.student_id = r.student_id
WHERE 1=1
"""


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path or config.DATABASE_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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


def _now() -> Tuple[str, str]:
    n = datetime.now()
    return n.strftime("%Y-%m-%d"), n.strftime("%H:%M:%S")


def _upsert_student(conn: sqlite3.Connection, student_id: str, first_name: str, last_name: str) -> str:
    student_id = _clean(student_id)
    first_name, last_name = _clean(first_name).title(), _clean(last_name).title()
    if not (student_id and first_name and last_name):
        raise ValueError("student_id, first_name and last_name are all required.")
    conn.execute(
        "INSERT INTO students (student_id, first_name, last_name) VALUES (?,?,?) "
        "ON CONFLICT(student_id) DO UPDATE SET first_name=excluded.first_name, "
        "last_name=excluded.last_name",
        (student_id, first_name, last_name),
    )
    return student_id


# --------------------------------------------------------------------- setup
def init_db(db_path: Optional[str] = None) -> None:
    """Create tables and indexes if missing (safe to call on every launch)."""
    with _connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)


# -------------------------------------------------------------------- writes
def log_violation(violation_type: str,
                  snapshot_path: str = "",
                  log_date: Optional[str] = None,
                  log_time: Optional[str] = None,
                  db_path: Optional[str] = None) -> int:
    """The camera flagged someone. Creates a Pending record with no identity yet.

    Date and time are stamped automatically. Returns the record id (the queue card id).
    """
    d, t = _now()
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO records (student_id, log_date, log_time, violation_type, snapshot_path, "
            "verification_method, verification_status) VALUES (NULL,?,?,?,?,?,?)",
            (log_date or d, log_time or t, _clean(violation_type), snapshot_path or "",
             METHOD_AI, STATUS_PENDING),
        )
        return cur.lastrowid


def resolve_violation(record_id: int, method: str, student_id: str,
                      first_name: str, last_name: str,
                      db_path: Optional[str] = None) -> bool:
    """Tier 2 (OCR) or Tier 3 (manual): attach an identity to a queued record.

    method must be METHOD_SCAN or METHOD_MANUAL; status is derived from it
    (scan -> Auto-Verified, manual -> Manual Override). True if a row was updated.
    """
    if method == METHOD_SCAN:
        status = STATUS_AUTO
    elif method == METHOD_MANUAL:
        status = STATUS_MANUAL
    else:
        raise ValueError("method must be METHOD_SCAN or METHOD_MANUAL")
    with _connect(db_path) as conn:
        sid = _upsert_student(conn, student_id, first_name, last_name)
        cur = conn.execute(
            "UPDATE records SET student_id=?, verification_method=?, verification_status=? WHERE id=?",
            (sid, method, status, record_id),
        )
        return cur.rowcount > 0


def add_manual_record(student_id: str, first_name: str, last_name: str,
                      violation_type: str = "Manual Entry",
                      db_path: Optional[str] = None) -> int:
    """'Add new' button: guard logs a student directly with no queued card."""
    d, t = _now()
    with _connect(db_path) as conn:
        sid = _upsert_student(conn, student_id, first_name, last_name)
        cur = conn.execute(
            "INSERT INTO records (student_id, log_date, log_time, violation_type, snapshot_path, "
            "verification_method, verification_status) VALUES (?,?,?,?,?,?,?)",
            (sid, d, t, _clean(violation_type), "", METHOD_MANUAL, STATUS_MANUAL),
        )
        return cur.lastrowid


def update_student(student_id: str, first_name: str, last_name: str,
                   db_path: Optional[str] = None) -> bool:
    """Fix a name typo once; every record for that student reflects it."""
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE students SET first_name=?, last_name=? WHERE student_id=?",
            (_clean(first_name).title(), _clean(last_name).title(), _clean(student_id)),
        )
        return cur.rowcount > 0


def delete_record(record_id: int, db_path: Optional[str] = None) -> bool:
    with _connect(db_path) as conn:
        return conn.execute("DELETE FROM records WHERE id=?", (record_id,)).rowcount > 0


# --------------------------------------------------------------------- reads
def get_record(record_id: int, db_path: Optional[str] = None) -> Optional[Dict]:
    with _connect(db_path) as conn:
        row = conn.execute(_VIEW_SELECT + " AND r.id=?", (record_id,)).fetchone()
        if not row:
            return None
        rec = dict(row)
        rec["snapshot_path"] = conn.execute(
            "SELECT snapshot_path FROM records WHERE id=?", (record_id,)).fetchone()[0]
        return rec


def fetch_pending(db_path: Optional[str] = None) -> List[Dict]:
    """Side-queue cards waiting for a guard, oldest first."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, log_date, log_time, violation_type, snapshot_path FROM records "
            "WHERE verification_status=? ORDER BY id ASC", (STATUS_PENDING,)).fetchall()
        return [dict(r) for r in rows]


def _filters(search: str, date_from: str, date_to: str) -> Tuple[str, list]:
    sql, args = "", []
    if date_from:
        sql += " AND r.log_date >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND r.log_date <= ?"
        args.append(date_to)
    if _clean(search):
        sql += (" AND (s.last_name LIKE ? OR s.first_name LIKE ? OR r.student_id LIKE ?"
                " OR r.violation_type LIKE ?)")
        args += [f"%{_clean(search)}%"] * 4
    return sql, args


_ORDER = " ORDER BY r.log_date DESC, r.log_time DESC, r.id DESC"


def fetch_table_rows(search: str = "", date_from: str = "", date_to: str = "",
                     db_path: Optional[str] = None) -> List[Tuple]:
    """Rows for the UI audit table, newest first.

    Tuple: (id, last_name, first_name, student_id, date, time, status)
    id is first so the UI can keep it as hidden row data for edit/delete.
    """
    where, args = _filters(search, date_from, date_to)
    with _connect(db_path) as conn:
        rows = conn.execute(_VIEW_SELECT + where + _ORDER, args).fetchall()
        return [(r["id"], r["last_name"], r["first_name"], r["student_id"],
                 r["log_date"], r["log_time"], r["verification_status"]) for r in rows]


def fetch_report_rows(search: str = "", date_from: str = "", date_to: str = "",
                      db_path: Optional[str] = None) -> List[Dict]:
    """Full rows for the PDF record sheet (adds violation + method). Newest first."""
    where, args = _filters(search, date_from, date_to)
    with _connect(db_path) as conn:
        return [dict(r) for r in conn.execute(_VIEW_SELECT + where + _ORDER, args).fetchall()]


def fetch_summary(date_from: str = "", date_to: str = "",
                  db_path: Optional[str] = None) -> Dict:
    """Counts for the PDF header: total, by status, by violation type."""
    where, args = _filters("", date_from, date_to)
    base = "FROM records r LEFT JOIN students s ON s.student_id = r.student_id WHERE 1=1" + where
    with _connect(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) " + base, args).fetchone()[0]
        by_status = {r[0]: r[1] for r in conn.execute(
            "SELECT r.verification_status, COUNT(*) " + base + " GROUP BY 1", args)}
        by_type = {r[0] or "(none)": r[1] for r in conn.execute(
            "SELECT r.violation_type, COUNT(*) " + base + " GROUP BY 1 ORDER BY 2 DESC", args)}
    return {"total": total, "by_status": by_status, "by_violation": by_type}


def fetch_student_history(student_id: str, db_path: Optional[str] = None) -> List[Dict]:
    """Every record for one student (useful for repeat-offender checks)."""
    with _connect(db_path) as conn:
        return [dict(r) for r in conn.execute(
            _VIEW_SELECT + " AND r.student_id=?" + _ORDER, (_clean(student_id),)).fetchall()]


if __name__ == "__main__":
    init_db()
    print(f"Database ready at {config.DATABASE_PATH}")
