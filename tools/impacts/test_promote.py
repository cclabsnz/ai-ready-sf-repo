#!/usr/bin/env python3
"""Tests for promote.py. Plain script: python3 tools/impacts/test_promote.py

promote.py runs by subprocess with --root <temp root>; the temp root holds data only.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

from validate import validate  # noqa: E402

PROMOTE = os.path.join(HERE, "promote.py")
SCAN = os.path.join(REPO, "tools", "guard", "scan_data.py")
CLS = "force-app/main/default/classes/WidgetService.cls"
DRAFT = "ai-context/DEMO-903-widget-change"
DEST = "impacts/DEMO-903-widget-change"
MD = "# Impact: DEMO-903 widget-change\n\nSynthetic.\n"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def draft_doc():
    return {"schemaVersion": 1, "storyId": "DEMO-903", "slug": "widget-change", "squad": "Service Ops",
            "status": "draft",
            "provenance": {"indexStamp": {"commit": "abc1234"}, "frameworkVersion": "0.1.0",
                           "model": "m", "assistantVersion": "n/a", "hops": 1},
            "components": [{"api": "WidgetService", "type": "ApexClass", "changeType": "modify",
                            "impact": "Medium", "confidence": "Confirmed", "hop": 0,
                            "evidence": CLS + ":2", "path": CLS}],
            "decisions": [{"text": "Agree sequencing", "ownerRole": "Tech Lead"}],
            "unknowns": ["Org-only config"]}


def make_root(doc=None, md=MD):
    root = tempfile.mkdtemp(prefix="promote_")
    write(os.path.join(root, CLS), "public with sharing class WidgetService {\n"
                                   "    public static void run() {}\n}\n")
    write(os.path.join(root, DRAFT, "impact.json"), json.dumps(doc or draft_doc(), indent=2) + "\n")
    write(os.path.join(root, DRAFT, "impact.md"), md)
    return root


def run(root, *extra, draft=DRAFT, who="Service Ops lead"):
    args = [sys.executable, PROMOTE, os.path.join(root, draft)]
    if who is not None:
        args += ["--confirmed-by", who]
    p = subprocess.run(args + ["--root", root] + list(extra), capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def case_promote_sets_status_and_confirmer():
    root = make_root()
    code, out = run(root)
    assert code == 0, out
    dest = os.path.join(root, DEST)
    doc = load(os.path.join(dest, "impact.json"))
    assert doc["status"] == "in-flight" and doc["confirmedBy"] == "Service Ops lead", doc
    assert validate(doc, "promoted", root) == []
    with open(os.path.join(dest, "impact.json"), encoding="utf-8", newline="") as fh:
        raw = fh.read()
    assert raw == json.dumps(doc, indent=2, sort_keys=True) + "\n"
    assert "Next: git add" in out and "a reviewer checks the impact before merge." in out, out
    with open(os.path.join(dest, "impact.md"), "rb") as fh:
        assert fh.read() == MD.encode("utf-8")


def case_promote_copies_only_two_files():
    root = make_root()
    write(os.path.join(root, DRAFT, "inputs", "x.txt"), "x\n")
    write(os.path.join(root, DRAFT, "scan", "terms.txt"), "t\n")
    code, out = run(root)
    assert code == 0, out
    assert sorted(os.listdir(os.path.join(root, DEST))) == ["impact.json", "impact.md"]


def case_refuses_existing_without_replace():
    root = make_root()
    assert run(root)[0] == 0
    code, out = run(root)
    assert code == 1 and "already exists" in out, out
    code, out = run(root, "--replace")
    assert code == 0, out


def case_refuses_invalid_draft():
    doc = draft_doc()
    doc["components"][0]["evidence"] = CLS + ":99"
    root = make_root(doc)
    code, out = run(root)
    assert code == 1, out
    assert not os.path.exists(os.path.join(root, DEST))


def case_refuses_data_scan_hit():
    spec = importlib.util.spec_from_file_location("scan_data", SCAN)
    scan = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scan)
    bank = "-".join(["12", "3456", "7890123", "00"])
    assert scan.load_patterns()["nz_bank_account"].search(bank), "test string no longer matches the pattern"
    root = make_root(md=MD + "Account " + bank + "\n")
    code, out = run(root)
    assert code == 1, out
    assert not os.path.exists(os.path.join(root, DEST))


def case_missing_confirmed_by_is_usage_error():
    root = make_root()
    assert run(root, who=None)[0] == 2
    assert run(root, who="   ")[0] == 2
    assert not os.path.exists(os.path.join(root, DEST))


def case_draft_outside_ai_context_is_usage_error():
    root = make_root()
    outside = os.path.join(root, "elsewhere")
    shutil.copytree(os.path.join(root, DRAFT), outside)
    code, out = run(root, draft="elsewhere")
    assert code == 2, out
    assert not os.path.exists(os.path.join(root, DEST))


def case_refuses_symlink_destination():
    root = make_root()
    target = tempfile.mkdtemp(prefix="promote_target_")
    os.makedirs(os.path.join(root, "impacts"))
    os.symlink(target, os.path.join(root, DEST))
    code, out = run(root, "--replace")
    assert code == 1 and "symlink" in out, out
    assert os.listdir(target) == []


def case_refuses_symlinked_impacts_folder():
    root = make_root()
    outside = tempfile.mkdtemp(prefix="promote_outside_")
    os.symlink(outside, os.path.join(root, "impacts"))
    code, out = run(root)
    assert code == 1 and "symlink" in out, out
    assert os.listdir(outside) == []


def case_refuses_symlink_destination_file():
    root = make_root()
    target = os.path.join(tempfile.mkdtemp(prefix="promote_target_"), "victim.txt")
    write(target, "keep\n")
    os.makedirs(os.path.join(root, DEST))
    os.symlink(target, os.path.join(root, DEST, "impact.md"))
    code, out = run(root, "--replace")
    assert code == 1 and "symlink" in out, out
    with open(target, encoding="utf-8") as fh:
        assert fh.read() == "keep\n"


def main():
    cases = [(n, f) for n, f in sorted(globals().items()) if n.startswith("case_") and callable(f)]
    passed = failed = 0
    for name, fn in cases:
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
