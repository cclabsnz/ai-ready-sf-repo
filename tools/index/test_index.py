#!/usr/bin/env python3
"""Prove the index's evidence opens from the repo root. Run in CI and in the smoke test.

Builds the index on fixtures/ into a temp dir, then checks every node path and every edge's
`path:line` evidence against the repo root, which is how run_skill.py and reviewers read them.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "build_index.py")
# Files a fresh clone needs; a too-broad ignore rule once kept tools/index/ out of git entirely.
MUST_NOT_BE_IGNORED = ("tools/index/build_index.py", "tools/index/query.py", "tools/index/test_index.py",
                       "CLAUDE.md")


def repo_root():
    try:
        return subprocess.check_output(
            ["git", "-C", HERE, "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return os.path.abspath(os.path.join(HERE, "..", ".."))


def main():
    root = repo_root()
    out = tempfile.mkdtemp(prefix="index-test-")
    try:
        subprocess.run([sys.executable, BUILD, "--root", os.path.join(root, "fixtures"), "--out", out],
                       check=True, capture_output=True)
        with open(os.path.join(out, "metadata.json")) as fh:
            meta = json.load(fh)
    finally:
        shutil.rmtree(out, ignore_errors=True)

    failures = []
    # check-ignore prints each ignored path and exits 0 if any is ignored; outside a checkout it exits 128.
    try:
        ignored = subprocess.run(["git", "-C", root, "check-ignore", *MUST_NOT_BE_IGNORED],
                                 capture_output=True, text=True).stdout.split()
    except FileNotFoundError:  # no git at all: nothing to check
        ignored = []
    for p in ignored:
        failures.append(f"git ignores {p}, so a fresh clone will not have it")
    paths = [v["path"] for v in meta["nodes"].values() if v.get("path")]
    evidence = [e["evidence"] for e in meta["edges"] if e.get("evidence")]
    if not paths or not evidence:
        failures.append("index has no node paths or no evidence, so nothing was checked")
    for p in paths:
        if not os.path.exists(os.path.join(root, p)):
            failures.append(f"node path does not exist from the repo root: {p}")
    for ev in evidence:
        p, line = ev.rsplit(":", 1)
        full = os.path.join(root, p)
        if not os.path.isfile(full):
            failures.append(f"evidence path does not exist from the repo root: {ev}")
            continue
        with open(full, encoding="utf-8", errors="replace") as fh:
            n = sum(1 for _ in fh)
        if int(line) > n:
            failures.append(f"evidence line beyond end of file ({n} lines): {ev}")

    for f in failures:
        print(f"[FAIL] {f}")
    print(f"{'PASS' if not failures else 'FAIL'}: {len(paths)} node paths and {len(evidence)} evidence refs "
          f"checked from the repo root")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
