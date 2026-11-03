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


def _symlink(src, dst):
    """os.symlink, or Skip when this machine cannot create the link (Windows without the privilege)."""
    try:
        os.symlink(src, dst)
    except (OSError, NotImplementedError) as exc:
        raise Skip("symlinks unavailable: %s" % type(exc).__name__)


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
    assert code == 2 and "missing from tools/guard/, and the guard owner must restore it" in err, (code, err)


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
    _symlink(victim, os.path.join(root, "ai-context", ".active-story"))
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


def case_creates_missing_ai_context():
    # A fresh clone has no ai-context/ (it is git-ignored): start.py creates it as a real folder.
    root = make_repo()
    os.rmdir(os.path.join(root, "ai-context"))
    code, out, err = run([STORY, "--root", root], core_dir=stub_dir())
    assert code == 0, (code, err)
    ctx = os.path.join(root, "ai-context")
    assert os.path.isdir(ctx) and not os.path.islink(ctx), ctx
    with open(os.path.join(ctx, ".active-story"), newline="") as fh:
        assert fh.read() == ACTIVE + "\n"


def case_symlinked_ai_context_refused():
    root = make_repo()
    elsewhere = tmpdir()
    os.rmdir(os.path.join(root, "ai-context"))
    _symlink(elsewhere, os.path.join(root, "ai-context"))
    code, out, err = run([STORY, "--root", root], core_dir=stub_dir())
    assert code == 1 and "symlink" in err and out == "", (code, err)
    assert os.listdir(elsewhere) == [], os.listdir(elsewhere)


def case_file_named_like_a_folder_not_counted():
    # git ls-tree -d: a committed file impacts/<storyId>-<slug> is not a package folder.
    root = make_repo()
    with open(os.path.join(root, "impacts", STORY + "-file-slug"), "w") as fh:
        fh.write("not a folder\n")
    git(root, "add", "impacts")
    git(root, "commit", "-q", "-m", "a file")
    code, out, err = run([STORY, "--root", root], core_dir=stub_dir())
    assert code == 0 and "more than one" not in err, (code, err)
    with open(os.path.join(root, "ai-context", ".active-story"), newline="") as fh:
        assert fh.read() == ACTIVE + "\n"


def case_default_root_is_the_checkout_not_cwd():
    # Without --root, start.py reads this checkout, never the current directory. The temp repo holds a
    # package for a story id that this checkout never has, so a cwd-based default would start a session there.
    assert start.CHECKOUT == REPO, start.CHECKOUT
    story, active = "ZZQ-9", "ZZQ-9-not-in-checkout"
    root = make_repo(folders=(active,))
    old = os.getcwd()
    os.chdir(root)
    try:
        code, out, err = run([story], core_dir=stub_dir())
    finally:
        os.chdir(old)
    assert code == 1 and "no impacts/ZZQ-9-*/ folder committed at HEAD" in err and out == "", (code, err)
    assert not os.path.exists(os.path.join(root, "ai-context", ".active-story"))
    p = subprocess.run([sys.executable, START, "--help"], capture_output=True, text=True)
    assert p.returncode == 0 and "default: this checkout" in p.stdout, p.stdout


def case_core_loaded_without_bytecode():
    root = make_repo()
    core_dir = stub_dir()
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = False
    try:
        code, _, err = run([STORY, "--root", root], core_dir=core_dir)
    finally:
        sys.dont_write_bytecode = old
    assert code == 0, err
    assert sorted(os.listdir(core_dir)) == ["scope_core.py"], os.listdir(core_dir)


def case_real_core():
    if not os.path.isfile(REAL_CORE):
        raise Skip("tools/guard/scope_core.py is absent")
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
