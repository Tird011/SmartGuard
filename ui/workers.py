"""Background threads: camera + engine loop, and OCR (so the window never freezes)."""
import logging
import sys
import time

import cv2
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

from core import config

log = logging.getLogger(__name__)

_DISPLAY_WIDTH = 960     # frames are shrunk before they cross to the UI thread
_MIN_EMIT_GAP = 0.033    # ~30 fps cap on what the UI has to paint


def to_qimage(bgr) -> QImage:
    h, w = bgr.shape[:2]
    if w > _DISPLAY_WIDTH:
        bgr = cv2.resize(bgr, (_DISPLAY_WIDTH, int(h * _DISPLAY_WIDTH / w)))
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()


class VideoWorker(QThread):
    frame = pyqtSignal(QImage)      # annotated frame for display
    event = pyqtSignal(object)      # FrameResult with event "pass" or "flag"
    camera_state = pyqtSignal(bool, str)

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.latest_raw = None      # newest un-annotated frame (the scan dialog reads this)
        self._running = True

    def _open(self):
        cap = cv2.VideoCapture(config.CAMERA_INDEX, cv2.CAP_DSHOW) if sys.platform == "win32" \
            else cv2.VideoCapture(config.CAMERA_INDEX)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))   # USB cams only do 1080p30 in MJPG
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _pause(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while self._running and time.monotonic() < end:
            self.msleep(100)

    def run(self):
        while self._running:
            cap = self._open()
            if not cap.isOpened():
                cap.release()
                self.camera_state.emit(False, f"Cannot open camera {config.CAMERA_INDEX}. Retrying...")
                self._pause(2.0)
                continue
            self.camera_state.emit(True, "Camera ready")
            last_emit = 0.0
            while self._running:
                ok, raw = cap.read()
                if not ok:
                    break
                self.latest_raw = raw
                try:
                    result = self.engine.process(raw)
                except Exception:
                    log.exception("Engine error")
                    result = None
                now = time.monotonic()
                if now - last_emit >= _MIN_EMIT_GAP:
                    self.frame.emit(to_qimage(result.annotated if result else raw))
                    last_emit = now
                if result and result.event:
                    self.event.emit(result)
            cap.release()
            if self._running:
                self.camera_state.emit(False, "Camera disconnected. Reconnecting...")
                self._pause(2.0)

    def stop(self):
        self._running = False
        self.wait(5000)


class OcrWorker(QThread):
    done = pyqtSignal(object)       # OcrResult

    def __init__(self, ocr, image):
        super().__init__()
        self.ocr, self.image = ocr, image

    def run(self):
        self.done.emit(self.ocr.read(self.image))
