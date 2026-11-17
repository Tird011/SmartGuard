"""Plate-reader style OCR pipeline: line rebuilding, OCR-error tolerant parsing, frame voting.
All names and numbers are invented; the layouts copy the school's ID and COR."""
from core.ocr_engine import OcrResult, ScanVoter, find_student_number, group_lines, parse_document_text


def box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def test_boxes_become_reading_order_lines_and_columns_stay_apart():
    # COR top: label, name split over two boxes, and the date column on the same height
    boxes = [(box(150, 227, 200, 245), "Nama:", 0.56),
             (box(380, 236, 450, 250), "TORRES", 0.90),
             (box(200, 231, 375, 247), "SANTOS JOSE MIGUEL Ili", 0.78),
             (box(690, 229, 720, 245), "Dato", 0.64),
             (box(150, 209, 230, 225), "Studont No:", 0.69),
             (box(235, 211, 330, 227), "04141-24-0011", 0.84)]
    lines, confs = group_lines(boxes)
    assert lines == ["Studont No: 04141-24-0011", "Nama: SANTOS JOSE MIGUEL Ili TORRES", "Dato"]
    assert confs[1] == 0.56


def test_cor_with_lost_comma_misspelled_label_and_misread_suffix():
    text = "CERTIFICATE OF REGISTRATION\nStudont No: 04141-24-0011\nNama: SANTOS JOSE MIGUEL Ili TORRES"
    r = parse_document_text(text)
    assert (r.last_name, r.first_name, r.student_number) == ("Santos", "Jose Miguel", "04141-24-0011")
    assert r.success and r.doc_type == "cor"


def test_cor_particle_surname_without_comma():
    r = parse_document_text("ENROLLED\nName: DELA CRUZ ANA JR REYES\n04141-24-0012")
    assert (r.last_name, r.first_name) == ("Dela Cruz", "Ana")


def test_id_semicolon_and_colon_misreads():
    r = parse_document_text("A,Y 2026-2027\nFirst Semester\nGARCIA; LEA MAE R:\n04141-24-0013")
    assert (r.last_name, r.first_name, r.student_number) == ("Garcia", "Lea Mae", "04141-24-0013")
    assert r.success


def test_id_comma_lost_is_read_but_needs_the_guard():
    r = parse_document_text("KOLEHIYO NG LUNGSOD NG LIPA\nGARCIA LEA MAE R.\n04141-24-0013")
    assert (r.last_name, r.first_name) == ("Garcia", "Lea Mae") and r.review and not r.success


def test_letters_read_for_digits_are_repaired_but_noise_is_not_a_number():
    assert find_student_number("04l41-24-O013") == "04141-24-0013"
    assert find_student_number("04141 - 24 - 0013") == "04141-24-0013"
    assert find_student_number("OOOOO-OO-OOOO") == ""            # no real digits at all
    assert find_student_number("A.Y. 2026-2027") == ""


def test_voter_needs_two_agreeing_frames_or_one_confident_frame():
    low = OcrResult("04141-24-0013", "Lea Mae", "Garcia", confidence=0.4)
    v = ScanVoter(accept_confidence=0.6)
    assert v.add(low) is None
    assert v.add(low).student_number == "04141-24-0013"
    sure = ScanVoter(accept_confidence=0.6)
    assert sure.add(OcrResult("04141-24-0013", "Lea Mae", "Garcia", confidence=0.9)) is not None


def test_voter_outvotes_a_misread_and_never_confirms_a_review_name():
    v = ScanVoter(accept_confidence=0.6)
    v.add(OcrResult("04141-24-0013", "Lea Mae", "Miendoza", confidence=0.3))
    v.add(OcrResult("04141-24-0013", "Lea Mae", "Mendoza", confidence=0.3))
    assert v.add(OcrResult("04141-24-0013", "Lea Mae", "Mendoza", confidence=0.3)).last_name == "Mendoza"
    r = ScanVoter(accept_confidence=0.6)
    for _ in range(4):
        assert r.add(OcrResult("04141-24-0013", "Lea Mae", "Garcia", review=True, confidence=0.9)) is None
    assert r.best.review and r.best.student_number == "04141-24-0013"
