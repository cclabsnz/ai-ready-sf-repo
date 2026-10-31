#!/usr/bin/env python3
"""Tests for start.py: CLI plumbing only, against a stub core written into a temp dir.

start.py has no flag or env var that selects a core, so the stub is injected in-process through
main(argv, core_dir=..., isatty=...). One case runs the real script as a subprocess with pipes (no TTY).
One case runs the real tools/guard/scope_core.py and prints SKIP while that file is absent.

Run: python3 tools/impacts/test_start.py
"""
import atexit
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import start  # noqa: E402

START = os.path.join(HERE, "start.py")
REAL_CORE = os.path.join(REPO, "tools", "guard", "scope_core.py")
CTX = os.path.join(REPO, "ai-context")
STORY = "DEMO-202"
ACTIVE = "DEMO-202-example-slug"


class Skip(Exception):
    pass


STUB = '''
import os
def read_package(root, active):
    path = os.path.join(root, "impacts", active, "build-package.json")
    if not os.path.isfile(path):
        return None, "stub: no package for " + active
    return {"storyId": active}, None
'''

_made = []
atexit.register(lambda: [shutil.rmtree(p, True) for p in _made])


def tmpdir():
    os.makedirs(CTX, exist_ok=True)
    d = tempfile.mkdtemp(prefix="start_", dir=CTX)
    _made.append(d)
    return d


def git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "-c", "commit.gpgsign=false"] + list(args), check=True, capture_output=True, env=env)


def make_repo(folders=(ACTIVE,), commit=True):
    root = tmpdir()
    git(root, "init", "-q")
    os.makedirs(os.path.join(root, "ai-context"))
    for f in folders:
        os.makedirs(os.path.join(root, "impacts", f))
        with open(os.path.join(root, "impacts", f, "build-package.json"), "w") as fh:
            fh.write("{}\n")
    if commit:
        git(root, "add", "impacts")
        git(root, "commit", "-q", "-m", "package")
    return root


def stub_dir():
    d = tmpdir()
    with open(os.path.join(d, "scope_core.py"), "w") as fh:
        fh.write(STUB)
    return d


def run(argv, core_dir=None, tty=True):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = start.main(argv, core_dir=core_dir, isatty=lambda: tty)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def case_refuses_without_tty():
    root = make_repo()
    p = subprocess.run([sys.executable, START, STORY, "--root", root], capture_output=True, text=True, input="")
    assert p.returncode == 2, p
    assert "run start.py yourself in a terminal; the assistant cannot start a build session" in p.stderr
    assert not os.path.exists(os.path.join(root, "ai-context", ".active-story"))


def case_writes_active_story_and_prints_lines():
    root = make_repo()
    code, out, err = run([STORY, "--root", root], core_dir=stub_dir())
    assert code == 0, (code, err)
    with open(os.path.join(root, "ai-context", ".active-story"), newline="") as fh:
        assert fh.read() == ACTIVE + "\n"
    assert '"AI_FRAMEWORK_MODE": "build"' in out and '"AI_FRAMEWORK_STORY": "%s"' % ACTIVE in out, out
    assert ".claude/settings.local.json" in out and '"env"' in out
    assert ("Restart the Claude Code session for the mode to take effect. "
            "Remove both entries to leave build mode.") in out


def case_refuses_uncommitted_package():
    root = make_repo(commit=False)
    git(root, "commit", "-q", "--allow-empty", "-m", "empty")
    code, out, err = run([STORY, "--root", root], core_dir=stub_dir())
    assert code == 1 and "HEAD" in err and out == "", (code, err)
    assert not os.path.exists(os.path.join(root, "ai-context", ".active-story"))


def case_refuses_two_folders():
    root = make_repo(folders=(ACTIVE, STORY + "-other-slug"))
    code, out, err = run([STORY, "--root", root], core_dir=stub_dir())
    assert code == 1 and "more than one" in err, (code, err)
    assert not os.path.exists(os.path.join(root, "ai-context", ".active-story"))


def case_core_missing_exits_2():
    root = make_repo()
    code, out, err = run([STORY, "--root", root], core_dir=tmpdir())
    assert code == 2 and "apply the WS8 guard patch (ai-context/ws8/patches)" in err, (code, err)


def case_core_error_exits_1():
    root = make_repo()
    os.remove(os.path.join(root, "impacts", ACTIVE, "build-package.json"))
    code, out, err = run([STORY, "--root", root], core_dir=stub_dir())
    assert code == 1 and "stub: no package" in err, (code, err)


def case_never_writes_settings():
    root = make_repo()
    code, _, err = run([STORY, "--root", root], core_dir=stub_dir())
    assert code == 0, err
    assert not os.path.exists(os.path.join(root, ".claude")), "start.py touched .claude/"


def case_symlinked_active_story_refused():
    root = make_repo()
    victim = os.path.join(tmpdir(), "victim.txt")
    with open(victim, "w") as fh:
        fh.write("keep\n")
    os.symlink(victim, os.path.join(root, "ai-context", ".active-story"))
    code, _, err = run([STORY, "--root", root], core_dir=stub_dir())
    assert code == 1 and "symlink" in err, (code, err)
    with open(victim) as fh:
        assert fh.read() == "keep\n"


def case_core_dir_flag_rejected():
    root = make_repo()
    code, out, err = run([STORY, "--root", root, "--core-dir", stub_dir()], core_dir=stub_dir())
    assert code == 2 and "unrecognized arguments" in err, (code, err)
    p = subprocess.run([sys.executable, START, STORY, "--root", root, "--core-dir", "x"],
                       capture_output=True, text=True)
    assert p.returncode == 2, p


def case_real_core():
    if not os.path.isfile(REAL_CORE):
        raise Skip("tools/guard/scope_core.py absent (guard patch not applied)")
    root = make_repo()
    code, out, err = run([STORY, "--root", root])
    assert code in (0, 1) and "Traceback" not in err, (code, err)


def main():
    cases = [(n, f) for n, f in sorted(globals().items()) if n.startswith("case_")]
    failed = skipped = 0
    for name, fn in cases:
        try:
            fn()
            print("[PASS] %s" % name)
        except Skip as exc:
            skipped += 1
            print("SKIP %s: %s" % (name, exc))
        except Exception as exc:
            failed += 1
            print("[FAIL] %s: %s: %s" % (name, type(exc).__name__, str(exc)[:500]))
    print("%d passed, %d failed, %d skipped" % (len(cases) - failed - skipped, failed, skipped))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
