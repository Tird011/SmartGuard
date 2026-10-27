"""pytest setup: keep tests away from the real database and the real ESP32."""
import os
import tempfile

os.environ["SG_DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(prefix="sg_test_"), "test.db")
os.environ["SG_HARDWARE"] = "0"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
