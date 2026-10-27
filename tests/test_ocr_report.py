import pytest

from core import report
from core.ocr_engine import parse_document_text
from database import db_manager as db

# Invented people; the layouts and number format follow the school's two ID designs.
TEMPORARY_ID = "\n".join([
    "KOLEHIYO NG LUNSOD NG LIPA", "MARAWOY, LIPA CITY BATANGAS", "BSCS", "A.Y. 2026 - 2027",
    "FIRST SEMESTER", "TEMPORARY ID", "04141-24-0001", "STUDENT NUMBER",
    "SANTOS, MARIA CLARA D.", "FULL NAME", "Student's Signature"])
STANDARD_ID = "\n".join([
    "KOLEHIYO NG LUNGSOD NG LIPA", "A.Y. 2026-2027", "First Semester",
    "REYES, JUAN P.", "04141-24-0002", "COLLEGE OF COMPUTER STUDIES"])


def fields(text):
    r = parse_document_text(text)
    return r.last_name, r.first_name, r.student_number


def test_temporary_id_layout():
    assert fields(TEMPORARY_ID) == ("Santos", "Maria Clara", "04141-24-0001")
    assert parse_document_text(TEMPORARY_ID).success


def test_standard_id_layout_ignores_academic_year():
    assert fields(STANDARD_ID) == ("Reyes", "Juan", "04141-24-0002")


def test_ocr_separator_noise_and_multiword_surname():
    r = parse_document_text("DE LA CRUZ, ANA MAE S.\n04141 24 0003")
    assert (r.last_name, r.first_name, r.student_number) == ("De La Cruz", "Ana Mae", "04141-24-0003")


def test_labelled_documents_still_work():
    assert fields("Student Name: DELA CRUZ, JUAN\nID No 04141-24-0004") == ("Dela Cruz", "Juan", "04141-24-0004")
    assert fields("Last Name\nSANTOS\nFirst Name\nMARIA\nStudent No.\n04141-24-0005") == ("Santos", "Maria", "04141-24-0005")
    assert fields("Name: Juan Dela Cruz\n04141-24-0006")[:2] == ("Cruz", "Juan Dela")


def test_partial_and_noise_never_count_as_success():
    partial = parse_document_text("Some school header\nID 04141-24-0007")
    assert not partial.success and partial.student_number == "04141-24-0007"
    assert parse_document_text("A.Y. 2026-2027\nValid until 2026-10-27").student_number == ""
    assert not parse_document_text("FULL NAME\nStudent's Signature").success


@pytest.fixture
def path(tmp_path):
    p = str(tmp_path / "t.db")
    db.init_db(p)
    db.add_manual_record("04141-24-0001", "Juan", "Dela Cruz & Sons <b>", "Improper Attire", p)
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
