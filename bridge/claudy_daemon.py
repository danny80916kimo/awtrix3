#!/usr/bin/env python3
"""
Claudy daemon: keeps a persistent serial connection to AWTRIX3
and accepts hook events from claudy_client.py via a Unix socket.

Usage:
    python3 claudy_daemon.py [start|stop|status]
"""

import json
import os
import selectors
import signal
import socket
import sys
import time
from glob import glob

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BAUD = 115200
SOCK_PATH = "/tmp/claudy.sock"
PID_PATH = "/tmp/claudy.pid"
DEFAULT_MAX_TOKENS = 200_000
LARGE_CONTEXT = 1_000_000
MAX_MSG_LEN = 58
RECONNECT_INTERVAL = 2.0  # seconds between serial reconnect attempts

EVENT_STATE = {
    "SessionStart":       "idle",
    "UserPromptSubmit":   "thinking",
    "PreToolUse":         "working",
    "PostToolUse":        "thinking",
    "PostToolUseFailure": "error",
    "Notification":       "waiting",
    "PermissionRequest":  "waiting",
    "Elicitation":        "waiting",
    "Stop":               "done",
    "StopFailure":        "error",
    "PermissionDenied":   "error",
    "TaskCompleted":      "done",
    "SessionEnd":         "idle",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)

# ---------------------------------------------------------------------------
# Helpers (from send_serial.py)
# ---------------------------------------------------------------------------

def brief(s: str) -> str:
    if s and len(s) > MAX_MSG_LEN:
        return s[:MAX_MSG_LEN]
    return s or ""


def detect_port() -> str:
    override = os.environ.get("CLAUDY_SERIAL_PORT")
    if override:
        return override
    candidates = sorted(glob("/dev/cu.usbmodem*") + glob("/dev/cu.usbserial*"))
    if not candidates:
        raise RuntimeError("No USB serial port found")
    return candidates[0]


