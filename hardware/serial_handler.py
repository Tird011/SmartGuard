"""Serial communication handler for SmartGuard-Vision.

Talks to the ESP32 (servo gate, green/red LEDs, warning buzzer) over USB serial.

Design goals
  * Never block the UI or video thread: commands go into a queue and a single
    background thread owns the port.
  * Never crash the app: if the ESP32 is missing, unplugged or silent the
    handler keeps running in software-only mode and silently reconnects.
  * Never replay old commands: nothing is queued while disconnected, and
    commands that sat in the queue too long are discarded (a stale "open gate"
    must not fire after a reconnect).
  * Prove the right device is on the port: connection only counts once the
    firmware answers PING with PONG (or announces READY).
  * Fail safe: the firmware closes the gate if the heartbeat stops, and this
    handler sends SAFE on shutdown.

Protocol (ASCII, one command per line, replies are one line each)
  host -> ESP32:  PING | PASS | WARN | GATE_OPEN | GATE_CLOSE | BUZZ |
                  LED_GREEN | LED_RED | LED_OFF | SAFE | STATUS
  ESP32 -> host:  READY | PONG | OK <CMD> | ERR <reason> | STATUS ... | EVT ...

UI note: status listeners are called from the handler thread. In PyQt, have the
listener emit a pyqtSignal instead of touching widgets directly.
"""
import logging
import queue
import threading
import time
from typing import Callable, List, Optional

try:
    import serial  # pyserial
except ImportError:  # app still runs, hardware just stays disabled
    serial = None

from core import config, policy

logger = logging.getLogger(__name__)

# Connection states (for a UI status indicator)
STATE_DISABLED = "disabled"          # hardware turned off in config / pyserial missing
STATE_DISCONNECTED = "disconnected"  # enabled, searching for the ESP32
STATE_CONNECTED = "connected"        # firmware answered, commands are flowing

# Tunables. Optionally override by adding the same names to core/config.py.
_RECONNECT_SEC = getattr(config, "SERIAL_RECONNECT_SEC", 3.0)   # wait between connection attempts
_HEARTBEAT_SEC = getattr(config, "SERIAL_HEARTBEAT_SEC", 2.0)   # PING interval
_HANDSHAKE_SEC = getattr(config, "SERIAL_HANDSHAKE_SEC", 4.0)   # max wait for the firmware to answer
_STALE_CMD_SEC = 2.0                                            # drop queued commands older than this
_MAX_RX_BUFFER = 256


