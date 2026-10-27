"""Tier 2: read a Student ID / Certificate of Registration with EasyOCR."""
import logging
import re
from dataclasses import dataclass
from typing import List

from core import config

log = logging.getLogger(__name__)

_NUMBER = re.compile(config.STUDENT_NUMBER_PATTERN)
_LAST = r"\b(?:last\s*name|surname|family\s*name)\b"
_FIRST = r"\b(?:first\s*name|given\s*name)\b"
# plain "Name" / "Student Name", but not "Last Name", "First Name", "Middle Name"
_FULL = r"(?<!last )(?<!first )(?<!given )(?<!middle )(?<!family )\bname\b"
_MAX_OCR_WIDTH = 1280


@dataclass
class OcrResult:
    student_number: str = ""
    first_name: str = ""
    last_name: str = ""
    raw_text: str = ""

    @property
    def success(self) -> bool:
        """Complete enough to log without a human re-typing anything."""
        return bool(self.student_number and self.first_name and self.last_name)


def _clean(text: str) -> str:
    return re.sub(r"[^A-Za-z.,'\- ]", "", text).strip(" ,.-")


def _value_after(lines: List[str], label: str) -> str:
    """Text after `label`, or the next line when the label sits alone (EasyOCR splits boxes)."""
    for i, line in enumerate(lines):
        m = re.search(label + r"[ \t]*[:\-]?[ \t]*(.*)", line, re.I)
        if not m:
            continue
        value = _clean(m.group(1))
        if not value and i + 1 < len(lines):
            value = _clean(lines[i + 1])
        if value:
            return value
    return ""


def parse_document_text(text: str) -> OcrResult:
    """Pull student number and name out of raw OCR text."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    result = OcrResult(raw_text=text)

    m = _NUMBER.search(text)
    if m:
        result.student_number = m.group(0).upper()

    last, first = _value_after(lines, _LAST), _value_after(lines, _FIRST)
    if not (last and first):
        full = _value_after(lines, _FULL)
        if "," in full:                                  # "DELA CRUZ, JUAN A."
            last, first = [p.strip() for p in full.split(",", 1)]
        elif full:                                       # "Juan Dela Cruz"
            parts = full.split()
            first, last = " ".join(parts[:-1]), parts[-1]
    result.first_name, result.last_name = first.title(), last.title()
    return result


class DocumentOCR:
    """EasyOCR loads slowly (and downloads models on first use), so it is created on demand."""

    def __init__(self):
        self._reader = None

    def read(self, image) -> OcrResult:
        """Never raises: any failure returns an empty result."""
        try:
            import cv2
            h, w = image.shape[:2]
            if w > _MAX_OCR_WIDTH:
                image = cv2.resize(image, (_MAX_OCR_WIDTH, int(h * _MAX_OCR_WIDTH / w)))
            if self._reader is None:
                import easyocr
                self._reader = easyocr.Reader(["en"], gpu=config.OCR_GPU)
            return parse_document_text("\n".join(self._reader.readtext(image, detail=0)))
        except Exception:
            log.exception("OCR failed")
            return OcrResult()
