import time

import pytest
import serial

from core import policy
from hardware import serial_handler as sh


class Firmware:
    """Stands in for the ESP32 sketch; shared across reconnects."""
    def __init__(self):
        self.received, self.silent, self.absent = [], False, False


class FakePort:
    def __init__(self, fw):
        self.fw, self.is_open, self.out, self.written, self.unplugged = fw, False, bytearray(), bytearray(), False

    def open(self):
        if self.fw.absent:
            raise serial.SerialException("port not found")
        self.is_open = True

    def close(self):
        self.is_open = False

    def flush(self):
        pass

    @property
    def in_waiting(self):
        if self.unplugged:
            raise serial.SerialException("device disconnected")
        return len(self.out)

    def read(self, n):
        data = bytes(self.out[:n])
        del self.out[:n]
        return data

    def write(self, data):
        if self.unplugged:
            raise serial.SerialException("device disconnected")
        self.written.extend(data)
        for line in data.decode().splitlines():
            if not self.fw.silent:
                self.fw.received.append(line)
                self.out.extend(b"PONG\n" if line == "PING" else b"OK " + line.encode() + b"\n")


def wait(cond, seconds=4.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def rig(monkeypatch):
    monkeypatch.setattr(sh, "_RECONNECT_SEC", 0.2)
    monkeypatch.setattr(sh, "_HEARTBEAT_SEC", 0.3)
    monkeypatch.setattr(sh, "_HANDSHAKE_SEC", 0.6)
    fw, ports, handlers = Firmware(), [], []

    def make():
        h = sh.SerialHandler(port="COMX", enabled=True)

        def create():
            ports.append(FakePort(fw))
            return ports[-1]
        h._create_port = create
        handlers.append(h)
        return h
    yield fw, ports, make
    for h in handlers:
        h.close()


def test_commands_reach_the_firmware_and_map_from_policy_actions(rig):
    fw, _, make = rig
    h = make()
    assert h.send_command("PASS") is False                   # offline: refused, not queued
    h.start()
    assert wait(lambda: h.is_connected)
    assert h.apply_action(policy.ACTION_AUTO_PASS) and h.apply_action(policy.ACTION_FLAG_QUEUE)
    assert h.apply_action(policy.ACTION_NONE) is False
    assert wait(lambda: fw.received.count("PASS") == 1 and fw.received.count("WARN") == 1)
    assert "PING" in fw.received                             # heartbeat is running


def test_stale_command_is_never_sent(rig):
    fw, _, make = rig
    h = make()
    h.start()
    assert wait(lambda: h.is_connected)
    h._queue.put((time.monotonic() - 10, "GATE_OPEN"))
    time.sleep(0.5)
    assert "GATE_OPEN" not in fw.received


def test_unplug_then_replug_reconnects(rig):
    fw, ports, make = rig
    h = make()
    states = []
    h.add_status_listener(states.append)
    h.start()
    assert wait(lambda: h.is_connected)
    fw.absent, ports[-1].unplugged = True, True
    assert wait(lambda: not h.is_connected)
    assert h.grant_access() is False
    fw.absent = False
    assert wait(lambda: h.is_connected)
    assert states[:3] == ["connected", "disconnected", "connected"]
    assert h.grant_access()


def test_silent_firmware_is_dropped_and_recovers(rig):
    fw, _, make = rig
    h = make()
    h.start()
    assert wait(lambda: h.is_connected)
    fw.silent = True
    assert wait(lambda: not h.is_connected)
    fw.silent = False
    assert wait(lambda: h.is_connected)


def test_shutdown_sends_safe(rig):
    _, ports, make = rig
    h = make()
    h.start()
    assert wait(lambda: h.is_connected)
    port = ports[-1]
    h.close()
    assert b"SAFE\n" in port.written and not port.is_open and h.state == "disconnected"


def test_wrong_device_never_counts_as_connected(rig):
    fw, _, make = rig
    fw.silent = True
    h = make()
    h.start()
    time.sleep(1.0)
    assert not h.is_connected


def test_disabled_mode_is_inert():
    h = sh.SerialHandler(enabled=False)
    h.start()
    assert h.state == "disabled" and h.grant_access() is False and h._thread is None