def calc_context_pct(ev: dict) -> int:
    transcript_path = ev.get("transcript_path")
    if not transcript_path:
        return -1
    try:
        used = 0
        model = ""
        with open(transcript_path, "r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # model and usage may be at top level or nested in message
                msg = obj.get("message", {}) if isinstance(obj.get("message"), dict) else {}
                if "model" in msg:
                    model = msg["model"]
                elif "model" in obj:
                    model = obj["model"]
                usage = msg.get("usage") or obj.get("usage")
                if usage:
                    used = (
                        usage.get("input_tokens", 0)
                        + usage.get("cache_read_input_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)
                    )
        if used == 0:
            return -1
        max_tokens = DEFAULT_MAX_TOKENS
        env_max = os.environ.get("CLAUDY_MAX_TOKENS")
        if env_max:
            max_tokens = int(env_max)
        elif used > DEFAULT_MAX_TOKENS or "[1m]" in model:
            max_tokens = LARGE_CONTEXT
        return min(100, int(used * 100 / max_tokens))
    except Exception:
        return -1


def build_payload(ev: dict) -> dict:
    event_name = ev.get("hook_event_name", "")
    state = EVENT_STATE.get(event_name, "idle")

    tool = ""
    msg = ""

    if event_name == "PreToolUse":
        tool = ev.get("tool_name", "")
        tool_input = ev.get("tool_input", {})
        if isinstance(tool_input, dict):
            msg = (
                tool_input.get("file_path")
                or tool_input.get("command")
                or tool_input.get("pattern")
                or ""
            )
            if "/" in msg:
                msg = msg.rsplit("/", 1)[-1]
        msg = brief(msg)

    pct = calc_context_pct(ev)

    payload: dict = {"state": state}
    if tool:
        payload["tool"] = brief(tool)
    if msg:
        payload["msg"] = msg
    if pct >= 0:
        payload["pct"] = pct

    return payload


# ---------------------------------------------------------------------------
# SerialManager
# ---------------------------------------------------------------------------

class SerialManager:
    """Manages a persistent serial connection with auto-reconnect."""

    def __init__(self):
        self.ser = None
        self.port = None
        self.last_reconnect_attempt = 0.0

    def connect(self) -> bool:
        try:
            import serial  # type: ignore
        except ImportError:
            log("pyserial not installed. Run: pip3 install pyserial")
            return False

        try:
            port = detect_port()
            ser = serial.Serial()
            ser.port = port
            ser.baudrate = BAUD
            ser.timeout = 2
            ser.dtr = False
            ser.rts = False
            ser.open()
            self.ser = ser
            self.port = port
            log(f"Serial connected: {port}")
            return True
        except Exception as e:
            log(f"Serial connect failed: {e}")
            self.ser = None
            return False

    def ensure_connected(self) -> bool:
        if self.ser and self.ser.is_open:
            return True
        now = time.monotonic()
        if now - self.last_reconnect_attempt < RECONNECT_INTERVAL:
            return False
        self.last_reconnect_attempt = now
        return self.connect()

    def send(self, payload: dict):
        if not self.ensure_connected():
            return
        line = json.dumps(payload, separators=(",", ":")) + "\n"
        try:
            self.ser.write(line.encode())
            self.ser.flush()
            log(f"Sent: {line.rstrip()}")
        except Exception as e:
            log(f"Serial write error: {e}")
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def close(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
            log("Serial closed")


# ---------------------------------------------------------------------------
# DaemonServer
# ---------------------------------------------------------------------------

class DaemonServer:
    """Unix socket server that bridges hook events to serial."""

    def __init__(self):
        self.serial_mgr = SerialManager()
        self.sel = selectors.DefaultSelector()
        self.running = False
        self.pending_idle = None  # (deadline_monotonic, payload)
        self.server_sock = None
        # Buffer for partially received client data
        self.client_buffers: dict[int, bytearray] = {}

    def start(self):
        self._cleanup_stale()
        self._bind_socket()
        self._write_pid()
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        log("Connecting to serial...")
        self.serial_mgr.connect()

        # Wait for ESP32 to finish booting after the CH340 reset
        log("Waiting 6s for board to boot...")
        time.sleep(6)

        self.running = True
        log(f"Daemon running (pid={os.getpid()}, socket={SOCK_PATH})")
        self._main_loop()

    def _cleanup_stale(self):
        """Remove stale socket/PID if the old daemon is dead."""
        if os.path.exists(PID_PATH):
            try:
                old_pid = int(open(PID_PATH).read().strip())
                os.kill(old_pid, 0)  # Check if alive
                log(f"Another daemon is already running (pid={old_pid})")
                sys.exit(1)
            except (ProcessLookupError, ValueError):
                # Old process is dead
                pass
            except PermissionError:
                log(f"Another daemon may be running (pid check failed)")
                sys.exit(1)
        if os.path.exists(SOCK_PATH):
            os.unlink(SOCK_PATH)
        if os.path.exists(PID_PATH):
            os.unlink(PID_PATH)

    def _bind_socket(self):
        self.server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_sock.bind(SOCK_PATH)
        self.server_sock.listen(8)
        self.server_sock.setblocking(False)
        self.sel.register(self.server_sock, selectors.EVENT_READ, data=None)

    def _write_pid(self):
        with open(PID_PATH, "w") as f:
            f.write(str(os.getpid()))

    def _signal_handler(self, signum, frame):
        log(f"Received signal {signum}, shutting down...")
        self.running = False

    def _main_loop(self):
        while self.running:
            events = self.sel.select(timeout=1.0)
            for key, mask in events:
                if key.data is None:
                    self._accept(key.fileobj)
                else:
                    self._handle_client(key)
            self._housekeep()
        self._shutdown()

    def _accept(self, sock):
        conn, _ = sock.accept()
        conn.setblocking(False)
        self.sel.register(conn, selectors.EVENT_READ, data="client")
        self.client_buffers[conn.fileno()] = bytearray()

    def _handle_client(self, key):
        conn = key.fileobj
        fd = conn.fileno()
        try:
            data = conn.recv(4096)
        except (ConnectionResetError, OSError):
            data = b""

        if data:
            buf = self.client_buffers.get(fd)
            if buf is not None:
                buf.extend(data)
            return

        # EOF — client closed connection, process the buffered data
        self.sel.unregister(conn)
        raw = bytes(self.client_buffers.pop(fd, b""))
        conn.close()

        if not raw.strip():
            return

        try:
            ev = json.loads(raw)
        except json.JSONDecodeError as e:
            log(f"Invalid JSON from client: {e}")
            return

        event_name = ev.get("hook_event_name", "")
        payload = build_payload(ev)
        self.serial_mgr.send(payload)

        # Schedule delayed idle for terminal events
        if event_name in ("Stop", "TaskCompleted"):
            self.pending_idle = (time.monotonic() + 3.0, {"state": "idle"})
        elif event_name not in ("SessionEnd",):
            # New non-terminal event cancels pending idle
            self.pending_idle = None

    def _housekeep(self):
        # Send delayed idle if timer expired
        if self.pending_idle:
            deadline, payload = self.pending_idle
            if time.monotonic() >= deadline:
                self.serial_mgr.send(payload)
                self.pending_idle = None

        # Periodically try to reconnect serial
        self.serial_mgr.ensure_connected()

    def _shutdown(self):
        log("Shutting down...")
        self.serial_mgr.close()
        if self.server_sock:
            self.sel.unregister(self.server_sock)
            self.server_sock.close()
        self.sel.close()
        if os.path.exists(SOCK_PATH):
            os.unlink(SOCK_PATH)
        if os.path.exists(PID_PATH):
            os.unlink(PID_PATH)
        log("Daemon stopped.")


# ---------------------------------------------------------------------------
# CLI: start / stop / status
# ---------------------------------------------------------------------------

def cmd_stop():
    if not os.path.exists(PID_PATH):
        print("Daemon is not running (no PID file).")
        return
    try:
        pid = int(open(PID_PATH).read().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to daemon (pid={pid}).")
    except ProcessLookupError:
        print("Daemon is not running (stale PID file). Cleaning up.")
        if os.path.exists(PID_PATH):
            os.unlink(PID_PATH)
        if os.path.exists(SOCK_PATH):
            os.unlink(SOCK_PATH)
    except Exception as e:
        print(f"Error stopping daemon: {e}")


def cmd_status():
    if not os.path.exists(PID_PATH):
        print("Daemon is not running.")
        return
    try:
        pid = int(open(PID_PATH).read().strip())
        os.kill(pid, 0)
        print(f"Daemon is running (pid={pid}).")
    except ProcessLookupError:
        print("Daemon is not running (stale PID file).")
    except Exception as e:
        print(f"Unknown status: {e}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"

    if cmd == "stop":
        cmd_stop()
    elif cmd == "status":
        cmd_status()
    elif cmd == "start":
        DaemonServer().start()
    else:
        print(f"Usage: {sys.argv[0]} [start|stop|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()
