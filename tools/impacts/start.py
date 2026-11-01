#!/usr/bin/env python3
"""Start a build session for one story. A human runs this from a real terminal.

Usage:
  start.py <storyId> [--root <repo>]

--root defaults to this checkout (the repo holding this file), never the current directory.

It validates the build package committed at git HEAD through the guard-owned reader,
<checkout>/tools/guard/scope_core.py, writes ai-context/.active-story, and prints the two env entries the human
pastes under "env" in .claude/settings.local.json. It never writes settings. On a fresh clone, where the
git-ignored ai-context/ does not exist yet, it creates it as a real folder; a symlinked ai-context/ is refused.

Order of checks: no TTY (stdin or stdout) exits 2; a missing core exits 2; a package the core refuses exits 1.
The active story is the single impacts/<storyId>-*/ folder at HEAD (git ls-tree -d, so a file of that name does
not count); zero or several refuse (exit 1).

The core is loaded by a path computed from this file and compiled from source into a fresh module, as the guard
does, so no .pyc is read or written beside it. There is deliberately no flag or env var to load another core: a
selectable core would run unseen code. Tests pass a stub through main(argv, core_dir=..., isatty=...).

Exit codes: 0 session started, 1 refused (no or several folders, package refused, cannot write), 2 bad usage,
no terminal, or missing core. Stdlib only. Offline. Writes only ai-context/.active-story (and ai-context/ itself
when it is missing).
"""
import argparse
import os
import re
import subprocess
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import register  # noqa: E402  (hardened git env, shared)
from safe_write import write_nofollow  # noqa: E402

CHECKOUT = os.path.dirname(os.path.dirname(HERE))
DEFAULT_CORE_DIR = os.path.join(CHECKOUT, "tools", "guard")
STORY_RE = re.compile(r"^[A-Z][A-Z0-9]*-[0-9]+$")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
NO_TTY = "run start.py yourself in a terminal; the assistant cannot start a build session"
MISSING_CORE = "scope core not found at %s; it is missing from tools/guard/, and the guard owner must restore it"


class Refused(Exception):
    """Exit 1."""


class Unusable(Exception):
    """Exit 2."""


def _tty():
    return sys.stdin.isatty() and sys.stdout.isatty()


def load_core(path):
    if not os.path.isfile(path):
        raise Unusable(MISSING_CORE % path)
    try:
        # Compiled from source, as the guard loads it: no .pyc is read or written next to the core.
        with open(path, "rb") as fh:
            source = fh.read()
        core = types.ModuleType("scope_core")
        core.__file__ = path
        exec(compile(source, path, "exec"), core.__dict__)
    except Exception as exc:
        raise Unusable("scope core at %s cannot be loaded: %s" % (path, type(exc).__name__))
    if not callable(getattr(core, "read_package", None)):
        raise Unusable("scope core at %s lacks read_package" % path)
    return core


def active_story(root, story):
    """<storyId>-<slug> from the single impacts/<storyId>-*/ folder at HEAD."""
    cmd = ["git", "-C", root] + register.GIT_SAFE + ["ls-tree", "-d", "--name-only", "HEAD", "impacts/"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=register._git_env())
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused("git ls-tree failed: %s" % type(exc).__name__)
    if out.returncode != 0:
        raise Refused("git ls-tree HEAD impacts/ failed under %s" % root)
    names = []
    for line in out.stdout.splitlines():
        name = line.rsplit("/", 1)[-1]
        if name.startswith(story + "-") and SLUG_RE.fullmatch(name[len(story) + 1:]):
            names.append(name)
    if not names:
        raise Refused("no impacts/%s-*/ folder committed at HEAD" % story)
    if len(names) > 1:
        raise Refused("more than one impacts folder at HEAD matches %s: %s" % (story, ", ".join(sorted(names))))
    return names[0]


def write_active(root, active):
    ctx = os.path.join(root, "ai-context")
    if not os.path.lexists(ctx):  # a fresh clone: ai-context/ is git-ignored, so it is not there yet
        try:
            os.mkdir(ctx)
        except OSError as exc:
            raise Refused("cannot create %s: %s" % (ctx, exc))
    if os.path.islink(ctx) or not os.path.isdir(ctx):
        raise Refused("%s is a symlink or not a directory" % ctx)
    try:
        write_nofollow(os.path.join(ctx, ".active-story"), (active + "\n").encode("utf-8"))
    except OSError as exc:
        raise Refused("cannot write ai-context/.active-story: %s" % exc)


def main(argv=None, core_dir=None, isatty=None):
    """core_dir and isatty are for in-process tests only; no command-line flag or env var can set them."""
    ap = argparse.ArgumentParser(description="Start a build session from a committed package.", allow_abbrev=False)
    ap.add_argument("storyId")
    ap.add_argument("--root", default=CHECKOUT, help="repo to read (default: this checkout)")
    args = ap.parse_args(argv)
    try:
        if not (isatty or _tty)():
            raise Unusable(NO_TTY)
        core = load_core(os.path.join(core_dir or DEFAULT_CORE_DIR, "scope_core.py"))
        if not STORY_RE.fullmatch(args.storyId):
            raise Unusable("storyId %r does not match %s" % (args.storyId, STORY_RE.pattern))
        root = os.path.realpath(args.root)
        if not os.path.isdir(root):
            raise Unusable("--root %s is not a directory" % args.root)
        active = active_story(root, args.storyId)
        _, err = core.read_package(root, active)
        if err:
            raise Refused(err)
        write_active(root, active)
    except Unusable as exc:
        sys.stderr.write("start: %s\n" % exc)
        return 2
    except Refused as exc:
        sys.stderr.write("start: %s\n" % exc)
        return 1
    sys.stdout.write('Add under "env" in .claude/settings.local.json the two entries:\n'
                     '  "AI_FRAMEWORK_MODE": "build",\n'
                     '  "AI_FRAMEWORK_STORY": "%s"\n'
                     'Restart the Claude Code session for the mode to take effect. '
                     'Remove both entries to leave build mode.\n' % active)
    return 0


if __name__ == "__main__":
    sys.exit(main())
