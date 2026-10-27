import pytest

from core import report
from core.ocr_engine import parse_document_text
from database import db_manager as db


def test_ocr_full_name_line():
    r = parse_document_text("Student Name: DELA CRUZ, JUAN\nID No 2023-01234")
    assert r.success and (r.last_name, r.first_name, r.student_number) == ("Dela Cruz", "Juan", "2023-01234")


def test_ocr_labels_on_separate_lines():
    r = parse_document_text("Republic\nLast Name\nSANTOS\nFirst Name\nMARIA\nStudent No.\n21-0123-456")
    assert r.success and (r.last_name, r.first_name, r.student_number) == ("Santos", "Maria", "21-0123-456")


def test_ocr_western_order_and_partial():
    assert parse_document_text("Name: Juan Dela Cruz\n2023-01234").last_name == "Cruz"
    partial = parse_document_text("Some school header\nID 2023-01234")
    assert not partial.success and partial.student_number == "2023-01234"


def test_ocr_ignores_dates_and_noise():
    assert parse_document_text("Valid until 2026-10-27").student_number == ""


@pytest.fixture
def path(tmp_path):
    p = str(tmp_path / "t.db")
    db.init_db(p)
    db.add_manual_record("2023-0001", "Juan", "Dela Cruz & Sons <b>", "Improper Attire", p)
    db.log_violation("No Lanyard", db_path=p)
    return p


def test_pdf_and_excel_export(tmp_path, path):
    pdf = report.export(str(tmp_path / "a.pdf"), search="juan", period="Today", db_path=path)
    assert open(pdf, "rb").read(5) == b"%PDF-"
    empty = report.export(str(tmp_path / "b.pdf"), search="nobody <x>", db_path=path)
    assert open(empty, "rb").read(5) == b"%PDF-"

    from openpyxl import load_workbook
    rows = list(load_workbook(report.export(str(tmp_path / "c.xlsx"), db_path=path)).active.values)
    assert rows[0][0] == "Last Name" and len(rows) == 3
