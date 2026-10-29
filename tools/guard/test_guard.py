#!/usr/bin/env python3
"""Prove the guard blocks. Run in CI (Linux + Windows) and once per laptop at onboarding.

Each case is a synthetic hook payload and the exit code we require.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

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
    ("write escaping ai-context via .. is blocked", {"tool_name": "Write", "tool_input": {"file_path": "ai-context/../force-app/main/default/classes/A.cls"}}, 2),
    ("write escaping ai-context via ..\\ is blocked", {"tool_name": "Edit", "tool_input": {"file_path": "ai-context\\..\\force-app\\main\\default\\classes\\A.cls"}}, 2),
    ("write under ./ai-context is allowed", {"tool_name": "Write", "tool_input": {"file_path": "./ai-context/123-x/impact.md"}}, 0),
    ("fetch to salesforce docs is allowed", {"tool_name": "WebFetch", "tool_input": {"url": "https://help.salesforce.com/s/"}}, 0),
    ("fetch to a blog is blocked", {"tool_name": "WebFetch", "tool_input": {"url": "https://someblog.example/post"}}, 2),
]
ADVISE_CASES = [
    ("advise mode blocks writes", {"tool_name": "Write", "tool_input": {"file_path": "ai-context/x/y.md"}}, 2),
    ("advise mode allows git status", {"tool_name": "Bash", "tool_input": {"command": "git status"}}, 0),
]
# A payload the guard ALLOWS, so exit 2 can only come from the wrapper's fail-closed branch.
NO_PYTHON_CASE = ("no interpreter fails closed", {"tool_name": "Bash", "tool_input": {"command": "git status"}}, 2)
INTERPRETERS = ("python3", "python", "py")
# Run from a throwaway repo whose ai-context/ holds symlinks into force-app/ (see make_symlink_repo).
SYMLINK_CASES = [
    ("write in a temp repo's ai-context is allowed", {"tool_name": "Write", "tool_input": {"file_path": "ai-context/x/y.md"}}, 0),
    ("write through a symlinked dir out of ai-context is blocked", {"tool_name": "Write", "tool_input": {"file_path": "ai-context/fa/A.cls"}}, 2),
    ("edit of a symlinked file out of ai-context is blocked", {"tool_name": "Edit", "tool_input": {"file_path": "ai-context/link.cls"}}, 2),
]


def run(payload, env, cwd=None):
    p = subprocess.run([WRAPPER], input=json.dumps(payload).encode(), capture_output=True, env=env, cwd=cwd)
    return p.returncode, p.stderr.decode()


def make_symlink_repo(repo):
    """ai-context/fa -> force-app/ and ai-context/link.cls -> force-app/A.cls."""
    os.makedirs(os.path.join(repo, "ai-context"))
    os.makedirs(os.path.join(repo, "force-app"))
    target = os.path.join(repo, "force-app", "A.cls")
    open(target, "w").close()
    os.symlink(os.path.join(repo, "force-app"), os.path.join(repo, "ai-context", "fa"), target_is_directory=True)
    os.symlink(target, os.path.join(repo, "ai-context", "link.cls"))


def run_without_python(payload, base_env):
    """Run the wrapper with a PATH that holds the shell tools it needs and no Python."""
    shim = tempfile.mkdtemp(prefix="guard-nopy-")
    try:
        if os.name != "nt":
            # guard.sh needs sh (via its /usr/bin/env shebang) and dirname; link only those.
            for tool in ("sh", "dirname"):
                os.symlink(shutil.which(tool), os.path.join(shim, tool))
        # On Windows the shim stays empty: `where` cannot resolve, so guard.cmd falls through.
        found = [py for py in INTERPRETERS if shutil.which(py, path=shim)]
        if found:
            return None, f"test setup invalid: {found} still on PATH"
        return run(payload, dict(base_env, PATH=shim))
    finally:
        shutil.rmtree(shim, ignore_errors=True)


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
    name, payload, want = NO_PYTHON_CASE
    code, err = run_without_python(payload, base_env)
    ok = code == want and "no Python interpreter found" in err
    failures += 0 if ok else 1
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: exit {code} (want {want})" + ("" if ok else f" stderr: {err.strip()}"))
    skipped = 0
    repo = tempfile.mkdtemp(prefix="guard-link-")
    try:
        try:
            make_symlink_repo(repo)
        except OSError as e:  # Windows without Developer Mode or admin cannot create symlinks
            skipped = len(SYMLINK_CASES)
            print(f"[SKIP] {skipped} symlink cases: cannot create symlinks here ({e})")
        else:
            for name, payload, want in SYMLINK_CASES:
                code, err = run(payload, base_env, cwd=repo)
                ok = code == want
                failures += 0 if ok else 1
                print(f"[{'PASS' if ok else 'FAIL'}] {name}: exit {code} (want {want})")
    finally:
        shutil.rmtree(repo, ignore_errors=True)
    total = len(CASES) + len(ADVISE_CASES) + 1 + len(SYMLINK_CASES) - skipped
    print(f"\n{total - failures} passed, {failures} failed" + (f", {skipped} skipped" if skipped else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
