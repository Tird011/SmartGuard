"""Pop-up views: Input Data form (Tier 3), verification view for a queued card, and the
'Scan With the camera' view (Tier 2)."""
import os

import cv2
from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QSizePolicy, QVBoxLayout)

from core import config
from core.ocr_engine import OcrResult
from core.verification import validate
from ui.styles import SCAN_QSS
from ui.workers import OcrWorker

_running_ocr = set()    # keeps a still-running OCR thread alive after its dialog closed
# Cards sit sideways in some holders (the temporary ID), so each attempt reads a different turn.
_TURNS = (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE)


def button(text: str, name: str = "", slot=None) -> QPushButton:
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    if slot:
        b.clicked.connect(slot)
    return b


class ManualInputDialog(QDialog):
    """'Input Data': First Name / Last Name / Student Number with Confirm / Cancel."""

    def __init__(self, parent=None, first="", last="", number=""):
        super().__init__(parent)
        self.setWindowTitle("Input Data")
        self.setMinimumWidth(380)
        self.first, self.last, self.number = QLineEdit(first), QLineEdit(last), QLineEdit(number)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        title = QLabel("Input Data")
        title.setObjectName("heading")
        title.setAlignment(Qt.AlignCenter)
        form = QFormLayout()
        form.addRow("First Name", self.first)
        form.addRow("Last Name", self.last)
        form.addRow("Student Number", self.number)
        confirm = button("Confirm", "confirm", self._submit)
        confirm.setDefault(True)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(confirm)
        row.addWidget(button("Cancel", "cancel", self.reject))
        lay = QVBoxLayout(self)
        lay.addWidget(title)
        lay.addLayout(form)
        lay.addWidget(self.error)
        lay.addLayout(row)

    def values(self):
        return tuple(w.text().strip() for w in (self.first, self.last, self.number))

    def _submit(self):
        errors = validate(*self.values())
        if errors:
            self.error.setText(" ".join(errors))
        else:
            self.accept()


class VerifyDialog(QDialog):
    """Opened from a queue card: shows the snapshot and lets the guard pick Tier 2 or Tier 3."""

    def __init__(self, record: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Verify student")
        self.choice = ""
        photo = QLabel()
        photo.setAlignment(Qt.AlignCenter)
        photo.setMinimumSize(420, 300)
        path = record.get("snapshot_path", "")
        pm = QPixmap(path) if path and os.path.isfile(path) else QPixmap()
        if pm.isNull():
            photo.setText("No snapshot")
        else:
            photo.setPixmap(pm.scaled(QSize(520, 380), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        info = QLabel(f"{record['violation_type']}\n{record['log_date']}  {record['log_time']}")
        info.setAlignment(Qt.AlignCenter)
        row = QHBoxLayout()
        row.addWidget(button("Scan ID / COR", "confirm", lambda: self._pick("scan")))
        row.addWidget(button("Manual Entry", "", lambda: self._pick("manual")))
        row.addWidget(button("Close", "cancel", self.reject))
        lay = QVBoxLayout(self)
        lay.addWidget(photo)
        lay.addWidget(info)
        lay.addLayout(row)

    def _pick(self, choice: str):
        self.choice = choice
        self.accept()


class ScanDialog(QDialog):
    """'Scan With the camera': shows the live feed and reads the document on its own.

    outcome: "ok" (result is complete) | "manual" (guard gave up; `partial` has whatever
    was read, to pre-fill the form) | "cancel".
    """

    def __init__(self, worker, ocr, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scan ID / COR")
        self.setStyleSheet(SCAN_QSS)
        self.setMinimumSize(760, 560)
        self.worker, self.ocr = worker, ocr
        self.outcome, self.result, self.partial = "cancel", None, OcrResult()
        self._thread = None
        self._attempt = 0

        self.view = QLabel()
        self.view.setObjectName("video")
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        title = QLabel("Scan With the camera")
        title.setObjectName("heading")
        title.setAlignment(Qt.AlignCenter)
        self.status = QLabel("Hold the ID or COR flat in front of the camera.")
        self.status.setAlignment(Qt.AlignCenter)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button("Manual Entry", "", self._manual))
        row.addWidget(button("Cancel", "cancel", self.reject))
        row.addStretch()
        lay = QVBoxLayout(self)
        lay.addWidget(self.view, 1)
        lay.addWidget(title)
        lay.addWidget(self.status)
        lay.addLayout(row)

        worker.frame.connect(self._show)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(config.SCAN_INTERVAL_MS)

    def _show(self, image):
        self.view.setPixmap(QPixmap.fromImage(image).scaled(
            self.view.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _tick(self):
        if self._thread is not None:
            return                                   # previous read still running
        raw = self.worker.latest_raw
        if raw is None:
            self.status.setText("Waiting for the camera...")
            return
        self.status.setText("Reading document...")
        image, turn = raw.copy(), _TURNS[self._attempt % len(_TURNS)]
        self._attempt += 1
        if turn is not None:
            image = cv2.rotate(image, turn)
        t = self._thread = OcrWorker(self.ocr, image)
        _running_ocr.add(t)             # must outlive its own run(), even if this dialog closes first
        t.finished.connect(lambda t=t: _running_ocr.discard(t))
        t.done.connect(self._on_result)
        t.start()

    def _on_result(self, res: OcrResult):
        self._thread = None
        for field in ("student_number", "first_name", "last_name"):
            if getattr(res, field) and not getattr(self.partial, field):
                setattr(self.partial, field, getattr(res, field))
        if res.success:
            self.result, self.outcome = res, "ok"
            self.accept()
        else:
            self.status.setText("Could not read it all. Hold the document steady, or use Manual Entry.")

    def _manual(self):
        self.outcome = "manual"
        self.reject()

    def done(self, code):
        self.timer.stop()
        try:
            self.worker.frame.disconnect(self._show)
        except TypeError:
            pass
        if self._thread is not None:
            try:
                self._thread.done.disconnect(self._on_result)
            except TypeError:
                pass
            self._thread = None
        super().done(code)
