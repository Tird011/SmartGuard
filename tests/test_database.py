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
