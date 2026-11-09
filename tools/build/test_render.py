#!/usr/bin/env python3
"""Tests for render.py --check. Temp trees go under <checkout>/ai-context; framework/ is only read.

Run: python3 tools/build/test_render.py
"""
import filecmp
import importlib.util
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
_spec = importlib.util.spec_from_file_location("render", os.path.join(HERE, "render.py"))
render = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render)

# ai-context/ is git-ignored, so a fresh clone (and every CI runner) starts without it.
os.makedirs(os.path.join(REPO, "ai-context"), exist_ok=True)
TMP = tempfile.mkdtemp(prefix="render_", dir=os.path.join(REPO, "ai-context"))
FRESH = os.path.join(TMP, "fresh")
render.render(FRESH)


def committed_copy(name):
    """A copy of a fresh render, standing in for the committed outputs."""
    dest = os.path.join(TMP, name)
    shutil.copytree(FRESH, dest)
    return dest


def nested_skill_file(root):
    """A file at least two folders below .claude/skills/, so only a recursive check can see it."""
    base = os.path.join(root, ".claude", "skills")
    for dirpath, _, files in sorted(os.walk(base)):
        if os.path.relpath(dirpath, base).count(os.sep) >= 1 and files:
            return os.path.join(dirpath, sorted(files)[0])
    raise AssertionError("no nested file under .claude/skills to edit")


def test_identical_copy_is_current():
    copy = committed_copy("same")
    assert render.stale_outputs(copy, FRESH) == []


def test_nested_edit_is_stale():
    copy = committed_copy("edited")
    path = nested_skill_file(copy)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("drift\n")
    # The old check read only the top level of .claude/skills, which holds folders, so it saw nothing.
    top = filecmp.dircmp(os.path.join(copy, ".claude", "skills"), os.path.join(FRESH, ".claude", "skills"))
    assert not (top.diff_files or top.left_only or top.right_only), "the edit must be below the top level"
    assert render.stale_outputs(copy, FRESH) == [".claude/skills"]


def test_same_size_edit_is_stale():
    copy = committed_copy("same-size")
    path = nested_skill_file(copy)
    with open(path, "rb") as fh:
        data = bytearray(fh.read())
    data[0] = ord("X") if data[0] != ord("X") else ord("Y")
    st = os.stat(path)
    with open(path, "wb") as fh:
        fh.write(bytes(data))
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert render.stale_outputs(copy, FRESH) == [".claude/skills"]


def test_nested_extra_file_is_stale():
    copy = committed_copy("extra")
    folder = os.path.dirname(nested_skill_file(copy))
    with open(os.path.join(folder, "extra.md"), "w", encoding="utf-8") as fh:
        fh.write("extra\n")
    assert render.stale_outputs(copy, FRESH) == [".claude/skills"]


def test_nested_missing_file_is_stale():
    copy = committed_copy("missing")
    os.remove(nested_skill_file(copy))
    assert render.stale_outputs(copy, FRESH) == [".claude/skills"]


def test_missing_output_folder_is_stale():
    copy = committed_copy("no-agents")
    shutil.rmtree(os.path.join(copy, ".github", "agents"))
    assert render.stale_outputs(copy, FRESH) == [".github/agents"]


def test_changed_claude_md_is_stale():
    copy = committed_copy("claude-md")
    with open(os.path.join(copy, "CLAUDE.md"), "a", encoding="utf-8") as fh:
        fh.write("drift\n")
    assert render.stale_outputs(copy, FRESH) == ["CLAUDE.md"]


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    try:
        for t in tests:
            try:
                t()
                passed += 1
            except Exception as exc:
                failed += 1
                print(f"FAIL {t.__name__}: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(TMP, True)
    print(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
# CI smoke test: this branch is closed without merging.
