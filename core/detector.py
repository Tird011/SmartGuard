"""YOLOv8 wrapper, frame annotation and snapshot saving."""
import logging
import os
import time
from typing import Dict, List, Optional

import cv2

from core import config
from core.policy import Evaluation

log = logging.getLogger(__name__)

GREEN, RED, AMBER = (60, 160, 40), (40, 40, 220), (0, 170, 255)


class Detector:
    """Loads lazily and never raises: check `.ready` / `.error`."""

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or config.YOLO_MODEL_PATH
        self._model = None
        self.error = ""

    @property
    def ready(self) -> bool:
        return self._model is not None

    def load(self) -> bool:
        if self._model is not None:
            return True
        if not os.path.isfile(self.model_path):
            self.error = f"Model not found: {self.model_path}"
            return False
        try:
            from ultralytics import YOLO
            model = YOLO(self.model_path)
            missing = set(config.CLASS_NAMES) - set(model.names.values())
            if missing:
                self.error = f"Model lacks classes {sorted(missing)} (has {sorted(model.names.values())})"
                return False
        except Exception as exc:
            self.error = f"Could not load model: {exc}"
            return False
        self._model, self.error = model, ""
        return True

    def detect(self, frame) -> List[Dict]:
        """[{"label", "conf", "box": (x1, y1, x2, y2)}]; empty if no model."""
        if self._model is None:
            return []
        res = self._model.predict(frame, imgsz=config.YOLO_IMGSZ,
                                  conf=config.MIN_DETECTION_CONFIDENCE, verbose=False)[0]
        return [{"label": res.names[int(b.cls[0])], "conf": float(b.conf[0]),
                 "box": tuple(int(v) for v in b.xyxy[0].tolist())} for b in res.boxes]


def draw_boxes(frame, detections: List[Dict], evaluation: Optional[Evaluation] = None):
    """Return an annotated copy: green boxes when compliant, red/amber otherwise."""
    out = frame.copy()
    if evaluation is None or evaluation.action == "none":
        colour = GREEN
    else:
        colour = GREEN if evaluation.compliant else (AMBER if evaluation.status == "low_confidence" else RED)
    for d in detections:
        x1, y1, x2, y2 = d["box"]
        cv2.rectangle(out, (x1, y1), (x2, y2), colour, 2)
        cv2.putText(out, f"{d['label']} {d['conf']:.0%}", (x1, max(y1 - 8, 16)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2)
    if evaluation is not None and evaluation.action == "flag_queue":
        cv2.putText(out, evaluation.violation_type, (16, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, colour, 2)
    return out


def crop_to_detections(frame, detections: List[Dict], pad: int = 40):
    """Crop around every detection; the whole frame if there is nothing to crop to."""
    if not detections:
        return frame
    h, w = frame.shape[:2]
    x1 = max(min(d["box"][0] for d in detections) - pad, 0)
    y1 = max(min(d["box"][1] for d in detections) - pad, 0)
    x2 = min(max(d["box"][2] for d in detections) + pad, w)
    y2 = min(max(d["box"][3] for d in detections) + pad, h)
    return frame[y1:y2, x1:x2] if x2 > x1 and y2 > y1 else frame


def save_snapshot(image) -> str:
    """Write a JPEG into the snapshots folder and return its path."""
    os.makedirs(config.SNAPSHOTS_DIR, exist_ok=True)
    now = time.time()
    name = time.strftime("%Y%m%d_%H%M%S", time.localtime(now)) + f"_{int(now * 1000) % 1000:03d}.jpg"
    path = os.path.join(config.SNAPSHOTS_DIR, name)
    if not cv2.imwrite(path, image):
        raise IOError(f"Could not write snapshot {path}")
    return path
