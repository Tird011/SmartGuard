"""Find the cameras on this PC and remember which one SmartGuard uses.

Windows numbers cameras 0, 1, 2 ... in the order DirectShow lists them (built-in webcam
usually 0, USB webcam 1). The choice made in Camera Settings is saved to settings.json,
so the USB webcam stays selected after a restart without changing any Windows setting.
Order of priority: SG_CAMERA_INDEX environment variable > settings.json > 0.
"""
import json
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional

from core import config

log = logging.getLogger(__name__)

MAX_CAMERAS = 6             # indexes checked by "Refresh"


@dataclass
class CameraInfo:
    index: int
    name: str = ""
    width: int = 0
    height: int = 0
    thumbnail: Any = None   # small BGR frame, so the guard can see which camera it is
    in_use: bool = False    # the camera SmartGuard has open right now (not re-opened to test it)

    @property
    def label(self) -> str:
        text = f"Camera {self.index}"
        if self.name:
            text += f" - {self.name}"
        if self.width:
            text += f"  ({self.width}x{self.height})"
        return text + ("   [in use]" if self.in_use else "")


def backend() -> int:
    import cv2
    return cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY


def device_names() -> List[str]:
    """Camera names in index order (Windows, needs the small 'pygrabber' package). [] otherwise."""
    if sys.platform != "win32":
        return []
    try:
        from pygrabber.dshow_graph import FilterGraph
        return list(FilterGraph().get_input_devices())
    except Exception:
        return []


def probe(index: int) -> Optional[CameraInfo]:
    """Open camera `index`, grab one frame, close it. None if nothing answers there."""
    import cv2
    cap = cv2.VideoCapture(index, backend())
    try:
        if not cap.isOpened():
            return None
        frame = None
        for _ in range(5):                      # the first frames of some webcams are empty
            ok, frame = cap.read()
            if ok and frame is not None:
                break
        else:
            return None
        h, w = frame.shape[:2]
        thumb = cv2.resize(frame, (160, max(1, int(h * 160 / w))))
        return CameraInfo(index, width=w, height=h, thumbnail=thumb)
    except Exception:
        log.exception("Camera %s probe failed", index)
        return None
    finally:
        cap.release()


def list_cameras(in_use: Optional[int] = None, current_frame=None,
                 max_index: int = MAX_CAMERAS, names: Optional[Iterable[str]] = None) -> List[CameraInfo]:
    """Every camera that answers. The one in use is listed without re-opening it."""
    names = list(device_names() if names is None else names)
    found: List[CameraInfo] = []
    for i in range(max(max_index, len(names))):
        if i == in_use:
            info = CameraInfo(i, in_use=True)
            if current_frame is not None:
                import cv2
                h, w = current_frame.shape[:2]
                info.width, info.height = w, h
                info.thumbnail = cv2.resize(current_frame, (160, max(1, int(h * 160 / w))))
        else:
            info = probe(i)
        if info is not None:
            info.name = names[i] if i < len(names) else ""
            found.append(info)
    return found


# ------------------------------------------------------------ saved choice
def settings_path() -> str:
    return os.getenv("SG_SETTINGS_PATH", os.path.join(config.BASE_DIR, "settings.json"))


def _read_settings() -> dict:
    try:
        with open(settings_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def saved_camera_index(default: int = 0) -> int:
    env = os.getenv("SG_CAMERA_INDEX")
    if env not in (None, ""):
        return int(env)
    try:
        return int(_read_settings().get("camera_index", default))
    except (TypeError, ValueError):
        return default


def save_camera_index(index: int) -> None:
    data = _read_settings()
    data["camera_index"] = int(index)
    with open(settings_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    config.CAMERA_INDEX = int(index)