class SerialHandler:
    def __init__(self, port: Optional[str] = None, baud: Optional[int] = None,
                 enabled: Optional[bool] = None):
        self.port = port or config.SERIAL_PORT
        self.baud = baud or config.BAUD_RATE
        wanted = config.ENABLE_HARDWARE if enabled is None else enabled
        if wanted and serial is None:
            logger.warning("pyserial is not installed; running in software-only mode.")
        self.enabled = bool(wanted and serial is not None)

        self._state = STATE_DISCONNECTED if self.enabled else STATE_DISABLED
        self._conn = None
        self._queue: "queue.Queue" = queue.Queue(maxsize=32)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._listeners: List[Callable[[str], None]] = []
        self._lock = threading.Lock()
        self._last_rx = 0.0
        self._warned = False
        self.last_status_line = ""

    # ------------------------------------------------------------ public state
    @property
    def state(self) -> str:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == STATE_CONNECTED

    def add_status_listener(self, fn: Callable[[str], None]) -> None:
        """fn(state) is called whenever the connection state changes (handler thread)."""
        with self._lock:
            self._listeners.append(fn)

    # --------------------------------------------------------------- lifecycle
    def start(self) -> None:
        """Start the background thread (no-op if disabled or already running)."""
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="SerialHandler", daemon=True)
        self._thread.start()

    def close(self) -> None:
        """Stop the thread, put the hardware in its safe state, release the port."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.write(b"SAFE\n")
                conn.flush()
            except Exception:
                pass
            self._close_port(conn)
            logger.info("Serial connection closed safely.")
        self._flush_queue()
        if self.enabled:
            self._set_state(STATE_DISCONNECTED)

    # ---------------------------------------------------------------- commands
    def send_command(self, cmd: str) -> bool:
        """Queue a command for the ESP32. Never blocks.

        Returns True if the command was accepted for sending, False if the
        hardware is disabled / not connected (the command is NOT queued then).
        """
        cmd = cmd.strip().upper()
        if not self.is_connected:
            logger.debug("[Hardware offline] skipped: %s", cmd)
            return False
        try:
            self._queue.put_nowait((time.monotonic(), cmd))
            return True
        except queue.Full:
            logger.warning("Serial command queue full; dropped %s", cmd)
            return False

    # High-level actions (these are what the rest of the app should call)
    def grant_access(self) -> bool:
        """Tier 1 / guard clear: green LED, gate opens, ESP32 re-closes it by itself."""
        return self.send_command("PASS")

    def deny_access(self) -> bool:
        """Violation: red LED and warning beeps for a few seconds."""
        return self.send_command("WARN")

    def apply_action(self, action: str) -> bool:
        """Map a policy.Evaluation.action straight to hardware behaviour."""
        if action == policy.ACTION_AUTO_PASS:
            return self.grant_access()
        if action == policy.ACTION_FLAG_QUEUE:
            return self.deny_access()
        return False  # ACTION_NONE: nothing to do

    # Individual controls (guard override buttons, diagnostics)
    def open_gate(self) -> bool:
        return self.send_command("GATE_OPEN")

    def close_gate(self) -> bool:
        return self.send_command("GATE_CLOSE")

    def trigger_buzzer(self) -> bool:
        return self.send_command("BUZZ")

    def set_green_led(self) -> bool:
        return self.send_command("LED_GREEN")

    def set_red_led(self) -> bool:
        return self.send_command("LED_RED")

    def all_off(self) -> bool:
        return self.send_command("LED_OFF")

    def request_status(self) -> bool:
        """Ask the ESP32 to report its state; the reply lands in last_status_line."""
        return self.send_command("STATUS")

    # ----------------------------------------------------------- worker thread
    def _run(self) -> None:
        rx = bytearray()
        last_ping = 0.0
        while not self._stop.is_set():
            if self._conn is None:
                if self._connect():
                    rx.clear()
                    last_ping = self._last_rx = time.monotonic()
                else:
                    self._stop.wait(_RECONNECT_SEC)
                continue
            try:
                self._pump_writes()
                self._pump_reads(rx)
                now = time.monotonic()
                if now - last_ping >= _HEARTBEAT_SEC:
                    self._write("PING")
                    last_ping = now
                if now - self._last_rx > _HEARTBEAT_SEC * 3:
                    raise TimeoutError("ESP32 stopped answering")
            except Exception as exc:  # serial errors, unplugged cable, silent firmware
                logger.warning("Serial link lost (%s). Will try to reconnect.", exc)
                self._drop_connection()

    def _create_port(self):
        """Build an unopened port object (separate method so tests can fake it)."""
        conn = serial.Serial()
        conn.port = self.port
        conn.baudrate = self.baud
        conn.timeout = config.SERIAL_TIMEOUT
        conn.write_timeout = 1.0
        conn.dtr = False   # many ESP32 boards auto-reset when DTR/RTS toggle on open
        conn.rts = False
        return conn

    def _connect(self) -> bool:
        conn = None
        try:
            conn = self._create_port()
            conn.open()
            if not self._handshake(conn):
                raise IOError(f"no answer from ESP32 on {self.port}")
        except Exception as exc:
            if conn is not None:
                self._close_port(conn)
            if not self._warned:  # log once, not every retry
                logger.warning("ESP32 not available on %s (%s). Software-only mode; "
                               "retrying every %.0fs.", self.port, exc, _RECONNECT_SEC)
                self._warned = True
            return False
        self._warned = False
        self._conn = conn
        self._set_state(STATE_CONNECTED)
        logger.info("Connected to ESP32 on %s at %d baud.", self.port, self.baud)
        return True

    def _handshake(self, conn) -> bool:
        """Confirm the firmware is on the other end (PONG or READY)."""
        deadline = time.monotonic() + _HANDSHAKE_SEC
        next_ping = 0.0
        buf = bytearray()
        while time.monotonic() < deadline and not self._stop.is_set():
            if time.monotonic() >= next_ping:
                conn.write(b"PING\n")
                conn.flush()
                next_ping = time.monotonic() + 1.0
            n = conn.in_waiting
            if n:
                buf.extend(conn.read(n))
                if b"PONG" in buf or b"READY" in buf:
                    return True
            time.sleep(0.05)
        return False

    def _write(self, cmd: str) -> None:
        self._conn.write(f"{cmd}\n".encode("ascii"))
        self._conn.flush()
        if cmd != "PING":
            logger.info("Sent serial command: %s", cmd)

    def _pump_writes(self) -> None:
        try:
            item = self._queue.get(timeout=0.05)   # also paces the loop
        except queue.Empty:
            return
        while True:
            queued_at, cmd = item
            if time.monotonic() - queued_at <= _STALE_CMD_SEC:
                self._write(cmd)
            else:
                logger.warning("Dropped stale serial command: %s", cmd)
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break

    def _pump_reads(self, rx: bytearray) -> None:
        n = self._conn.in_waiting
        if not n:
            return
        rx.extend(self._conn.read(n))
        self._last_rx = time.monotonic()
        while True:
            i = rx.find(b"\n")
            if i < 0:
                break
            line = bytes(rx[:i]).decode("ascii", "ignore").strip()
            del rx[:i + 1]
            self._handle_line(line)
        if len(rx) > _MAX_RX_BUFFER:   # garbage with no newline
            rx.clear()

    def _handle_line(self, line: str) -> None:
        if not line or line == "PONG":
            return
        if line.startswith("ERR"):
            logger.warning("ESP32 reported: %s", line)
        elif line.startswith("STATUS"):
            self.last_status_line = line
            logger.info("ESP32 %s", line)
        else:
            logger.debug("ESP32: %s", line)

    def _drop_connection(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            self._close_port(conn)
        self._flush_queue()
        self._set_state(STATE_DISCONNECTED)

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _close_port(conn) -> None:
        try:
            conn.close()
        except Exception:
            pass

    def _flush_queue(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass

    def _set_state(self, new_state: str) -> None:
        with self._lock:
            if new_state == self._state:
                return
            self._state = new_state
            listeners = list(self._listeners)
        logger.info("Hardware state: %s", new_state)
        for fn in listeners:
            try:
                fn(new_state)
            except Exception:
                logger.exception("Hardware status listener failed")


# Global singleton for project-wide access
_instance: Optional[SerialHandler] = None


def get_serial_handler() -> SerialHandler:
    """Return the shared handler, creating and starting it on first use."""
    global _instance
    if _instance is None:
        _instance = SerialHandler()
        _instance.start()
    return _instance
