#!/usr/bin/env python3
"""Prove the guard blocks. Run in CI (Linux + Windows) and once per laptop at onboarding.

Each case is a synthetic hook payload and the exit code we require.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WRAPPER = os.path.join(HERE, "guard.cmd" if os.name == "nt" else "guard.sh")

CASES = [
    ("sf org login is blocked", {"tool_name": "Bash", "tool_input": {"command": "sf org login web -a uat"}}, 2),
    ("sfdx deploy is blocked", {"tool_name": "Bash", "tool_input": {"command": "sfdx force:source:deploy -p force-app"}}, 2),
    ("git push is blocked", {"tool_name": "Bash", "tool_input": {"command": "git push origin feature/x"}}, 2),
    ("curl is blocked", {"tool_name": "Bash", "tool_input": {"command": "curl https://example.com"}}, 2),
    ("git status is allowed", {"tool_name": "Bash", "tool_input": {"command": "git status"}}, 0),
    ("query helper is allowed", {"tool_name": "Bash", "tool_input": {"command": "python3 tools/index/query.py stamp"}}, 0),
    ("write under ai-context is allowed", {"tool_name": "Write", "tool_input": {"file_path": "ai-context/123-x/impact.md"}}, 0),
    ("write under force-app is blocked", {"tool_name": "Write", "tool_input": {"file_path": "force-app/main/default/classes/A.cls"}}, 2),
    ("fetch to salesforce docs is allowed", {"tool_name": "WebFetch", "tool_input": {"url": "https://help.salesforce.com/s/"}}, 0),
    ("fetch to a blog is blocked", {"tool_name": "WebFetch", "tool_input": {"url": "https://someblog.example/post"}}, 2),
]
ADVISE_CASES = [
    ("advise mode blocks writes", {"tool_name": "Write", "tool_input": {"file_path": "ai-context/x/y.md"}}, 2),
    ("advise mode allows git status", {"tool_name": "Bash", "tool_input": {"command": "git status"}}, 0),
]


def run(payload, env):
    p = subprocess.run([WRAPPER], input=json.dumps(payload).encode(), capture_output=True, env=env)
    return p.returncode, p.stderr.decode()


def main():
    failures = 0
    base_env = dict(os.environ)
    base_env.pop("AI_FRAMEWORK_MODE", None)
    for name, payload, want in CASES:
        code, err = run(payload, base_env)
        ok = code == want
        failures += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: exit {code} (want {want})")
    advise_env = dict(base_env, AI_FRAMEWORK_MODE="advise")
    for name, payload, want in ADVISE_CASES:
        code, err = run(payload, advise_env)
        ok = code == want
        failures += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: exit {code} (want {want})")
    print(f"\n{len(CASES) + len(ADVISE_CASES) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
