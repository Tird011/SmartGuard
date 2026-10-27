"""Main window: live feed + review queue, with the audit console one click away."""
import logging
import os

from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                             QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from core import policy
from core.detector import Detector
from core.engine import EVENT_PASS, CheckpointEngine
from core.ocr_engine import DocumentOCR
from core.verification import Verifier
from database import db_manager as db
from hardware.serial_handler import get_serial_handler
from ui.audit_page import AuditPage
from ui.dialogs import ManualInputDialog, ScanDialog, VerifyDialog, button
from ui.workers import VideoWorker

log = logging.getLogger(__name__)


class QueueCard(QFrame):
    """One flagged student: snapshot + Confirm (verify) / Cancel (dismiss)."""
    confirm = pyqtSignal(int)
    cancel = pyqtSignal(int)

    def __init__(self, record: dict):
        super().__init__()
        self.setObjectName("card")
        self.rid = record["id"]
        photo = QLabel()
        photo.setAlignment(Qt.AlignCenter)
        photo.setFixedHeight(110)
        path = record["snapshot_path"]
        pm = QPixmap(path) if path and os.path.isfile(path) else QPixmap()
        if pm.isNull():
            photo.setText("No snapshot")
        else:
            photo.setPixmap(pm.scaled(210, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        caption = QLabel(f"{record['log_time']}\n{record['violation_type']}")
        caption.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(button("Confirm", "confirm", lambda: self.confirm.emit(self.rid)))
        row.addWidget(button("Cancel", "cancel", lambda: self.cancel.emit(self.rid)))
        lay = QVBoxLayout(self)
        lay.addWidget(photo)
        lay.addWidget(caption)
        lay.addLayout(row)

    def mousePressEvent(self, event):       # clicking the card itself opens the verification view
        self.confirm.emit(self.rid)


class MainWindow(QMainWindow):
    hardware_changed = pyqtSignal(str)

    def __init__(self, hardware=None, detector=None, start_camera=True):
        super().__init__()
        self.setWindowTitle("SmartGuard-Vision")
        self.resize(1280, 760)
        db.init_db()

        self.hw = hardware or get_serial_handler()
        self.detector = detector or Detector()
        self.detector.load()
        self.engine = CheckpointEngine(self.detector, self.hw)
        self.verifier = Verifier(self.hw)
        self.ocr = DocumentOCR()

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.stack.addWidget(self._main_page())
        self.audit = AuditPage(self.verifier)
        self.audit.back.connect(self._show_main)
        self.audit.changed.connect(self._flash)
        self.stack.addWidget(self.audit)
        self._status_bar()

        self.worker = VideoWorker(self.engine)
        self.worker.frame.connect(self._show_frame)
        self.worker.event.connect(self._on_event)
        self.worker.camera_state.connect(self._on_camera)
        self.refresh_queue()
        if start_camera:
            self.worker.start()

    # ------------------------------------------------------------------ layout
    def _main_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        self.video = QLabel("Starting camera...")
        self.video.setObjectName("video")
        self.video.setAlignment(Qt.AlignCenter)
        self.video.setMinimumSize(640, 360)
        self.video.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        bar = QHBoxLayout()
        bar.addWidget(button("Check Records", "", self._show_audit))
        bar.addWidget(button("Manual Entry", "", self._manual_new))
        bar.addStretch()
        left = QVBoxLayout()
        left.addWidget(self.video, 1)
        left.addLayout(bar)

        self.queue_title = QLabel()
        self.queue_box = QVBoxLayout()
        self.queue_box.setAlignment(Qt.AlignTop)
        holder = QWidget()
        holder.setLayout(self.queue_box)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        scroll.setFixedWidth(260)
        right = QVBoxLayout()
        right.addWidget(self.queue_title)
        right.addWidget(scroll, 1)

        lay = QHBoxLayout(page)
        lay.addLayout(left, 1)
        lay.addLayout(right)
        return page

    def _status_bar(self):
        self.profile_label, self.hw_label = QLabel(), QLabel()
        self.statusBar().addPermanentWidget(self.profile_label)
        self.statusBar().addPermanentWidget(self.hw_label)
        self.hardware_changed.connect(self._set_hw_label)   # handler thread -> UI thread
        self.hw.add_status_listener(self.hardware_changed.emit)
        self._set_hw_label(self.hw.state)
        self._update_profile()
        self.clock = QTimer(self)                           # the rules change at midnight
        self.clock.timeout.connect(self._update_profile)
        self.clock.start(60_000)
        if not self.detector.ready:
            self._flash(self.detector.error, 0)

    # ---------------------------------------------------------------- status
    def _flash(self, message: str, ms: int = 8000):
        self.statusBar().showMessage(message, ms)

    def _update_profile(self):
        self.profile_label.setText(f"Today: {policy.get_active_profile().name}")

    def _set_hw_label(self, state: str):
        self.hw_label.setText(f"Gate hardware: {state}")

    def _on_camera(self, ok: bool, message: str):
        if not ok:
            self.video.setText(message)
        self._flash(message)

    def _show_frame(self, image):
        self.video.setPixmap(QPixmap.fromImage(image).scaled(
            self.video.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _on_event(self, result):
        if result.event == EVENT_PASS:
            self._flash(f"Gate opened - {result.evaluation.message}", 4000)
        else:
            self._flash(f"Flagged: {result.evaluation.violation_type}", 6000)
            self.refresh_queue()

    # ----------------------------------------------------------------- queue
    def refresh_queue(self):
        while self.queue_box.count():
            self.queue_box.takeAt(0).widget().deleteLater()
        pending = db.fetch_pending()
        self.queue_title.setText(f"Review Queue ({len(pending)})")
        for rec in pending:
            card = QueueCard(rec)
            card.confirm.connect(self._verify)
            card.cancel.connect(self._dismiss)
            self.queue_box.addWidget(card)

    def _dismiss(self, record_id: int):
        ask = QMessageBox.question(self, "Dismiss alert", "Dismiss this alert as a false alarm?\n"
                                   "It will be removed from the records.")
        if ask == QMessageBox.Yes:
            db.delete_record(record_id)
            self.refresh_queue()

    def _verify(self, record_id: int):
        rec = db.get_record(record_id)
        if not rec:
            return self.refresh_queue()
        dlg = VerifyDialog(rec, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        if dlg.choice == "scan":
            self._scan(record_id)
        else:
            self._manual(record_id)

    def _scan(self, record_id: int):
        dlg = ScanDialog(self.worker, self.ocr, self)
        dlg.exec_()
        if dlg.outcome == "ok":
            self._flash(self.verifier.scan(record_id, dlg.result).message)
            self.refresh_queue()
        elif dlg.outcome == "manual":
            p = dlg.partial
            self._manual(record_id, p.first_name, p.last_name, p.student_number)

    def _manual(self, record_id: int, first="", last="", number=""):
        dlg = ManualInputDialog(self, first, last, number)
        if dlg.exec_() == QDialog.Accepted:
            self._flash(self.verifier.manual(record_id, *dlg.values()).message)
            self.refresh_queue()

    def _manual_new(self):
        dlg = ManualInputDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            self._flash(self.verifier.add_manual(*dlg.values()).message)

    # ------------------------------------------------------------ navigation
    def _show_audit(self):
        self.audit.refresh()
        self.stack.setCurrentIndex(1)

    def _show_main(self):
        self.refresh_queue()
        self.stack.setCurrentIndex(0)

    def closeEvent(self, event):
        self.worker.stop()
        self.hw.close()
        super().closeEvent(event)
