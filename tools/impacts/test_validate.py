#!/usr/bin/env python3
"""Tests for validate.py. Temp trees only; the repo is not written.

Run: python3 tools/impacts/test_validate.py
"""
import atexit
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import validate as V  # noqa: E402

CLI = os.path.join(HERE, "validate.py")
ROOT = REPO

TMP = tempfile.mkdtemp(prefix="validate_impacts_")
atexit.register(shutil.rmtree, TMP, True)


def good():
    return {
        "schemaVersion": 1,
        "storyId": "DEMO-201",
        "slug": "premium-escalation",
        "squad": "Customer Care",
        "status": "draft",
        "provenance": {
            "indexStamp": {"commit": "abc1234"},
            "frameworkVersion": "unknown",
            "model": "unknown",
            "assistantVersion": "unknown",
            "hops": 2,
        },
        "components": [
            {"api": "CaseTriggerHandler", "type": "ApexClass", "changeType": "modify",
             "impact": "High", "confidence": "Confirmed", "hop": 0,
             "evidence": "a.cls:3", "path": "a.cls"},
        ],
        "decisions": [{"text": "Pick an owner for the handler change", "ownerRole": "Tech Lead"}],
        "unknowns": ["Managed package internals"],
    }


def mkroot(name):
    d = os.path.join(TMP, name)
    os.makedirs(d)
    return d


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="\n") as fh:
        fh.write(text)


def has(errors, word):
    return any(word in e for e in errors)


def test_good_draft_is_valid():
    assert V.validate(good(), "draft", ROOT) == []


def test_unknown_top_level_key():
    d = good()
    d["foo"] = 1
    assert has(V.validate(d, "draft", ROOT), "foo")


def test_bad_enums():
    for field, key, val in (("changeType", "changeType", "change"),
                            ("impact", "impact", "Huge"),
                            ("confidence", "confidence", "Sure")):
        d = good()
        d["components"][0][key] = val
        errs = V.validate(d, "draft", ROOT)
        assert len(errs) == 1 and field in errs[0], (field, errs)


def test_story_and_slug_patterns():
    d = good()
    d["storyId"] = "demo-1"
    assert has(V.validate(d, "draft", ROOT), "storyId")
    d = good()
    d["slug"] = "Bad Slug"
    assert has(V.validate(d, "draft", ROOT), "slug")


def test_stage_rules():
    d = good()
    d["confirmedBy"] = "someone"
    assert has(V.validate(d, "draft", ROOT), "confirmedBy")
    d = good()
    d["status"] = "in-flight"
    assert has(V.validate(d, "promoted", ROOT), "confirmedBy")
    d["confirmedBy"] = "someone"
    assert V.validate(d, "promoted", ROOT) == []
    d["status"] = "draft"
    assert has(V.validate(d, "promoted", ROOT), "status")
    d = good()
    d["status"] = "shipped"
    assert has(V.validate(d, "draft", ROOT), "status")


def test_evidence_null_rules():
    d = good()
    c = d["components"][0]
    c["evidence"] = None
    c["changeType"] = "new"
    assert V.validate(d, "draft", ROOT) == []
    c["changeType"] = "modify"
    c["confidence"] = "Unverifiable"
    assert V.validate(d, "draft", ROOT) == []
    c["confidence"] = "Confirmed"
    assert has(V.validate(d, "draft", ROOT), "evidence")


def test_check_evidence_line_range():
    root = mkroot("evidence")
    write(os.path.join(root, "a.cls"), "1\n2\n3\n")
    for ev, ok in (("a.cls:3", True), ("a.cls:4", False), ("missing.cls:1", False),
                   ("a.cls:0", False), ("a.cls:x", False), ("a.cls", False)):
        d = good()
        d["components"][0]["evidence"] = ev
        errs = V.validate(d, "draft", root, check_evidence=True)
        assert (errs == []) == ok, (ev, errs)
    # without check_evidence a missing file is not an error
    d = good()
    d["components"][0]["evidence"] = "missing.cls:1"
    assert V.validate(d, "draft", root) == []


def test_squad_not_listed():
    root = mkroot("squads")
    write(os.path.join(root, "impacts", "squads.json"),
          json.dumps({"version": 1, "squads": ["Customer Care"]}))
    d = good()
    assert V.validate(d, "draft", root) == []
    d["squad"] = "Nope"
    assert has(V.validate(d, "draft", root), "squad")
    assert V.load_squads(root) == ["Customer Care"]
    assert V.load_squads(mkroot("nosquads")) is None


def test_duplicate_api():
    d = good()
    d["components"].append(copy.deepcopy(d["components"][0]))
    assert has(V.validate(d, "draft", ROOT), "duplicate")


def test_duplicate_story_and_dir_mismatch():
    root = mkroot("all")
    for folder, slug in (("DEMO-1-a", "a"), ("DEMO-1-b", "c")):
        d = good()
        d["storyId"] = "DEMO-1"
        d["slug"] = slug
        d["status"] = "in-flight"
        d["confirmedBy"] = "someone"
        write(os.path.join(root, "impacts", folder, "impact.json"), json.dumps(d))
    p = subprocess.run([sys.executable, CLI, "--all", "--root", root],
                       capture_output=True, text=True)
    out = p.stdout
    assert p.returncode == 1, (p.returncode, out, p.stderr)
    assert "DEMO-1-a" in out and "DEMO-1-b" in out, out
    assert "duplicate" in out and "folder" in out, out


def test_nul_in_evidence_does_not_crash():
    d = good()
    d["components"][0]["evidence"] = "a\u0000b:3"
    errs = V.validate(d, "draft", ROOT, check_evidence=True)
    assert has(errs, "evidence path unreadable"), errs


def test_all_rejects_stage_and_check_evidence():
    root = mkroot("allflags")
    for flags in (["--stage", "draft"], ["--check-evidence"]):
        p = subprocess.run([sys.executable, CLI, "--all", "--root", root] + flags,
                           capture_output=True, text=True)
        assert p.returncode == 2, (flags, p.returncode, p.stdout)


def test_all_empty_exits_zero():
    root = mkroot("empty")
    p = subprocess.run([sys.executable, CLI, "--all", "--root", root],
                       capture_output=True, text=True)
    assert p.returncode == 0, (p.stdout, p.stderr)


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("FAIL %s: %r" % (name, exc))
    print("%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
