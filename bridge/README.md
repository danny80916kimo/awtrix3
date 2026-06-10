# Claudy — Claude Code status display for AWTRIX3

Claudy turns an AWTRIX3 (Ulanzi TC001 / ESP32 LED matrix) into a live status
indicator for [Claude Code](https://claude.com/claude-code). A ghost animates to
show what Claude is doing — thinking, working, waiting, error, done — alongside
the current context-window usage as a percentage and a progress bar.

```
┌──────────────────────┐
│  👻   42%  ▇▇▇▅░░░    │   ← ghost = state, % + bar = context usage
└──────────────────────┘
```

## How it works

Claude Code fires **hook events** at every step of a session. A small bridge on
your Mac maps each event to a Claudy state and pushes it to the board over USB
serial.

```
Claude Code ──hook event (JSON on stdin)──► send-state.sh
                                                  │  (fire-and-forget, never blocks Claude)
                                                  ▼
                                          claudy_client.py
                                                  │  Unix socket  /tmp/claudy.sock
                                                  ▼
                                          claudy_daemon.py ──USB serial 115200──► AWTRIX3
                                          (persistent connection,                  ClaydyApp
                                           auto-reconnect)                         (firmware)
```

Using a **daemon** with one persistent serial connection avoids the ~6 s ESP32
reboot that happens every time the serial port is opened (the CH340 toggles
DTR/RTS). The hook itself returns instantly so Claude Code is never slowed down.

> A daemon-less fallback, `send_serial.py`, opens the port per-event. It works but
> resets the board on every hook, so the daemon is strongly preferred.

## Files

| File | Role |
|---|---|
| `claudy_daemon.py` | Long-running bridge. Holds the serial connection, listens on a Unix socket, maps events → payloads. `start` / `stop` / `status`. |
| `claudy_client.py` | Tiny client. Reads hook JSON from stdin, forwards it to the daemon socket. Fails silently if the daemon is down. |
| `send-state.sh` | Hook entry point. Wraps the client in a backgrounded subshell so the hook returns immediately. |
| `install-hooks.sh` | Idempotently registers `send-state.sh` for all relevant hook events in `~/.claude/settings.json` (backs up first). |
| `send_serial.py` | Standalone per-event sender (daemon-less fallback). |
| `test-serial.sh` | Cycles the board through every state for a visual check. |

The firmware lives in `../src/ClaydyApp.{h,cpp}`; serial input is parsed in
`../src/main.cpp` (`processSerialInput`).

## Setup (Mac side)

1. **Install pyserial** (into the same `python3` the hooks will use — `/usr/bin/env python3`):

   ```bash
   pip3 install pyserial
   python3 -c "import serial; print(serial.__version__)"   # verify
   ```

2. **Register the hooks** in `~/.claude/settings.json` (idempotent, makes a backup):

   ```bash
   ./install-hooks.sh
   ```

3. **Start the daemon** (plug the AWTRIX3 in via USB first):

   ```bash
   python3 claudy_daemon.py start          # foreground; prepend nohup/& to background
   ```

   To run it detached:

   ```bash
   nohup python3 claudy_daemon.py start > /tmp/claudy.log 2>&1 &
   ```

That's it — start a Claude Code session and the ghost should come alive.

## Firmware side

Build and flash the AWTRIX3 firmware (PlatformIO) as usual:

```bash
pio run -t upload
```

Claudy activates automatically when the board receives a state JSON line over
serial, and falls back to the normal AWTRIX apps after 60 s of silence
(`IDLE_TIMEOUT`).

## Daemon management

```bash
python3 claudy_daemon.py status   # is it running?
python3 claudy_daemon.py stop     # SIGTERM, cleans up socket + PID
python3 claudy_daemon.py start    # start
```

Runtime files: socket `/tmp/claudy.sock`, PID `/tmp/claudy.pid`. Only one daemon
runs at a time (it refuses to start if a live PID is found).

> **Not persistent across reboots.** The daemon is a plain background process. To
> auto-start on login and restart on crash, wrap it in a launchd `.plist`.

## Configuration (environment variables)

Set these in the daemon's environment (e.g. before `start`):

| Variable | Default | Meaning |
|---|---|---|
| `CLAUDY_SERIAL_PORT` | auto-detect | Force a specific port, e.g. `/dev/cu.usbserial-10`. Otherwise the first `cu.usbmodem*` / `cu.usbserial*` is used. |
| `CLAUDY_MAX_TOKENS` | `200000` | Context-window size used to compute the percentage. Auto-bumps to `1000000` if usage exceeds 200k or the model id contains `[1m]`. |

## State mapping

| Hook event | Claudy state |
|---|---|
| `SessionStart`, `SessionEnd` | idle |
| `UserPromptSubmit`, `PostToolUse` | thinking |
| `PreToolUse` | working *(+ tool name & target)* |
| `Notification`, `PermissionRequest`, `Elicitation` | waiting |
| `PostToolUseFailure`, `StopFailure`, `PermissionDenied` | error |
| `Stop`, `TaskCompleted` | done → idle after 3 s |

The serial payload is a compact JSON line, e.g.
`{"state":"working","tool":"Edit","msg":"main.cpp","pct":42}`.

## Testing

Cycle the board through every state without Claude Code:

```bash
./test-serial.sh                       # auto-detects port
./test-serial.sh /dev/cu.usbserial-10  # or pass it explicitly
```

End-to-end test of the hook chain (daemon must be running):

```bash
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"echo hi"}}' \
  | ./send-state.sh
tail -f /tmp/claudy.log   # should log "Sent: ..."
```

## Troubleshooting

- **Ghost never appears** — confirm the daemon is running (`status`) and the
  serial port is connected (`ls /dev/cu.usbserial* /dev/cu.usbmodem*`). Check
  `/tmp/claudy.log` for `Serial connected:` and `Sent:` lines.
- **`pyserial not installed`** in the log — you installed pyserial into a
  different interpreter than `/usr/bin/env python3`. Match them up.
- **`Another daemon is already running`** — a live PID exists. `stop` first, or
  remove a stale `/tmp/claudy.pid`.
- **Board keeps rebooting** — you're using `send_serial.py` (per-event open)
  instead of the daemon. Switch to the daemon.
- **Hooks not firing** — re-run `./install-hooks.sh` and check the `hooks`
  block in `~/.claude/settings.json`.

## Uninstall

Stop the daemon and remove the hook entries from `~/.claude/settings.json`
(delete the blocks whose `command` ends in `send-state.sh`). A timestamped
backup `settings.json.bak.*` was saved next to it by the installer.
