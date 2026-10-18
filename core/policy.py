"""Schedule-aware policy engine for SmartGuard-Vision.

Decides what the camera result means for TODAY's dress code.

  Standard days (Mon, Tue, Thu, Fri): uniform + ID lanyard required.
  Wash Day (config.WASH_DAY_WEEKDAY):  uniform OR civilian wear allowed,
                                       ID lanyard still strictly mandatory.

Flow position (see system flowchart):
    YOLO detections -> evaluate_compliance() -> action
        auto_pass  : compliant AND confident  -> ESP32 opens gate (Tier 1)
        flag_queue : violation OR low confidence -> snapshot card in side queue (Tier 2 / 3)
        none       : nothing detected -> do nothing

The Evaluation's `violation_type` string is written as-is to the database
(db_manager.log_violation) and shown on the queue card.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Union

from core import config

# Class names the YOLO model emits (must match config.CLASS_NAMES).
UNIFORM = "uniform"
CIVILIAN = "civilian_wear"
LANYARD = "id_lanyard"

_missing = {UNIFORM, CIVILIAN, LANYARD} - set(config.CLASS_NAMES)
if _missing:
    raise RuntimeError(f"config.CLASS_NAMES is missing classes the policy engine needs: {sorted(_missing)}")

# Actions
ACTION_AUTO_PASS = "auto_pass"
ACTION_FLAG_QUEUE = "flag_queue"
ACTION_NONE = "none"

# Status (drives the UI banner colour)
STATUS_COMPLIANT = "compliant"
STATUS_VIOLATION = "violation"
STATUS_LOW_CONFIDENCE = "low_confidence"
STATUS_IDLE = "idle"

# Violation labels (stored in the database, shown on queue cards)
V_NO_LANYARD = "No Lanyard"
V_CIVILIAN_ON_UNIFORM_DAY = "Civilian Wear on Uniform Day"
V_NO_ATTIRE = "Attire Not Detected"
V_LOW_CONFIDENCE = "Low Confidence"

DateLike = Union[date, datetime]


@dataclass(frozen=True)
class Profile:
    """Today's rule set, also shown in the UI header badge."""
    name: str
    allowed_attire: frozenset
    description: str


STANDARD_PROFILE = Profile("Standard Uniform", frozenset({UNIFORM}),
                           "Full uniform + ID lanyard required")
WASH_DAY_PROFILE = Profile("Wash Day", frozenset({UNIFORM, CIVILIAN}),
                           "Casual attire allowed - ID lanyard still required")


@dataclass
class Evaluation:
    status: str
    action: str
    profile: str
    violations: List[str] = field(default_factory=list)
    confidence: float = 0.0     # weakest relevant detection (0 when nothing was evaluated)

    @property
    def compliant(self) -> bool:
        return self.status == STATUS_COMPLIANT

    @property
    def violation_type(self) -> str:
        """Text for the database / queue card. Empty when auto-passing or idle."""
        if self.violations:
            return ", ".join(self.violations)
        if self.status == STATUS_LOW_CONFIDENCE:
            return V_LOW_CONFIDENCE
        return ""

    @property
    def message(self) -> str:
        """Short line for the UI status label."""
        if self.status == STATUS_COMPLIANT:
            return f"Compliant ({self.profile})"
        if self.status == STATUS_IDLE:
            return "Waiting for subject"
        return f"{self.violation_type} - review needed"

    def to_dict(self) -> Dict:
        return {"status": self.status, "action": self.action, "profile": self.profile,
                "violation_type": self.violation_type, "violations": list(self.violations),
                "confidence": self.confidence}


# ---------------------------------------------------------------- schedule
def is_wash_day(target_date: Optional[DateLike] = None) -> bool:
    """True if the date (default: today) is the configured wash day."""
    d = target_date or datetime.now()
    return d.weekday() == config.WASH_DAY_WEEKDAY


def get_active_profile(target_date: Optional[DateLike] = None) -> Profile:
    return WASH_DAY_PROFILE if is_wash_day(target_date) else STANDARD_PROFILE


# -------------------------------------------------------------- evaluation
def _best_confidences(detections: Iterable[Union[str, Dict]]) -> Dict[str, float]:
    """Collapse detections to {label: highest confidence}.

    Accepts the detector's dicts ({"label", "conf", ...}) or bare class-name
    strings (treated as 100% confident, handy for tests). Detections below
    config.MIN_DETECTION_CONFIDENCE are ignored.
    """
    best: Dict[str, float] = {}
    for d in detections:
        label, conf = (d, 1.0) if isinstance(d, str) else (d.get("label"), float(d.get("conf", 0.0)))
        if label not in config.CLASS_NAMES or conf < config.MIN_DETECTION_CONFIDENCE:
            continue
        if conf > best.get(label, 0.0):
            best[label] = conf
    return best


def evaluate_compliance(detections: Iterable[Union[str, Dict]],
                        target_date: Optional[DateLike] = None) -> Evaluation:
    """Judge one frame's detections against the active day's policy."""
    profile = get_active_profile(target_date)
    best = _best_confidences(detections)

    if not best:                                   # nothing usable in frame
        return Evaluation(STATUS_IDLE, ACTION_NONE, profile.name)

    violations: List[str] = []
    confs: List[float] = []

    # Attire: if both classes appear (e.g. several people in frame), the strongest wins.
    attire = {k: v for k, v in best.items() if k in (UNIFORM, CIVILIAN)}
    if not attire:
        violations.append(V_NO_ATTIRE)
    else:
        label = max(attire, key=attire.get)
        confs.append(attire[label])
        if label not in profile.allowed_attire:
            violations.append(V_CIVILIAN_ON_UNIFORM_DAY)

    # ID lanyard: mandatory on every day, no exceptions.
    if LANYARD in best:
        confs.append(best[LANYARD])
    else:
        violations.append(V_NO_LANYARD)

    weakest = min(confs) if confs else 0.0

    if violations:
        return Evaluation(STATUS_VIOLATION, ACTION_FLAG_QUEUE, profile.name, violations, weakest)
    if weakest < config.CONFIDENCE_THRESHOLD:      # looks compliant but the model isn't sure
        return Evaluation(STATUS_LOW_CONFIDENCE, ACTION_FLAG_QUEUE, profile.name, [], weakest)
    return Evaluation(STATUS_COMPLIANT, ACTION_AUTO_PASS, profile.name, [], weakest)


if __name__ == "__main__":
    prof = get_active_profile()
    print(f"Today: {prof.name} - {prof.description}")
    print(evaluate_compliance([{"label": "uniform", "conf": 0.93},
                               {"label": "id_lanyard", "conf": 0.9}]).to_dict())