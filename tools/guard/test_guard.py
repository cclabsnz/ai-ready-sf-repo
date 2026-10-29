#!/usr/bin/env python3
"""Prove the guard blocks. Run in CI (Linux + Windows) and once per laptop at onboarding.

Each case is a synthetic hook payload and the exit code we require. Every case runs
in a throwaway git repo, so nothing depends on the checkout the tests live in.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
WRAPPER = os.path.join(HERE, "guard.cmd" if os.name == "nt" else "guard.sh")
INTERPRETERS = ("python3", "python", "py")
GIT = ["git", "-c", "user.name=guard-test", "-c", "user.email=guard-test@example.com"]


@dataclass
class Case:
    name: str
    payload: dict | str  # a str is sent raw, so malformed input can be tested
    want: int
    committed_mode: str = "normal"
    env_mode: str | None = None
    dirty: tuple[str, ...] = ()
    files: dict[str, str] = field(default_factory=dict)
    stderr_has: str = ""


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


def write(path, tool="Write"):
    return {"tool_name": tool, "tool_input": {"file_path": path}}


def fetch(url):
    return {"tool_name": "WebFetch", "tool_input": {"url": url}}


CASES = [
    Case("sf org login is blocked", bash("sf org login web -a uat"), 2),
    Case("sfdx deploy is blocked", bash("sfdx force:source:deploy -p force-app"), 2),
    Case("git push is blocked", bash("git push origin feature/x"), 2),
    Case("curl is blocked", bash("curl https://example.com"), 2),
    Case("git status is allowed", bash("git status"), 0),
    Case("query helper is allowed", bash("python3 tools/index/query.py stamp"), 0),
    Case("write under ai-context is allowed", write("ai-context/123-x/impact.md"), 0),
    Case("write under force-app is blocked", write("force-app/main/default/classes/A.cls"), 2),
    Case("write escaping ai-context via .. is blocked", write("ai-context/../force-app/main/default/classes/A.cls"), 2),
    Case("write escaping ai-context via ..\\ is blocked", write("ai-context\\..\\force-app\\main\\default\\classes\\A.cls", "Edit"), 2),
    Case("write under ./ai-context is allowed", write("./ai-context/123-x/impact.md"), 0),
    Case("fetch to salesforce docs is allowed", fetch("https://help.salesforce.com/s/"), 0),
    Case("fetch to a blog is blocked", fetch("https://someblog.example/post"), 2),
    Case("advise mode blocks writes", write("ai-context/x/y.md"), 2, committed_mode="normal", env_mode="advise"),
    Case("advise mode allows git status", bash("git status"), 0, committed_mode="normal", env_mode="advise"),
    Case("malformed hook JSON fails closed", "not json", 2, stderr_has="failing closed"),
]

# A payload the guard ALLOWS, so exit 2 can only come from the wrapper's fail-closed branch.
NO_PYTHON_CASE = Case("no interpreter fails closed", bash("git status"), 2, stderr_has="no Python interpreter found")
# The guard allows this payload when its policy is present, so exit 2 can only come from the missing file.
NO_POLICY_CASE = Case("missing policy fails closed", bash("git status"), 2, stderr_has="policy")
# A payload the guard blocks, with nowhere to write the message: the exit code must still be 2.
BAD_STDERR_CASES = [
    ("closed", Case("block with stderr closed still exits 2", bash("curl https://example.com"), 2)),
    ("broken", Case("block with stderr a broken pipe still exits 2", bash("curl https://example.com"), 2)),
]
# Run from a project whose ai-context/ holds symlinks into force-app/ (see add_symlinks).
SYMLINK_CASES = [
    Case("write in a temp repo's ai-context is allowed", write("ai-context/x/y.md"), 0, files={"force-app/A.cls": ""}),
    Case("write through a symlinked dir out of ai-context is blocked", write("ai-context/fa/A.cls"), 2, files={"force-app/A.cls": ""}),
    Case("edit of a symlinked file out of ai-context is blocked", write("ai-context/link.cls", "Edit"), 2, files={"force-app/A.cls": ""}),
]


def git(project, *args):
    subprocess.run(GIT + list(args), cwd=project, check=True, capture_output=True)


def put(project, rel, text):
    path = os.path.join(project, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def make_project(committed_mode, files):
    """A throwaway committed git repo shaped like the real one."""
    project = tempfile.mkdtemp(prefix="guard-proj-")
    try:
        subprocess.run(["git", "init", "-q"], cwd=project, check=True, capture_output=True)
        put(project, ".claude/settings.json", json.dumps({"env": {"AI_FRAMEWORK_MODE": committed_mode}}))
        for rel, text in files.items():
            put(project, rel, text)
        for d in ("ai-context", "index", "force-app/main/default/classes"):
            os.makedirs(os.path.join(project, *d.split("/")), exist_ok=True)
        for keep in ("tools/guard/.keep", ".github/workflows/.keep"):
            put(project, keep, "")
        git(project, "add", "-A")
        git(project, "commit", "-q", "-m", "init")
    except BaseException:
        shutil.rmtree(project, ignore_errors=True)
        raise
    return project


def make_dirty(project, dirty):
    for rel in dirty:
        path = os.path.join(project, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write("dirty\n")


def case_env(project, env_mode):
    env = dict(os.environ)
    env.pop("AI_FRAMEWORK_MODE", None)
    env["CLAUDE_PROJECT_DIR"] = project
    if env_mode is not None:
        env["AI_FRAMEWORK_MODE"] = env_mode
    return env


def send(wrapper, payload, env, cwd):
    data = payload if isinstance(payload, str) else json.dumps(payload)
    p = subprocess.run([wrapper], input=data.encode(), capture_output=True, env=env, cwd=cwd)
    return p.returncode, p.stderr.decode()


def run_case(case):
    project = make_project(case.committed_mode, case.files)
    try:
        make_dirty(project, case.dirty)
        return send(WRAPPER, case.payload, case_env(project, case.env_mode), project)
    finally:
        shutil.rmtree(project, ignore_errors=True)


def add_symlinks(project):
    """ai-context/fa -> force-app/ and ai-context/link.cls -> force-app/A.cls."""
    os.symlink(os.path.join(project, "force-app"), os.path.join(project, "ai-context", "fa"), target_is_directory=True)
    os.symlink(os.path.join(project, "force-app", "A.cls"), os.path.join(project, "ai-context", "link.cls"))


def run_symlink_case(case):
    project = make_project(case.committed_mode, case.files)
    try:
        add_symlinks(project)
        return send(WRAPPER, case.payload, case_env(project, case.env_mode), project)
    finally:
        shutil.rmtree(project, ignore_errors=True)


def run_without_python(case):
    """Run the wrapper with a PATH that holds the shell tools it needs and no Python."""
    shim = tempfile.mkdtemp(prefix="guard-nopy-")
    project = make_project(case.committed_mode, case.files)
    try:
        if os.name != "nt":
            # guard.sh needs sh (via its /usr/bin/env shebang) and dirname; link only those.
            for tool in ("sh", "dirname"):
                os.symlink(shutil.which(tool), os.path.join(shim, tool))
        # On Windows the shim stays empty: `where` cannot resolve, so guard.cmd falls through.
        found = [py for py in INTERPRETERS if shutil.which(py, path=shim)]
        if found:
            return None, f"test setup invalid: {found} still on PATH"
        env = dict(case_env(project, case.env_mode), PATH=shim)
        return send(WRAPPER, case.payload, env, project)
    finally:
        shutil.rmtree(shim, ignore_errors=True)
        shutil.rmtree(project, ignore_errors=True)


def run_without_policy(case):
    """Copy the wrapper and guard.py, but not policy.json, and run that copy."""
    copy = tempfile.mkdtemp(prefix="guard-nopolicy-")
    project = make_project(case.committed_mode, case.files)
    try:
        for name in (os.path.basename(WRAPPER), "guard.py"):
            shutil.copy(os.path.join(HERE, name), os.path.join(copy, name))
        wrapper = os.path.join(copy, os.path.basename(WRAPPER))
        os.chmod(wrapper, 0o755)
        return send(wrapper, case.payload, case_env(project, case.env_mode), project)
    finally:
        shutil.rmtree(copy, ignore_errors=True)
        shutil.rmtree(project, ignore_errors=True)


def run_bad_stderr(case, kind):
    """Run a blocking payload with stderr closed, or a pipe whose read end is closed."""
    project = make_project(case.committed_mode, case.files)
    r = w = None
    try:
        kwargs = {}
        if kind == "closed":
            kwargs["preexec_fn"] = lambda: os.close(2)
        else:
            r, w = os.pipe()
            os.close(r)
            kwargs["stderr"] = w
        data = json.dumps(case.payload).encode()
        p = subprocess.run([WRAPPER], input=data, stdout=subprocess.PIPE, env=case_env(project, None), cwd=project, **kwargs)
        return p.returncode, ""
    finally:
        if w is not None:
            os.close(w)
        shutil.rmtree(project, ignore_errors=True)


def report(case, code, err):
    ok = code == case.want and case.stderr_has in err
    note = "" if ok else f" stderr: {err.strip()!r}"
    print(f"[{'PASS' if ok else 'FAIL'}] {case.name}: exit {code} (want {case.want}){note}")
    return ok


def main():
    results = []
    for case in CASES:
        results.append(report(case, *run_case(case)))
    results.append(report(NO_PYTHON_CASE, *run_without_python(NO_PYTHON_CASE)))
    results.append(report(NO_POLICY_CASE, *run_without_policy(NO_POLICY_CASE)))
    skipped = 0
    if os.name == "nt":  # needs fd-level stderr control that Windows subprocess cannot give
        skipped += len(BAD_STDERR_CASES)
        print(f"[SKIP] {len(BAD_STDERR_CASES)} bad-stderr cases: POSIX only")
    else:
        for kind, case in BAD_STDERR_CASES:
            results.append(report(case, *run_bad_stderr(case, kind)))
    probe = tempfile.mkdtemp(prefix="guard-link-probe-")
    try:
        os.symlink(probe, os.path.join(probe, "probe"))
        can_link = True
    except OSError as e:  # Windows without Developer Mode or admin cannot create symlinks
        can_link = False
        skipped += len(SYMLINK_CASES)
        print(f"[SKIP] {skipped} symlink cases: cannot create symlinks here ({e})")
    finally:
        shutil.rmtree(probe, ignore_errors=True)
    if can_link:
        for case in SYMLINK_CASES:
            results.append(report(case, *run_symlink_case(case)))
    failures = results.count(False)
    print(f"\n{len(results) - failures} passed, {failures} failed" + (f", {skipped} skipped" if skipped else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
