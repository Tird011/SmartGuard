# SmartGuard-Vision v1 (Prototype)

Local-first campus checkpoint monitor: camera + YOLOv8 check uniform / ID lanyard, an ESP32 opens
the gate, flagged students go to a review queue, and every case ends up in a local SQLite audit log.

## Run (Windows)

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy your_weights.pt models\smartguard_yolov8.pt
python main.py
```

Without the weights the app still starts (detection off, manual entry and records work).
The first document scan downloads the EasyOCR English model, so do one scan while online.

## Flow

```
camera -> core/detector.py (YOLOv8) -> core/policy.py (today's dress code)
       -> core/engine.py (stable verdict + cooldown)
            pass : hardware/serial_handler.py -> ESP32 opens gate (Tier 1)
            flag : snapshot + Pending record (database/db_manager.py) + red LED/buzzer
                   -> review queue card -> Confirm ->
                        Tier 2: scan ID/COR (core/ocr_engine.py), or
                        Tier 3: manual form (core/verification.py)
audit table (ui/audit_page.py) -> Save A Copy -> PDF / Excel (core/report.py)
```

| Folder | What is in it |
|---|---|
| `core/` | config, policy, detector, engine, OCR, verification, report export |
| `database/` | `db_manager.py`: `students` + `records` tables (names always split, date and time separate) |
| `hardware/` | `serial_handler.py`: background, auto-reconnecting ESP32 link |
| `firmware/` | Arduino sketch for the ESP32 (edit the pin numbers at the top) |
| `ui/` | PyQt5 window, queue cards, dialogs, audit page |

## Settings you will want to change (`core/config.py`)

- `STUDENT_NUMBER_PATTERN`: your school's student number format (used by the OCR).
- `SERIAL_PORT` (or env `SG_SERIAL_PORT`), `CAMERA_INDEX`, `WASH_DAY_WEEKDAY`, `CONFIDENCE_THRESHOLD`.
- `SG_HARDWARE=0` runs without the ESP32.

## Model

Train YOLOv8 with exactly three classes: `uniform`, `civilian_wear`, `id_lanyard`. The app checks the
class names when it loads the weights.

## Tests

```
pip install pytest
python -m pytest tests
```
