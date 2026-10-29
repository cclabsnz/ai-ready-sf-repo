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
"""
import json
import os
import re
import sys

BLOCKED_CMDS = [
    r"(^|\s|/)sf(dx)?(\s|$)",
    r"\bgit\s+push\b",
    r"\bgit\s+commit\b.*--amend",
    r"\bcurl\b", r"\bwget\b", r"\bssh\b", r"\bscp\b",
    r"\bInvoke-WebRequest\b",
]
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
ALLOWED_WRITE_PREFIXES = ("ai-context/", "index/")
FETCH_ALLOWLIST = ("help.salesforce.com", "developer.salesforce.com", "releasenotes.docs.salesforce.com",
                   "docs.ncino.com")
READ_ONLY_BASH = re.compile(r"^\s*(cat|ls|dir|git\s+(status|diff|log|show|rev-parse)|python3?\s+tools/index/query\.py|py\s+-3\s+tools/index/query\.py)\b")


def block(msg):
    sys.stderr.write(f"BLOCKED by tools/guard/guard.py: {msg}\n")
    sys.exit(2)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        block("could not parse hook input; failing closed")
    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input", {}) or {}
    mode = os.environ.get("AI_FRAMEWORK_MODE", "normal").lower()

    if tool == "Bash":
        cmd = inp.get("command", "")
        for pat in BLOCKED_CMDS:
            if re.search(pat, cmd):
                block(f"command matches blocked pattern {pat!r}. Write numbered steps for a human to run instead.")
        if mode == "advise" and not READ_ONLY_BASH.match(cmd):
            block("framework is in ADVISE mode: only read-only commands are allowed. Output recommendations, do not act.")

    elif tool in WRITE_TOOLS:
        path = (inp.get("file_path") or inp.get("path") or "").replace("\\", "/")
        rel = os.path.relpath(path, os.getcwd()).replace("\\", "/") if os.path.isabs(path) else path
        if mode == "advise":
            block("framework is in ADVISE mode: no writes. Output the content in your reply instead.")
        if not rel.startswith(ALLOWED_WRITE_PREFIXES):
            block(f"write to {rel!r} is outside {ALLOWED_WRITE_PREFIXES}. The build is read-only; hand code to the squad.")

    elif tool == "WebFetch":
        url = inp.get("url", "")
        host = re.sub(r"^https?://", "", url).split("/")[0].lower()
        if not any(host == h or host.endswith("." + h) for h in FETCH_ALLOWLIST):
            block(f"fetch to {host!r} is not on the allowlist {FETCH_ALLOWLIST}.")

    sys.exit(0)


if __name__ == "__main__":
    main()
