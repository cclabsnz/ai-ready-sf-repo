#!/bin/sh
# Cross-platform wrapper: find an interpreter or FAIL CLOSED (exit 2).
# Claude Code treats any exit code other than 0/2 as a non-blocking warning,
# so "python3: command not found" (127) would silently allow the tool call.
# Shell builtins only: with an empty PATH, `env` and `dirname` would not resolve.
case "$0" in */*) DIR="$(cd "${0%/*}" && pwd)" ;; *) DIR="$(cd . && pwd)" ;; esac
if [ ! -r "$DIR/guard.py" ]; then
  echo "BLOCKED: tools/guard/guard.py not found or unreadable; failing closed" >&2
  exit 2
fi
# No exec: a broken interpreter (pyenv shim, Xcode stub) exits 1 or 127, which must become 2.
for py in python3 python py; do
  if command -v "$py" >/dev/null 2>&1; then
    if [ "$py" = "py" ]; then py -3 -I "$DIR/guard.py"; else "$py" -I "$DIR/guard.py"; fi
    rc=$?
    [ "$rc" -eq 0 ] || [ "$rc" -eq 2 ] || rc=2
    exit "$rc"
  fi
done
echo "BLOCKED: no Python interpreter found for the guard; failing closed" >&2
exit 2
