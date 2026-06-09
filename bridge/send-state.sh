#!/bin/bash
# Shell wrapper: reads stdin, pipes to send_serial.py in background, exits immediately.
# This ensures the hook never blocks Claude Code.
INPUT=$(cat)
HERE="$(cd "$(dirname "$0")" && pwd)"
(printf '%s' "$INPUT" | /usr/bin/env python3 "$HERE/claudy_client.py" >/dev/null 2>&1) &
disown
exit 0
