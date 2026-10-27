"""Right-side console: the audit table with Add new / Back to Main / Save A Copy."""
import logging
from datetime import date, timedelta

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
                             QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

from core import report
from database import db_manager as db
from ui.dialogs import ManualInputDialog, button

log = logging.getLogger(__name__)

COLUMNS = ["LastName", "FirstName", "Student Number", "Date", "Time", "Status"]
PERIODS = ["All dates", "Today", "Last 7 days", "This month"]


class AuditPage(QWidget):
    back = pyqtSignal()
    changed = pyqtSignal(str)       # message for the main window's status bar

    def __init__(self, verifier, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.verifier = verifier

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name, student number or violation")
        self.search.textChanged.connect(self.refresh)
        self.period = QComboBox()
        self.period.addItems(PERIODS)
        self.period.currentIndexChanged.connect(self.refresh)

        self.table = QTableWidget(0, len(COLUMNS) + 1)
        self.table.setHorizontalHeaderLabels(COLUMNS + [""])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.Stretch)
        head.setSectionResizeMode(len(COLUMNS), QHeaderView.ResizeToContents)

        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.period)
        bottom = QHBoxLayout()
        bottom.addWidget(button("Add new", "link", self._add))
        bottom.addStretch()
        bottom.addWidget(button("Back to Main", "pill", lambda: self.back.emit()))
        bottom.addStretch()
        bottom.addWidget(button("Save A Copy", "link", self._save_copy))
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        lay.addLayout(bottom)

    def _range(self):
        today, i = date.today(), self.period.currentIndex()
        if i == 1:
            return today.isoformat(), today.isoformat()
        if i == 2:
            return (today - timedelta(days=6)).isoformat(), today.isoformat()
        if i == 3:
            return today.replace(day=1).isoformat(), today.isoformat()
        return "", ""

    def refresh(self, *_):
        start, end = self._range()
        rows = db.fetch_table_rows(self.search.text(), start, end)
        self.table.setRowCount(len(rows))
        for r, (rid, last, first, number, day, clock, status) in enumerate(rows):
            for c, text in enumerate((last, first, number, day, clock, status)):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, item)
            self.table.setCellWidget(r, len(COLUMNS), button("Edit", "link", lambda _=False, i=rid: self._edit(i)))
        self.table.resizeRowsToContents()

    def _ask(self, first="", last="", number=""):
        dlg = ManualInputDialog(self, first, last, number)
        return dlg.values() if dlg.exec_() == dlg.Accepted else None

    def _add(self):
        values = self._ask()
        if values:
            self._report(self.verifier.add_manual(*values))

    def _edit(self, record_id: int):
        rec = db.get_record(record_id)
        if not rec:
            return self.refresh()
        values = self._ask(rec["first_name"], rec["last_name"], rec["student_id"])
        if values:
            self._report(self.verifier.edit(record_id, *values))

    def _report(self, outcome):
        if not outcome.ok:
            QMessageBox.warning(self, "Could not save", outcome.message)
        self.changed.emit(outcome.message)
        self.refresh()

    def _save_copy(self):
        path, chosen = QFileDialog.getSaveFileName(
            self, "Save A Copy", report.default_path("pdf"), "PDF (*.pdf);;Excel (*.xlsx)")
        if not path:
            return
        ext = ".xlsx" if "xlsx" in chosen else ".pdf"
        if not path.lower().endswith((".pdf", ".xlsx")):
            path += ext
        start, end = self._range()
        try:
            report.export(path, self.search.text().strip(), start, end, self.period.currentText())
        except Exception as exc:
            log.exception("Report export failed")
            QMessageBox.warning(self, "Could not save", f"{exc}\n\nIs the file open in another program?")
            return
        QMessageBox.information(self, "Saved", f"Record sheet saved to:\n{path}")
