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


# --- WS10: designOption, provenance.recommendedBy, chosenOption -----------------------------------

CTX = os.path.join(REPO, "ai-context")
CLS = "force-app/main/default/classes/WidgetService.cls"


def promoted_with_design():
    d = good()
    d["status"], d["confirmedBy"] = "in-flight", "Tech Lead"
    d["designOption"] = d["chosenOption"] = "OPT-2"
    d["provenance"]["recommendedBy"] = "assistant"
    return d


def test_impact_without_design_unchanged():
    """DEMO-202's committed record carries none of the WS10 fields and still validates."""
    path = os.path.join(REPO, "impacts", "DEMO-202-round-robin-assignment", "impact.json")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    for k in ("designOption", "chosenOption"):
        assert k not in doc, k
    assert "recommendedBy" not in doc["provenance"]
    assert V.validate(doc, "promoted", REPO, check_evidence=True) == []
    p = subprocess.run([sys.executable, CLI, "--all"], capture_output=True, text=True)
    assert p.returncode == 0, (p.stdout, p.stderr)


def test_design_fields_draft_and_promoted():
    d = good()
    d["designOption"] = "OPT-2"
    d["provenance"]["recommendedBy"] = "assistant"
    assert V.validate(d, "draft", ROOT) == []
    assert V.validate(promoted_with_design(), "promoted", ROOT) == []
    # designOption alone (owner chose a non-recommended option, re-assessed) is valid in a draft.
    d = good()
    d["designOption"] = "OPT-3"
    assert V.validate(d, "draft", ROOT) == []


def test_design_fields_rejected():
    cases = []
    d = good(); d["designOption"] = "option-2"; cases.append((d, "draft", "does not match OPT-<n>"))
    d = good(); d["designOption"] = "OPT-2"; d["provenance"]["recommendedBy"] = "model"
    cases.append((d, "draft", "recommendedBy 'model'"))
    d = good(); d["provenance"]["recommendedBy"] = "assistant"
    cases.append((d, "draft", "without a designOption"))
    d = good(); d["designOption"] = d["chosenOption"] = "OPT-2"
    cases.append((d, "draft", "chosenOption is present in a draft"))
    d = promoted_with_design(); del d["chosenOption"]
    cases.append((d, "promoted", "chosenOption is missing"))
    d = promoted_with_design(); d["chosenOption"] = "OPT-3"
    cases.append((d, "promoted", "differs from designOption"))
    d = promoted_with_design(); del d["designOption"]; del d["provenance"]["recommendedBy"]
    cases.append((d, "promoted", "differs from designOption"))
    for doc, stage, word in cases:
        errs = V.validate(doc, stage, ROOT)
        assert has(errs, word), (word, errs)


def _design(chosen="OPT-2"):
    return {
        "schemaVersion": 1, "storyId": "DEMO-201", "slug": "premium-escalation",
        "status": "confirmed", "confirmedBy": "Tech Lead", "chosenOption": chosen,
        "options": [
            {"id": "OPT-1", "title": "Do nothing", "summary": "Keep it.", "doNothing": True,
             "components": [], "tradeOffs": [{"criterion": "reuse", "note": "No change."}],
             "impactSummary": "None."},
            {"id": "OPT-2", "title": "Extend", "summary": "Extend the class.", "doNothing": False,
             "components": [{"api": "WidgetService", "type": "ApexClass", "changeType": "modify",
                             "evidence": CLS + ":1", "confidence": "Confirmed"}],
             "tradeOffs": [{"criterion": "maintainability", "note": "One class."}],
             "impactSummary": "One class."}],
        "recommendation": {"optionId": "OPT-2", "reasons": ["Reuse."]},
        "provenance": {"indexStamp": {"commit": "feedc0de"}, "frameworkVersion": "0.1.0",
                       "model": "m", "assistantVersion": "unknown", "sourceRoot": "."}}


