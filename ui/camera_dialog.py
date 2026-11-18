"""Camera Settings: list the cameras plugged into this PC and pick the one the checkpoint uses."""
from PyQt5.QtCore import QSize, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout

from core import camera, config
from ui.dialogs import button
from ui.workers import to_qimage


class CameraScan(QThread):
    """Testing each camera takes about a second, so it runs off the UI thread."""
    done = pyqtSignal(list)

    def __init__(self, in_use, current_frame, lister=camera.list_cameras):
        super().__init__()
        self.in_use, self.frame, self.lister = in_use, current_frame, lister

    def run(self):
        self.done.emit(self.lister(in_use=self.in_use, current_frame=self.frame))


class CameraDialog(QDialog):
    def __init__(self, worker, parent=None, lister=camera.list_cameras):
        super().__init__(parent)
        self.setWindowTitle("Camera Settings")
        self.setMinimumWidth(560)
        self.worker, self.lister = worker, lister
        self.chosen = None
        self._scan = None

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.list = QListWidget()
        self.list.setIconSize(QSize(160, 90))
        self.list.itemDoubleClicked.connect(lambda _: self._use())
        self.use_btn = button("Use This Camera", "confirm", self._use)
        self.refresh_btn = button("Refresh", "", self.refresh)
        row = QHBoxLayout()
        row.addWidget(self.refresh_btn)
        row.addStretch()
        row.addWidget(self.use_btn)
        row.addWidget(button("Cancel", "cancel", self.reject))
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Pick the camera that watches the gate. Plugged in a USB camera? Press Refresh."))
        lay.addWidget(self.list, 1)
        lay.addWidget(self.status)
        lay.addLayout(row)
        self.refresh()

    def refresh(self):
        if self._scan is not None:
            return
        self.list.clear()
        self.use_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.status.setText("Looking for cameras...")
        frame = None if self.worker.latest_raw is None else self.worker.latest_raw.copy()
        self._scan = CameraScan(self.worker.camera_index, frame, self.lister)
        self._scan.done.connect(self._show)
        self._scan.start()

    def _show(self, cams):
        self._scan = None
        self.refresh_btn.setEnabled(True)
        for cam in cams:
            item = QListWidgetItem(cam.label)
            item.setData(Qt.UserRole, cam.index)
            if cam.thumbnail is not None:
                item.setIcon(QIcon(QPixmap.fromImage(to_qimage(cam.thumbnail))))
            self.list.addItem(item)
            if cam.in_use:
                self.list.setCurrentItem(item)
        if not cams:
            self.status.setText("No camera found. Check the USB cable, then press Refresh.")
            return
        self.use_btn.setEnabled(True)
        if self.list.currentItem() is None:
            self.list.setCurrentRow(0)
        self.status.setText(f"Found {len(cams)} camera(s). Selected camera is saved for next time.")

    def _use(self):
        item = self.list.currentItem()
        if item is None:
            return
        self.chosen = item.data(Qt.UserRole)
        self.accept()

    def done(self, result):
        if self._scan is not None:              # let a running scan finish before closing
            self._scan.wait(10000)
        super().done(result)
