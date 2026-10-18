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
CONFIDENCE_THRESHOLD = 0.85        
MIN_DETECTION_CONFIDENCE = 0.35    
CLASS_NAMES = ["uniform", "civilian_wear", "id_lanyard"]
INFERENCE_EVERY_N_FRAMES = 3       
VIOLATION_COOLDOWN_SEC = 10        # dont queue duplicate cards for the same person

# --- Camera Settings ---
CAMERA_INDEX = int(os.getenv("SG_CAMERA_INDEX", "0"))
FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080

# --- Hardware (ESP32) Settings ---
SERIAL_PORT = os.getenv("SG_SERIAL_PORT", "COM3")
BAUD_RATE = 115200
SERIAL_TIMEOUT = 1
ENABLE_HARDWARE = os.getenv("SG_HARDWARE", "1") == "1"

# --- Policy Engine Settings ---
WASH_DAY_WEEKDAY = 2               # Mon=0 ... Wed=2 parang array