"""Central configuration for SmartGuard-Vision.

Every value can be overridden with an environment variable (SG_*) so the same
code runs on the dev laptop and the checkpoint PC without edits.
"""
import os

# --- Base Paths ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, "models")
DATABASE_PATH = os.getenv("SG_DATABASE_PATH", os.path.join(BASE_DIR, "smartguard.db"))
SNAPSHOTS_DIR = os.path.join(BASE_DIR, "snapshots")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

for _d in (MODELS_DIR, SNAPSHOTS_DIR, REPORTS_DIR):
    os.makedirs(_d, exist_ok=True)

# --- AI & Computer Vision Settings ---
YOLO_MODEL_PATH = os.getenv("SG_MODEL_PATH", os.path.join(MODELS_DIR, "smartguard_yolov8.pt"))
YOLO_IMGSZ = 640
CONFIDENCE_THRESHOLD = 0.85        # Tier 1 auto-pass: every relevant detection must reach this
MIN_DETECTION_CONFIDENCE = 0.35    # detections below this are ignored entirely
CLASS_NAMES = ["uniform", "civilian_wear", "id_lanyard"]
INFERENCE_EVERY_N_FRAMES = 3       # run YOLO every Nth frame (keeps CPU-only laptops smooth)
STABLE_DETECTIONS = 2              # same verdict on N checks in a row before acting (kills flicker)
PASS_COOLDOWN_SEC = 6              # don't re-open the gate for the same person standing there
VIOLATION_COOLDOWN_SEC = 10        # don't queue duplicate cards for the same person

# --- Camera Settings ---
CAMERA_INDEX = int(os.getenv("SG_CAMERA_INDEX", "0"))
FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080

# --- Hardware (ESP32) Settings ---
SERIAL_PORT = os.getenv("SG_SERIAL_PORT", "COM3")
BAUD_RATE = 115200
SERIAL_TIMEOUT = 1                 # seconds
ENABLE_HARDWARE = os.getenv("SG_HARDWARE", "1") == "1"

# --- Policy Engine Settings ---
WASH_DAY_WEEKDAY = 2               # datetime.weekday(): Mon=0 ... Wed=2

# --- Identification (Tier 2 OCR / Tier 3 manual) ---
# Student number as printed on the school IDs: 5 digits - 2 digits - 4 digits (e.g. 04141-24-0549).
# Separators may be read by OCR as a space, dot, underscore or long dash, so those are accepted too.
STUDENT_NUMBER_PATTERN = r"\b\d{5}[-–—_. ]\d{2}[-–—_. ]\d{4}\b"
OCR_GPU = False
SCAN_INTERVAL_MS = 1500            # how often the scan dialog tries to read the document
OPEN_GATE_ON_VERIFY = True         # a guard-cleared / document-verified student opens the gate
