import os

import numpy as np
import pytest

from core import config
from core.engine import CheckpointEngine
from core.ocr_engine import OcrResult
from core.verification import Verifier, validate
from database import db_manager as db


class FakeHW:
    def __init__(self):
        self.calls = []

    def grant_access(self):
        self.calls.append("grant")

    def deny_access(self):
        self.calls.append("deny")


class FakeDetector:
    def __init__(self):
        self.dets = []

    def detect(self, frame):
        return self.dets


def det(label, conf=0.95):
    return {"label": label, "conf": conf, "box": (100, 100, 200, 300)}


COMPLIANT = [det("uniform"), det("id_lanyard")]
NO_LANYARD = [det("uniform")]


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SNAPSHOTS_DIR", str(tmp_path / "snaps"))
    monkeypatch.setattr(config, "INFERENCE_EVERY_N_FRAMES", 1)
    monkeypatch.setattr(config, "STABLE_DETECTIONS", 2)
    path = str(tmp_path / "t.db")
    db.init_db(path)
    clock = [0.0]
    detector, hw = FakeDetector(), FakeHW()
    engine = CheckpointEngine(detector, hw, path, clock=lambda: clock[0])
    frame = np.zeros((480, 640, 3), np.uint8)

    def feed(dets, n=1, advance=0.0):
        events = []
        for _ in range(n):
            detector.dets = dets
            clock[0] += advance
            events.append(engine.process(frame))
        return events
    return engine, hw, path, feed


def test_pass_needs_stable_verdict_then_opens_gate(rig):
    _, hw, _, feed = rig
    first, second = feed(COMPLIANT, 2)
    assert first.event is None and second.event == "pass"
    assert hw.calls == ["grant"]


def test_violation_creates_pending_record_with_snapshot(rig):
    _, hw, path, feed = rig
    res = feed(NO_LANYARD, 2)[-1]
    assert res.event == "flag" and hw.calls == ["deny"]
    rec = db.get_record(res.record_id, path)
    assert rec["verification_status"] == "Pending" and rec["violation_type"] == "No Lanyard"
    assert os.path.isfile(rec["snapshot_path"])


def test_same_person_is_not_flagged_twice_within_cooldown(rig):
    _, hw, path, feed = rig
    feed(NO_LANYARD, 10, advance=0.5)           # 5 seconds of the same person standing there
    assert len(db.fetch_pending(path)) == 1 and hw.calls == ["deny"]
    feed(NO_LANYARD, 4, advance=3.0)            # still there after the cooldown: flagged again
    assert len(db.fetch_pending(path)) == 2


def test_empty_frame_rearms_for_next_person(rig):
    _, hw, _, feed = rig
    feed(COMPLIANT, 2)
    feed([], 1)
    feed(COMPLIANT, 2)
    assert hw.calls == ["grant", "grant"]


def test_flicker_does_not_trigger(rig):
    _, hw, path, feed = rig
    for dets in (NO_LANYARD, COMPLIANT, NO_LANYARD, COMPLIANT):
        feed(dets, 1)
    assert hw.calls == [] and db.fetch_pending(path) == []


def test_detector_crash_does_not_kill_the_loop(rig):
    engine, _, _, feed = rig
    engine.detector.detect = lambda frame: 1 / 0
    assert feed([], 3)[-1].evaluation.action == "none"


def test_verification_tiers(rig):
    _, hw, path, feed = rig
    rid = feed(NO_LANYARD, 2)[-1].record_id
    v = Verifier(hw, path)
    hw.calls.clear()

    bad = v.manual(rid, "", "Cruz", "12 34")
    assert not bad.ok and db.get_record(rid, path)["verification_status"] == "Pending" and hw.calls == []

    ok = v.scan(rid, OcrResult("2023-01234", "Juan", "Dela Cruz"))
    assert ok.ok and hw.calls == ["grant"]
    assert db.get_record(rid, path)["verification_status"] == "Auto-Verified"

    assert v.edit(rid, "Juan", "De La Cruz", "2023-01234").ok and hw.calls == ["grant"]  # edit never opens the gate
    assert v.add_manual("Maria", "Santos", "2023-0002").ok
    assert not v.manual(9999, "A", "B", "1").ok


def test_validate():
    assert validate("Juan", "Dela Cruz", "2023-01234") == []
    assert len(validate("", "", "")) == 3
    assert validate("J0hn", "Cruz", "1")
