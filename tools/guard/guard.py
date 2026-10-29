#!/usr/bin/env python3
"""PreToolUse guard. Reads the hook JSON from stdin, exits 2 to block.

Exit codes (Claude Code semantics):
  0  allow
  2  block; stderr is shown to the model
  anything else is treated as a non-blocking warning, so this script
  never deliberately exits with another code.

Policy:
  - No org or network commands: sf, sfdx, git push, curl, wget, ssh.
  - Writes only under ai-context/ and index/.
  - WebFetch only to the allowlist.
  - AI_FRAMEWORK_MODE=advise blocks every write and every Bash call
    except read-only ones (the kill switch).

The rules live in policy.json next to this file. Any internal error,
including an unreadable policy, blocks (exit 2): the hook runner treats
every other exit code as a warning and would let the call through.
"""
import json
import os
import re
import sys

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
# Found through __file__ because the wrapper runs us with -I (no cwd, no script dir on sys.path).
POLICY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "policy.json")


def block(msg):
    try:
        sys.stderr.write(f"BLOCKED by tools/guard/guard.py: {msg}\n")
        sys.stderr.flush()
    except BaseException:
        # Closed or broken stderr must not turn a block into another exit code. _exit skips
        # the interpreter's shutdown flush, which would fail again and exit 120.
        os._exit(2)
    sys.exit(2)


def load_policy(path):
    try:
        with open(path, encoding="utf-8") as f:
            policy = json.load(f)
    except (OSError, ValueError) as e:
        block(f"policy unreadable: {e}; failing closed")
    if not isinstance(policy, dict) or policy.get("version") != 1:
        block("policy unreadable: version is not 1; failing closed")
    return policy


def project_dir():
    return os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def rel_path(root, path):
    """Path relative to root with ".." and symlinks resolved, so neither can carry a write out of ai-context/."""
    try:
        return os.path.relpath(os.path.realpath(os.path.join(root, path)), root).replace("\\", "/")
    except ValueError:  # Windows: path is on a different drive from the repo
        return None


def main():
    policy = load_policy(POLICY_PATH)
    try:
        payload = json.load(sys.stdin)
    except Exception:
        block("could not parse hook input; failing closed")
    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input", {}) or {}
    mode = os.environ.get("AI_FRAMEWORK_MODE", "normal").lower()

    if tool == "Bash":
        cmd = inp.get("command", "")
        for pat in policy["blocked_commands"]:
            if re.search(pat, cmd):
                block(f"command matches blocked pattern {pat!r}. Write numbered steps for a human to run instead.")
        read_only = re.compile(r"^\s*(" + "|".join(policy["bash_groups"]["read_only"]) + r")\b")
        if mode == "advise" and not read_only.match(cmd):
            block("framework is in ADVISE mode: only read-only commands are allowed. Output recommendations, do not act.")

    elif tool in WRITE_TOOLS:
        path = (inp.get("file_path") or inp.get("path") or "").replace("\\", "/")
        rel = rel_path(project_dir(), path)
        if rel is None:
            block(f"write to {path!r} is on a different drive from the repo.")
        if mode == "advise":
            block("framework is in ADVISE mode: no writes. Output the content in your reply instead.")
        allowed = tuple(policy["modes"]["normal"]["writes"])
        if not rel.startswith(allowed):
            block(f"write to {rel!r} is outside {allowed}. The build is read-only; hand code to the squad.")

    elif tool == "WebFetch":
        url = inp.get("url", "")
        host = re.sub(r"^https?://", "", url).split("/")[0].lower()
        allowlist = policy["fetch_allowlist"]
        if not any(host == h or host.endswith("." + h) for h in allowlist):
            block(f"fetch to {host!r} is not on the allowlist {tuple(allowlist)}.")

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        block("internal error; failing closed")
