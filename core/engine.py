"""Checkpoint engine: one frame in -> annotated frame + (maybe) one event out.

    frame -> Detector -> policy.evaluate_compliance -> stability + cooldown
        "pass" : compliant and confident  -> ESP32 opens the gate (Tier 1)
        "flag" : violation / low confidence -> snapshot + Pending record + red LED/buzzer

No Qt in here, so it is testable without a screen or a camera.
"""
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from core import config, policy
from core.detector import crop_to_detections, draw_boxes, save_snapshot
from database import db_manager

log = logging.getLogger(__name__)

EVENT_PASS, EVENT_FLAG = "pass", "flag"


@dataclass
class FrameResult:
    annotated: Any
    evaluation: Optional[policy.Evaluation]
    event: Optional[str] = None
    record_id: Optional[int] = None


class CheckpointEngine:
    def __init__(self, detector, hardware, db_path: Optional[str] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.detector, self.hw, self.db_path, self._clock = detector, hardware, db_path, clock
        self._frames = 0
        self._dets: list = []
        self._eval: Optional[policy.Evaluation] = None
        self._key = None            # verdict being confirmed
        self._streak = 0
        self._locked = False        # an event just fired; wait for cooldown or an empty frame
        self._last_fire = 0.0
        self._detect_failed = False

    def process(self, frame) -> FrameResult:
        event = record_id = None
        if self._frames % config.INFERENCE_EVERY_N_FRAMES == 0:
            self._infer(frame)
            event = self._decide(self._eval)
            if event == EVENT_PASS:
                self.hw.grant_access()
            elif event == EVENT_FLAG:
                record_id = self._flag(frame)
        self._frames += 1
        return FrameResult(draw_boxes(frame, self._dets, self._eval), self._eval, event, record_id)

    def _infer(self, frame) -> None:
        try:
            self._dets = self.detector.detect(frame)
            self._detect_failed = False
        except Exception:
            if not self._detect_failed:     # log once, not on every frame
                log.exception("Detection failed")
            self._detect_failed, self._dets = True, []
        self._eval = policy.evaluate_compliance(self._dets)

    def _decide(self, ev: policy.Evaluation) -> Optional[str]:
        if ev.action == policy.ACTION_NONE:         # nobody in frame: re-arm
            self._key, self._streak, self._locked = None, 0, False
            return None
        key = (ev.action, ev.violation_type)
        self._streak = self._streak + 1 if key == self._key else 1
        self._key = key
        if self._streak < config.STABLE_DETECTIONS:
            return None
        passing = ev.action == policy.ACTION_AUTO_PASS
        cooldown = config.PASS_COOLDOWN_SEC if passing else config.VIOLATION_COOLDOWN_SEC
        now = self._clock()
        if self._locked and now - self._last_fire < cooldown:
            return None
        self._locked, self._last_fire = True, now
        return EVENT_PASS if passing else EVENT_FLAG

    def _flag(self, frame) -> int:
        path = save_snapshot(crop_to_detections(frame, self._dets))
        record_id = db_manager.log_violation(self._eval.violation_type, path, db_path=self.db_path)
        self.hw.deny_access()
        return record_id
