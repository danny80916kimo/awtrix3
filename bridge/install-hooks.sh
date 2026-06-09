#!/bin/bash
# install-hooks.sh - Installs Claude Code hook entries in ~/.claude/settings.json
# so that every relevant hook event invokes send-state.sh.
#
# Safe to run multiple times (idempotent). Backs up settings before modifying.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK_SCRIPT="$HERE/send-state.sh"
SETTINGS="$HOME/.claude/settings.json"

# Ensure the settings directory exists
mkdir -p "$(dirname "$SETTINGS")"

# Create settings file if it doesn't exist
if [ ! -f "$SETTINGS" ]; then
    echo '{}' > "$SETTINGS"
fi

# Backup existing settings
cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"

# Use embedded Python to merge hook entries idempotently
/usr/bin/env python3 - "$SETTINGS" "$HOOK_SCRIPT" <<'PYEOF'
import json
import sys

settings_path = sys.argv[1]
hook_script = sys.argv[2]

EVENTS = [
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Notification",
    "PermissionRequest",
    "Elicitation",
    "Stop",
    "StopFailure",
    "PermissionDenied",
    "TaskCompleted",
    "SessionEnd",
]

with open(settings_path, "r") as f:
    settings = json.load(f)

hooks = settings.setdefault("hooks", {})

hook_entry = {
    "type": "command",
    "command": hook_script,
}

for event in EVENTS:
    hook_list = hooks.setdefault(event, [])

    # Check if our hook command is already present (support both old and new format)
    already = any(
        (isinstance(h, dict) and h.get("command") == hook_script)
        or (isinstance(h, dict) and any(
            isinstance(inner, dict) and inner.get("command") == hook_script
            for inner in h.get("hooks", [])
        ))
        for h in hook_list
    )
    if not already:
        hook_list.append({
            "matcher": "",
            "hooks": [hook_entry],
        })

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")

print(f"Installed hooks for {len(EVENTS)} events in {settings_path}")
PYEOF

echo "Done. Backup saved beside settings.json."
