#!/usr/bin/env python3
"""Shared write helpers for the skill writers (write_report.py, write_story.py). stdlib only.

Lifted unchanged from story-impact's write_report.py (reviewed in WS2):

- checkout_out_dir(root, rel_dir): <root>/ai-context/<rel_dir>, refused (ValueError) when
  <root>/ai-context or this checkout's ai-context is a symlink, or when the folder resolves
  (realpath) outside <root>/ai-context/ or outside this checkout's ai-context/. The checkout is
  located from this file's __file__, never from --root or the cwd. With --root . both anchors are
  the same folder.
- write_nofollow(path, data): write bytes, never through a symlink.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
# tools/impacts -> tools -> repo root
REPO = os.path.dirname(os.path.dirname(HERE))


def _ctx_of(top):
    """realpath of <top>/ai-context, or None when ai-context itself is a symlink."""
    ctx = os.path.join(os.path.realpath(top), "ai-context")
    if os.path.realpath(os.path.join(top, "ai-context")) != ctx:
        return None
    return ctx


def checkout_out_dir(root, rel_dir):
    """Return <root>/ai-context/<rel_dir>, or raise ValueError when it is refused.

    Refused when <root>/ai-context or this checkout's ai-context is a symlink, or when the
    folder resolves (realpath) outside <root>/ai-context/ or outside this checkout's
    ai-context/ (REPO, from __file__). With --root . both anchors are the same folder.
    """
    root_ctx, repo_ctx = _ctx_of(root), _ctx_of(REPO)
    if root_ctx is None or repo_ctx is None:
        raise ValueError("ai-context is a symlink under %s or under the checkout" % root)
    out = os.path.join(root, "ai-context", rel_dir)
    real = os.path.realpath(out)
    if not (real.startswith(root_ctx + os.sep) and real.startswith(repo_ctx + os.sep)):
        raise ValueError("%s resolves outside <root>/ai-context/ or outside the checkout's "
                         "ai-context/" % out)
    return out


def write_nofollow(path, data):
    """Write bytes to path, never through a symlink. O_NOFOLLOW where the platform has it
    (not Windows); the caller's islink check covers the rest."""
    if os.path.islink(path):
        raise OSError("%s is a symlink" % path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o644)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