def _design_root(design=None, impact=None):
    """A temp root with no index at all: --all never reads one."""
    os.makedirs(CTX, exist_ok=True)
    root = tempfile.mkdtemp(prefix="validate_design_all_", dir=CTX)
    atexit.register(shutil.rmtree, root, True)
    write(os.path.join(root, CLS), "public with sharing class WidgetService {}\n")
    folder = os.path.join(root, "impacts", "DEMO-201-premium-escalation")
    write(os.path.join(folder, "impact.json"), json.dumps(impact or promoted_with_design()))
    if design is not False:
        write(os.path.join(folder, "design.json"), json.dumps(design or _design()))
    return root


def _all(root, *extra):
    p = subprocess.run([sys.executable, CLI, "--all", "--root", root] + list(extra),
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def test_all_validates_design_beside_impact():
    root = _design_root()
    code, out = _all(root)
    assert code == 0, out
    assert "design.json" in out, out
    # No index check on a confirmed design: a modify component that is no node anywhere (there is
    # no index in the root) and evidence past the end of its file both pass --all.
    d = _design()
    d["options"][1]["components"][0]["api"] = "GhostService"
    d["options"][1]["components"][0]["evidence"] = CLS + ":99"
    code, out = _all(_design_root(design=d))
    assert code == 0, out
    # A draft design on record fails: designs beside impacts are confirmed.
    d = _design()
    d["status"] = "draft"
    code, out = _all(_design_root(design=d))
    assert code == 1 and "status 'draft'" in out, out
    # Schema still fails: a malformed evidence string and a missing sourceRoot.
    d = _design()
    d["options"][1]["components"][0]["evidence"] = "no-colon"
    del d["provenance"]["sourceRoot"]
    code, out = _all(_design_root(design=d))
    assert code == 1 and "is not 'path:line'" in out and "provenance.sourceRoot is missing" in out, out
    # The design's chosenOption agrees with the impact's.
    code, out = _all(_design_root(design=_design("OPT-1")))
    assert code == 1 and "differs from the impact's chosenOption" in out, out
    # An impact with chosenOption and no design beside it.
    code, out = _all(_design_root(design=False))
    assert code == 1 and "no design.json is beside the impact" in out, out
    # --index is not an option of validate.py any more, with or without --all.
    code, out = _all(root, "--index", os.path.join(root, "index"))
    assert code == 2, out
    p = subprocess.run([sys.executable, CLI, os.path.join(root, "x.json"), "--index", "index"],
                       capture_output=True, text=True)
    assert p.returncode == 2, p.stderr


def test_all_deep_nesting_reported_not_crash():
    root = mkroot("deep")
    write(os.path.join(root, "impacts", "DEMO-1-a", "impact.json"), "[" * 100000 + "]" * 100000)
    p = subprocess.run([sys.executable, CLI, "--all", "--root", root], capture_output=True, text=True)
    assert p.returncode == 1, (p.returncode, p.stdout, p.stderr)
    out = json.loads(p.stdout)
    assert out["ok"] is False and "cannot read JSON" in out["results"][0]["errors"][0], out
    assert "Traceback" not in p.stderr, p.stderr
    # A deeply nested design.json beside an impact is reported the same way.
    root = _design_root()
    write(os.path.join(root, "impacts", "DEMO-201-premium-escalation", "design.json"),
          "[" * 100000 + "]" * 100000)
    code, out = _all(root)
    assert code == 1 and "cannot read JSON" in out and "Traceback" not in out, out


def test_all_do_nothing_choice_with_changes():
    imp = promoted_with_design()
    imp["designOption"] = imp["chosenOption"] = "OPT-1"
    del imp["provenance"]["recommendedBy"]
    code, out = _all(_design_root(design=_design("OPT-1"), impact=imp))
    assert code == 1, out
    assert "the chosen option is do nothing; the impact must not change components" in out, out
    imp["components"][0]["changeType"] = "review"
    code, out = _all(_design_root(design=_design("OPT-1"), impact=imp))
    assert code == 0, out


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
