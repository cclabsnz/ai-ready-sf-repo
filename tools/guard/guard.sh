#!/usr/bin/env sh
# Cross-platform wrapper: find an interpreter or FAIL CLOSED (exit 2).
# Claude Code treats any exit code other than 0/2 as a non-blocking warning,
# so "python3: command not found" (127) would silently allow the tool call.
DIR="$(cd "$(dirname "$0")" && pwd)"
for py in python3 python py; do
  if command -v "$py" >/dev/null 2>&1; then
    if [ "$py" = "py" ]; then exec py -3 -I "$DIR/guard.py"; else exec "$py" -I "$DIR/guard.py"; fi
  fi
done
echo "BLOCKED: no Python interpreter found for the guard; failing closed" >&2
exit 2
