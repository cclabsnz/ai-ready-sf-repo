#!/usr/bin/env python3
"""Tests for answer_to_draft.py. Plain script: python3 tools/demo/test_answer_to_draft.py

The index is built into a temp root together with a copy of demo/org; the real repo is only read.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tools", "impacts"))

from validate import validate  # noqa: E402
from _testutil import run_tests, symlink  # noqa: E402

TOOL = os.path.join(HERE, "answer_to_draft.py")
BUILD = os.path.join(REPO, "tools", "index", "build_index.py")
KEY = os.path.join(REPO, "demo", "stories", "DEMO-202.answer.json")

# The writer refuses output outside the checkout's ai-context/, so the temp root lives there.
os.makedirs(os.path.join(REPO, "ai-context"), exist_ok=True)
ROOT = tempfile.mkdtemp(prefix="answer_to_draft_", dir=os.path.join(REPO, "ai-context"))
atexit.register(shutil.rmtree, ROOT, True)
INDEX = os.path.join(ROOT, "index")


def setup():
    shutil.copytree(os.path.join(REPO, "demo", "org"), os.path.join(ROOT, "demo", "org"))
    subprocess.run([sys.executable, BUILD, "--root", os.path.join(REPO, "demo", "org"), "--out", INDEX],
                   check=True, capture_output=True)


def run(key=KEY, slug="round-robin-assignment"):
    p = subprocess.run([sys.executable, TOOL, "--key", key, "--slug", slug, "--index", INDEX,
                        "--root", ROOT], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def case_demo_202_draft_validates_and_matches_key():
    code, out = run()
    assert code == 0, out
    path = os.path.join(ROOT, "ai-context", "DEMO-202-round-robin-assignment", "impact.json")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    assert validate(doc, "draft", ROOT, check_evidence=True) == []
    with open(KEY, encoding="utf-8") as fh:
        key = json.load(fh)
    assert [c["api"] for c in doc["components"]] == [c["api"] for c in key["components"]]
    by = {c["api"]: c for c in doc["components"]}
    assert by["CaseAssignmentService"]["evidence"].endswith("CaseAssignmentService.cls:1")
    assert by["Escalation_Agents"]["confidence"] == "Inferred"
    assert by["CaseTrigger"]["confidence"] == "Confirmed" and by["CaseTrigger"]["impact"] == "Medium"
    assert doc["provenance"]["model"] == "none (derived from reviewed answer key)"
    assert doc["unknowns"] == key["assumptions"]


def case_unplaceable_index_component_exits_1():
    with open(KEY, encoding="utf-8") as fh:
        key = json.load(fh)
    key["components"].append({"api": "NoSuchThing", "type": "ApexClass", "changeType": "modify",
                              "hop": 1, "why": "synthetic"})
    kpath = os.path.join(ROOT, "bad.answer.json")
    with open(kpath, "w", encoding="utf-8") as fh:
        json.dump(key, fh)
    code, out = run(kpath, slug="bad-key")
    assert code == 1 and "NoSuchThing" in out, out
    assert not os.path.exists(os.path.join(ROOT, "ai-context", "DEMO-202-bad-key", "impact.json"))


def case_symlinked_scan_file_not_followed():
    outside = tempfile.mkdtemp(prefix="answer_to_draft_outside_")
    scan = os.path.join(ROOT, "ai-context", "DEMO-202-symlink-scan", "scan")
    try:
        os.makedirs(scan)
        victim = os.path.join(outside, "victim.json")
        with open(victim, "w", encoding="utf-8") as fh:
            fh.write("keep")
        symlink(victim, os.path.join(scan, "classified.json"))
        code, out = run(slug="symlink-scan")
        assert code == 2 and "symlink" in out, out
        with open(victim, encoding="utf-8") as fh:
            assert fh.read() == "keep"
        assert not os.path.exists(os.path.join(scan, "meta.json"))
    finally:
        shutil.rmtree(outside)


def case_root_outside_checkout_refused():
    root = tempfile.mkdtemp(prefix="answer_to_draft_elsewhere_")
    try:
        p = subprocess.run([sys.executable, TOOL, "--key", KEY, "--slug", "elsewhere",
                            "--index", INDEX, "--root", root], capture_output=True, text=True)
        assert p.returncode == 2, p.stdout + p.stderr
        assert "outside the checkout's ai-context/" in p.stderr, p.stderr
        assert not os.path.exists(os.path.join(root, "ai-context"))
    finally:
        shutil.rmtree(root)


def main():
    setup()
    cases = [(n, f) for n, f in sorted(globals().items()) if n.startswith("case_") and callable(f)]
    return run_tests(cases)


if __name__ == "__main__":
    sys.exit(main())
