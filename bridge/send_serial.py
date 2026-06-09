#!/usr/bin/env python3
"""
Bridge script: reads Claude Code hook JSON from stdin,
maps it to a Claudy state, and sends a JSON line over USB serial.
"""

import json
import os
import sys
import time
from glob import glob

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BAUD = 115200
DEFAULT_MAX_TOKENS = 200_000
LARGE_CONTEXT = 1_000_000
MAX_MSG_LEN = 58

EVENT_STATE = {
    "SessionStart":        "idle",
    "UserPromptSubmit":    "thinking",
    "PreToolUse":          "working",
    "PostToolUse":         "thinking",
    "PostToolUseFailure":  "error",
    "Notification":        "waiting",
    "PermissionRequest":   "waiting",
    "Elicitation":         "waiting",
    "Stop":                "done",
    "StopFailure":         "error",
    "PermissionDenied":    "error",
    "TaskCompleted":       "done",
    "SessionEnd":          "idle",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def brief(s: str) -> str:
    """Truncate a string to MAX_MSG_LEN characters."""
    if s and len(s) > MAX_MSG_LEN:
        return s[:MAX_MSG_LEN]
    return s or ""


def detect_port() -> str:
    """Return the first matching USB serial port, or raise."""
    override = os.environ.get("CLAUDY_SERIAL_PORT")
    if override:
        return override
    candidates = sorted(glob("/dev/cu.usbmodem*") + glob("/dev/cu.usbserial*"))
    if not candidates:
        raise RuntimeError("No USB serial port found")
    return candidates[0]


def calc_context_pct(ev: dict) -> int:
    """
    Read the JSONL transcript and compute context-window usage %.

    Returns 0..100, or -1 if the transcript cannot be read.
    """
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
                # Capture model name if present
                if "model" in obj:
                    model = obj["model"]
                # Look for usage blocks
                usage = obj.get("usage")
                if usage:
                    used = (
                        usage.get("input_tokens", 0)
                        + usage.get("cache_read_input_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)
                    )

        if used == 0:
            return -1

        # Determine context window size
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
    """Build the JSON payload to send over serial."""
    event_name = ev.get("hook_event_name", "")
    state = EVENT_STATE.get(event_name, "idle")

    tool = ""
    msg = ""

    if event_name == "PreToolUse":
        tool = ev.get("tool_name", "")
        # Try to extract a short message from tool_input
        tool_input = ev.get("tool_input", {})
        if isinstance(tool_input, dict):
            # Use file_path, command, or pattern as the message
            msg = (
                tool_input.get("file_path")
                or tool_input.get("command")
                or tool_input.get("pattern")
                or ""
            )
            # For file paths, just keep the basename
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
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        return

    try:
        ev = json.loads(raw)
    except json.JSONDecodeError:
        return

    payload = build_payload(ev)
    event_name = ev.get("hook_event_name", "")

    try:
        import serial  # type: ignore
    except ImportError:
        sys.exit("pyserial is not installed. Run: pip3 install pyserial")

    port = detect_port()

    try:
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = BAUD
        ser.timeout = 2
        ser.dtr = False
        ser.rts = False
        ser.open()

        ser.write((json.dumps(payload, separators=(",", ":")) + "\n").encode())
        ser.flush()

        # For terminal states, wait a beat then send idle
        if event_name in ("Stop", "TaskCompleted"):
            time.sleep(3)
            idle = {"state": "idle"}
            ser.write((json.dumps(idle, separators=(",", ":")) + "\n").encode())
            ser.flush()

        ser.close()
    except Exception:
        pass  # Best-effort; never block Claude Code


if __name__ == "__main__":
    main()
