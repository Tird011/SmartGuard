"""Tier 2 / Tier 3: turn a flagged (Pending) record into an identified student."""
import re
from typing import List, NamedTuple, Optional

from core import config
from core.ocr_engine import OcrResult
from database import db_manager as db

_NUMBER_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]*$")


class Outcome(NamedTuple):
    ok: bool
    message: str


def validate(first: str, last: str, number: str) -> List[str]:
    """Error messages for the manual form (empty list = valid)."""
    errors = []
    for label, value in (("First name", first), ("Last name", last)):
        value = value.strip()
        if not value:
            errors.append(f"{label} is required.")
        elif len(value) > 60 or any(ch.isdigit() for ch in value):
            errors.append(f"{label} must be text only (max 60 characters).")
    number = number.strip()
    if not number:
        errors.append("Student number is required.")
    elif len(number) > 20 or not _NUMBER_OK.match(number):
        errors.append("Student number may only contain letters, digits and hyphens.")
    return errors


class Verifier:
    def __init__(self, hardware, db_path: Optional[str] = None):
        self.hw = hardware
        self.db_path = db_path

    def _resolve(self, record_id: int, method: str, first: str, last: str,
                 number: str, open_gate: bool) -> Outcome:
        errors = validate(first, last, number)
        if errors:
            return Outcome(False, " ".join(errors))
        number = number.strip().upper()
        if not db.resolve_violation(record_id, method, number, first, last, self.db_path):
            return Outcome(False, "That record no longer exists.")
        if open_gate and config.OPEN_GATE_ON_VERIFY:
            self.hw.grant_access()
        return Outcome(True, f"Verified: {last.strip().title()}, {first.strip().title()} ({number})")

    def scan(self, record_id: int, ocr: OcrResult) -> Outcome:
        """Tier 2: identity read from an ID / COR."""
        return self._resolve(record_id, db.METHOD_SCAN, ocr.first_name, ocr.last_name,
                             ocr.student_number, open_gate=True)

    def manual(self, record_id: int, first: str, last: str, number: str) -> Outcome:
        """Tier 3: guard typed the identity for a queued card."""
        return self._resolve(record_id, db.METHOD_MANUAL, first, last, number, open_gate=True)

    def edit(self, record_id: int, first: str, last: str, number: str) -> Outcome:
        """Correct an existing audit row (never touches the gate)."""
        return self._resolve(record_id, db.METHOD_MANUAL, first, last, number, open_gate=False)

    def add_manual(self, first: str, last: str, number: str) -> Outcome:
        """'Add new' in the audit console: log a student with no queued card."""
        errors = validate(first, last, number)
        if errors:
            return Outcome(False, " ".join(errors))
        db.add_manual_record(number.strip().upper(), first, last, db_path=self.db_path)
        return Outcome(True, "Record added.")
