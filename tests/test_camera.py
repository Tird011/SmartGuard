"""Camera Settings: finding cameras, saving the choice, switching live."""
import numpy as np

from core import camera, config


def test_list_cameras_skips_missing_and_does_not_reopen_the_one_in_use(monkeypatch):
    opened = []

    def fake_probe(i):
        opened.append(i)
        return camera.CameraInfo(i, width=1280, height=720) if i == 2 else None
    monkeypatch.setattr(camera, "probe", fake_probe)
    frame = np.zeros((480, 640, 3), np.uint8)
    cams = camera.list_cameras(in_use=0, current_frame=frame, max_index=4,
                               names=["Integrated Webcam", "", "USB2.0 HD UVC WebCam"])
    assert [c.index for c in cams] == [0, 2]
    assert 0 not in opened                                  # the open camera is not grabbed twice
    assert cams[0].in_use and cams[0].width == 640 and cams[0].thumbnail.shape[1] == 160
    assert cams[1].label == "Camera 2 - USB2.0 HD UVC WebCam  (1280x720)"


def test_choice_is_saved_and_env_still_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("SG_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.delenv("SG_CAMERA_INDEX", raising=False)
    monkeypatch.setattr(config, "CAMERA_INDEX", 0)
    assert camera.saved_camera_index() == 0
    camera.save_camera_index(2)
    assert camera.saved_camera_index() == 2 and config.CAMERA_INDEX == 2
    monkeypatch.setenv("SG_CAMERA_INDEX", "1")
    assert camera.saved_camera_index() == 1


def test_broken_settings_file_falls_back_to_zero(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    p.write_text("not json")
    monkeypatch.setenv("SG_SETTINGS_PATH", str(p))
    monkeypatch.delenv("SG_CAMERA_INDEX", raising=False)
    assert camera.saved_camera_index() == 0
