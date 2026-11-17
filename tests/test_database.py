import pytest

from database import db_manager as db


@pytest.fixture
def path(tmp_path):
    p = str(tmp_path / "t.db")
    db.init_db(p)
    db.init_db(p)  # safe to repeat
    return p


def test_pending_record_has_blank_identity(path):
    rid = db.log_violation("No Lanyard", "a.jpg", log_date="2026-10-17", log_time="08:00:00", db_path=path)
    assert [r["id"] for r in db.fetch_pending(path)] == [rid]
    assert db.fetch_table_rows(db_path=path)[0] == (rid, "", "", "", "2026-10-17", "08:00:00", "Pending")


def test_resolve_sets_identity_and_status(path):
    rid = db.log_violation("No Lanyard", db_path=path)
    assert db.resolve_violation(rid, db.METHOD_SCAN, "2023-0001", "JUAN", "DELA CRUZ", path)
    row = db.get_record(rid, path)
    assert (row["first_name"], row["last_name"], row["verification_status"]) == ("Juan", "Dela Cruz", "Auto-Verified")
    assert db.fetch_pending(path) == []


def test_student_name_stored_once(path):
    a = db.add_manual_record("2023-0001", "juan", "dela cruz", db_path=path)
    b = db.add_manual_record("2023-0001", "Juan", "Dela Cruz", db_path=path)
    db.update_student("2023-0001", "Juan Carlos", "Dela Cruz", path)
    assert {r[2] for r in db.fetch_table_rows(db_path=path)} == {"Juan Carlos"}
    assert len(db.fetch_student_history("2023-0001", path)) == 2 and a != b


def test_filters_and_summary(path):
    db.log_violation("No Lanyard", log_date="2026-10-17", log_time="08:00:00", db_path=path)
    db.add_manual_record("2023-0002", "Maria", "Santos", db_path=path)
    assert len(db.fetch_table_rows(date_to="2026-10-17", db_path=path)) == 1
    assert len(db.fetch_table_rows(search="santos", db_path=path)) == 1
    s = db.fetch_summary(db_path=path)
    assert s["total"] == 2 and s["by_status"] == {"Pending": 1, "Manual Override": 1}


def test_rejects_bad_input(path):
    with pytest.raises(ValueError):
        db.resolve_violation(1, "bogus", "1", "a", "b", path)
    with pytest.raises(ValueError):
        db.add_manual_record("", "a", "b", db_path=path)


def test_expired_pending_records_are_purged_with_their_snapshot(path, tmp_path, monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(db.config, "SNAPSHOTS_DIR", str(tmp_path))
    snap = tmp_path / "old.jpg"
    snap.write_bytes(b"x")
    old = db.log_violation("No Lanyard", str(snap), log_date="2026-11-18", log_time="03:00:00", db_path=path)
    fresh = db.log_violation("No Lanyard", log_date="2026-11-18", log_time="05:30:00", db_path=path)
    done = db.log_violation("No Lanyard", log_date="2026-11-18", log_time="01:00:00", db_path=path)
    db.resolve_violation(done, db.METHOD_MANUAL, "2023-0003", "Ana", "Reyes", path)

    now = datetime(2026, 11, 18, 8, 15)                 # 'old' is 5 h 15 min old, 'fresh' 2 h 45 min
    assert db.purge_expired_pending(5, now=now, db_path=path) == 1
    ids = {r[0] for r in db.fetch_table_rows(db_path=path)}
    assert old not in ids and fresh in ids and done in ids   # verified records are never purged
    assert not snap.exists()
    assert db.purge_expired_pending(5, now=now, db_path=path) == 0


def test_report_rows_can_leave_out_pending(path):
    db.log_violation("No Lanyard", db_path=path)
    db.add_manual_record("2023-0004", "Lea", "Garcia", db_path=path)
    rows = db.fetch_report_rows(db_path=path, include_pending=False)
    assert [r["last_name"] for r in rows] == ["Garcia"]
    assert db.fetch_summary(db_path=path, include_pending=False)["total"] == 1
