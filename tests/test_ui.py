"""Offscreen UI test: real window, real engine and database, fake camera + fake detector."""
import time

import numpy as np
import pytest

pytest.importorskip("PyQt5")
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog

from core import config
from core.ocr_engine import OcrResult
from database import db_manager as db
from ui.audit_page import AuditPage
from ui.dialogs import ManualInputDialog, ScanDialog
from ui.main_window import MainWindow
from ui.styles import QSS


class FakeHW:
    state = "disabled"

    def __init__(self):
        self.calls = []

    def add_status_listener(self, fn):
        pass

    def grant_access(self):
        self.calls.append("grant")

    def deny_access(self):
        self.calls.append("deny")

    def close(self):
        pass


class FakeDetector:
    ready, error = True, ""

    def load(self):
        return True

    def detect(self, frame):
        return [{"label": "uniform", "conf": 0.95, "box": (100, 80, 300, 400)}]    # no lanyard


class FakeCap:
    frame = np.full((480, 640, 3), 60, np.uint8)

    def isOpened(self):
        return True

    def read(self):
        time.sleep(0.01)
        return True, self.frame.copy()

    def set(self, *args):
        pass

    def release(self):
        pass


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(QSS)
    return a


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SNAPSHOTS_DIR", str(tmp_path))
    db.init_db()
    for rec in db.fetch_table_rows():
        db.delete_record(rec[0])
    hw = FakeHW()
    w = MainWindow(hardware=hw, detector=FakeDetector(), start_camera=False)
    w.hw_calls = hw.calls
    yield w
    w.close()


def test_camera_to_queue_to_verified_to_audit(window):
    window.worker._open = lambda: FakeCap()
    window.worker.start()
    QTest.qWait(1500)
    window.worker.stop()

    assert not window.video.pixmap().isNull()                       # live feed reached the screen
    pending = db.fetch_pending()
    assert len(pending) == 1 and pending[0]["violation_type"] == "No Lanyard"
    assert window.queue_box.count() == 1 and "(1)" in window.queue_title.text()
    assert "deny" in window.hw_calls

    out = window.verifier.manual(pending[0]["id"], "Juan", "Dela Cruz", "2023-01234")
    assert out.ok
    window.refresh_queue()
    assert window.queue_box.count() == 0

    window._show_audit()
    t = window.audit.table
    assert t.rowCount() == 1 and t.item(0, 0).text() == "Dela Cruz" and t.item(0, 5).text() == "Manual Override"
    window.audit.search.setText("zzz")
    assert t.rowCount() == 0
    window.audit.search.setText("")
    window.audit.period.setCurrentIndex(1)
    assert t.rowCount() == 1
    window._show_main()
    assert window.stack.currentIndex() == 0


def test_manual_form_validates(app):
    dlg = ManualInputDialog()
    dlg._submit()
    assert dlg.result() != QDialog.Accepted and "required" in dlg.error.text()
    dlg.first.setText("Juan")
    dlg.last.setText("Dela Cruz")
    dlg.number.setText("2023-01234")
    dlg._submit()
    assert dlg.result() == QDialog.Accepted and dlg.values() == ("Juan", "Dela Cruz", "2023-01234")


class StubWorker:
    from PyQt5.QtCore import QObject, pyqtSignal
    latest_raw = np.zeros((100, 100, 3), np.uint8)

    class _Sig:
        def connect(self, f): pass
        def disconnect(self, f): pass
    frame = _Sig()


class StubOcr:
    def __init__(self, result):
        self.result = result

    def read(self, image):
        return self.result


def test_scan_dialog_accepts_complete_read_and_falls_back_on_partial(app):
    good = ScanDialog(StubWorker(), StubOcr(OcrResult("2023-01234", "Juan", "Dela Cruz")))
    good._tick()
    QTest.qWait(300)
    assert good.outcome == "ok" and good.result.last_name == "Dela Cruz"

    partial = ScanDialog(StubWorker(), StubOcr(OcrResult("2023-01234", "", "")))
    partial._tick()
    QTest.qWait(300)
    assert partial.outcome == "cancel" and partial.partial.student_number == "2023-01234"
    partial._manual()
    assert partial.outcome == "manual"


def test_audit_edit_and_add(app, window, monkeypatch):
    rid = db.log_violation("No Lanyard")
    page = window.audit
    monkeypatch.setattr(page, "_ask", lambda *a: ("Maria", "Santos", "2023-0002"))
    page._edit(rid)
    assert db.get_record(rid)["last_name"] == "Santos"
    page._add()
    assert len([r for r in db.fetch_table_rows() if r[1] == "Santos"]) == 2
