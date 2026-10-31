#!/usr/bin/env python3
"""Tests for validate_design.py. Plain script: python3 tools/designs/test_validate_design.py

Data is synthetic: a temp root with one evidence file and an in-memory index. Tests never read
<checkout>/index.
"""
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
sys.path.insert(0, os.path.join(REPO, "tools", "impacts"))

from _testutil import run_tests  # noqa: E402
from validate_design import validate_design  # noqa: E402

SCRIPT = os.path.join(HERE, "validate_design.py")
CLS = "force-app/main/default/classes/WidgetService.cls"
IDX = {"stamp": {"commit": "feedc0de"},
       "nodes": {"WidgetService": {"type": "ApexClass", "path": CLS}}, "edges": []}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def make_root():
    root = tempfile.mkdtemp(prefix="validate_design_")
    write(os.path.join(root, CLS), "public with sharing class WidgetService {\n    void run() {}\n}\n")
    return root


def good():
    return {
        "schemaVersion": 1, "storyId": "DEMO-921", "slug": "widget-resize", "status": "draft",
        "options": [
            {"id": "OPT-1", "title": "Do nothing", "summary": "Keep the current widget service.",
             "doNothing": True, "components": [],
             "tradeOffs": [{"criterion": "reuse", "note": "No change to the build."}],
             "impactSummary": "No metadata changes."},
            {"id": "OPT-2", "title": "Extend WidgetService", "summary": "Add a resize method.",
             "doNothing": False,
             "components": [{"api": "WidgetService", "type": "ApexClass", "changeType": "modify",
                             "evidence": CLS + ":1", "confidence": "Confirmed"},
                            {"api": "WidgetSize__c", "type": "CustomObject", "changeType": "new",
                             "evidence": None, "confidence": "Inferred"}],
             "tradeOffs": [{"criterion": "maintainability", "note": "One class holds widget logic."},
                           {"criterion": "governor-limits", "note": "Runs in the existing trigger context."}],
             "impactSummary": "One class changes and one object is added."},
        ],
        "recommendation": {"optionId": "OPT-2", "reasons": ["Reuses the existing service."]},
        "provenance": {"indexStamp": {"commit": "feedc0de"}, "frameworkVersion": "0.1.0",
                       "model": "m", "assistantVersion": "unknown", "sourceRoot": "."},
    }


def confirmed():
    d = good()
    d["status"] = "confirmed"
    d["confirmedBy"] = "Tech Lead"
    d["chosenOption"] = "OPT-2"
    return d


def has(errors, text):
    return any(text in e for e in errors)


def test_good_design_valid():
    root = make_root()
    try:
        assert validate_design(good(), "draft", root) == []
        assert validate_design(good(), "draft", root, idx=IDX, check_evidence=True) == []
        assert validate_design(confirmed(), "confirmed", root, idx=IDX, check_evidence=True) == []
    finally:
        shutil.rmtree(root)


def test_no_do_nothing_fails():
    d = good()
    d["options"][0]["doNothing"] = False
    d["options"][0]["components"] = copy.deepcopy(d["options"][1]["components"])
    errs = validate_design(d, "draft", ".")
    assert has(errs, "exactly one doNothing option"), errs


def test_two_do_nothings_fail():
    d = good()
    extra = copy.deepcopy(d["options"][0])
    extra["id"] = "OPT-3"
    d["options"].append(extra)
    errs = validate_design(d, "draft", ".")
    assert has(errs, "exactly one doNothing option"), errs


def test_do_nothing_with_components_fails():
    d = good()
    d["options"][0]["components"] = copy.deepcopy(d["options"][1]["components"][:1])
    errs = validate_design(d, "draft", ".")
    assert has(errs, "do-nothing option has components"), errs


def test_change_option_needs_component():
    d = good()
    d["options"][1]["components"] = []
    errs = validate_design(d, "draft", ".")
    assert has(errs, "options[1]: lists no components"), errs


def test_option_count_bounds():
    d = good()
    d["options"] = d["options"][:1]
    d["recommendation"]["optionId"] = "OPT-1"
    assert has(validate_design(d, "draft", "."), "between 2 and 4 options"), d
    d = good()
    for n in (3, 4, 5):
        o = copy.deepcopy(d["options"][1])
        o["id"] = "OPT-%d" % n
        d["options"].append(o)
    assert has(validate_design(d, "draft", "."), "between 2 and 4 options")


def test_recommendation_unknown_option_fails():
    d = good()
    d["recommendation"]["optionId"] = "OPT-7"
    errs = validate_design(d, "draft", ".")
    assert has(errs, "recommendation.optionId 'OPT-7' is not an option id"), errs
    d["recommendation"]["optionId"] = ["OPT-1"]
    errs = validate_design(d, "draft", ".")
    assert has(errs, "recommendation.optionId '['OPT-1']' is not an option id"), errs


def test_recommendation_needs_reason():
    for reasons in ([], ["  "], "because", [3]):
        d = good()
        d["recommendation"]["reasons"] = reasons
        errs = validate_design(d, "draft", ".")
        assert has(errs, "recommendation.reasons"), (reasons, errs)


def test_option_ids_unique_no_gaps():
    d = good()
    d["options"][1]["id"] = "OPT-1"
    assert has(validate_design(d, "draft", "."), "duplicate id 'OPT-1'")
    d = good()
    d["options"][1]["id"] = "OPT-3"
    d["recommendation"]["optionId"] = "OPT-3"
    assert has(validate_design(d, "draft", "."), "have gaps")


def test_existing_component_missing_from_index_fails():
    d = good()
    d["options"][1]["components"][0]["api"] = "GhostService"
    errs = validate_design(d, "draft", ".", idx=IDX)
    assert has(errs, "'GhostService' (changeType modify) is not a node in the index"), errs
    assert validate_design(d, "draft", ".") == [], "without idx the index check does not run"
    # new components are never looked up
    assert not has(validate_design(good(), "draft", ".", idx=IDX), "WidgetSize__c")


def test_new_component_already_in_index_fails():
    d = good()
    d["options"][1]["components"][0]["changeType"] = "new"
    d["options"][1]["components"][0]["evidence"] = None
    errs = validate_design(d, "draft", ".", idx=IDX)
    assert has(errs, "'WidgetService' (changeType new) already exists as index node 'WidgetService'; "
                     "use modify or review"), errs
    assert validate_design(d, "draft", ".") == [], "without idx the index check does not run"


def test_new_component_case_insensitive_clash_fails():
    d = good()
    d["options"][1]["components"][1]["api"] = "widgetservice"
    d["options"][1]["components"][1]["type"] = "ApexClass"
    errs = validate_design(d, "draft", ".", idx=IDX)
    assert has(errs, "'widgetservice' (changeType new) already exists as index node 'WidgetService'"), errs


BUNDLE = "force-app/main/default/lwc/widgetCard"
IDX2 = {"stamp": {"commit": "feedc0de"},
        "nodes": {"WidgetService": {"type": "ApexClass", "path": CLS},
                  "widgetCard": {"type": "LightningComponentBundle", "path": BUNDLE},
                  "Case": {"type": "CustomObject", "path": None}}, "edges": []}


def test_evidence_wrong_file_fails():
    d = good()
    d["options"][1]["components"][0]["evidence"] = "force-app/main/default/classes/OtherService.cls:1"
    errs = validate_design(d, "draft", ".", idx=IDX2)
    assert has(errs, "is not in the index node's file '%s' for 'WidgetService'" % CLS), errs
    # a sibling whose name only shares the prefix is not inside the node's file
    d["options"][1]["components"][0]["evidence"] = CLS + "x:1"
    assert has(validate_design(d, "draft", ".", idx=IDX2), "is not in the index node's file")
    # bundle node: a file under the folder counts; the folder's sibling does not
    d = good()
    d["options"][1]["components"][0] = {"api": "widgetCard", "type": "LightningComponentBundle",
                                        "changeType": "modify", "evidence": BUNDLE + "/widgetCard.js:1",
                                        "confidence": "Confirmed"}
    assert validate_design(d, "draft", ".", idx=IDX2) == []
    d["options"][1]["components"][0]["evidence"] = BUNDLE + "Old/widgetCard.js:1"
    assert has(validate_design(d, "draft", ".", idx=IDX2), "is not in the index node's file")
    # null evidence (Unverifiable) skips the path check; a node with no path cannot anchor one
    d["options"][1]["components"][0]["evidence"] = None
    d["options"][1]["components"][0]["confidence"] = "Unverifiable"
    assert validate_design(d, "draft", ".", idx=IDX2) == []
    d["options"][1]["components"][0] = {"api": "Case", "type": "CustomObject", "changeType": "review",
                                        "evidence": CLS + ":1", "confidence": "Inferred"}
    assert validate_design(d, "draft", ".", idx=IDX2) == []


def test_type_mismatch_fails():
    d = good()
    d["options"][1]["components"][0]["type"] = "CustomObject"
    errs = validate_design(d, "draft", ".", idx=IDX2)
    assert has(errs, "type 'CustomObject' differs from the index node type 'ApexClass' for 'WidgetService'"), errs
    d["options"][1]["components"][0]["evidence"] = None
    d["options"][1]["components"][0]["confidence"] = "Unverifiable"
    errs = validate_design(d, "draft", ".", idx=IDX2)
    assert has(errs, "differs from the index node type"), "null evidence still checks the type"


def test_all_reads_no_index():
    root = make_root()
    try:
        code, out = run_cli(["--all", "--root", root])
        assert code == 0 and json.loads(out) == {"ok": True, "results": []}, out
        # A confirmed design whose modify component is no node anywhere, with no index on disk and
        # evidence past the end of its file: --all checks schema and consistency only.
        d = confirmed()
        d["options"][1]["components"][0]["api"] = "GhostService"
        d["options"][1]["components"][0]["evidence"] = CLS + ":99"
        write(os.path.join(root, "impacts", "DEMO-921-widget-resize", "design.json"), json.dumps(d))
        code, out = run_cli(["--all", "--root", root])
        assert code == 0 and json.loads(out)["ok"] is True, out
        # --index with --all is bad usage: it would read as "checked against the index".
        code, out = run_cli(["--all", "--root", root, "--index", os.path.join(root, "index")])
        assert code == 2 and "--index" in out, out
        # Schema and consistency still fail under --all.
        d["chosenOption"] = "OPT-9"
        write(os.path.join(root, "impacts", "DEMO-921-widget-resize", "design.json"), json.dumps(d))
        code, out = run_cli(["--all", "--root", root])
        assert code == 1 and "chosenOption 'OPT-9' is not an option id" in out, out
    finally:
        shutil.rmtree(root)


def test_source_root_lexical():
    for good_value in (".", "demo/org", "demo/greenfield", "src"):
        d = good()
        d["provenance"]["sourceRoot"] = good_value
        assert validate_design(d, "draft", ".") == [], good_value
    for bad_value in ("", "  ", "/abs/path", "../outside", "demo/../org", "demo/org/", "./demo",
                      "demo\\org", "C:/x", " demo", 7, None):
        d = good()
        d["provenance"]["sourceRoot"] = bad_value
        assert has(validate_design(d, "draft", "."), "provenance.sourceRoot"), bad_value
    d = good()
    del d["provenance"]["sourceRoot"]
    assert has(validate_design(d, "draft", "."), "provenance.sourceRoot is missing")
    # Lexical only: a folder that does not exist under root is still a valid record.
    d = confirmed()
    d["provenance"]["sourceRoot"] = "moved/away"
    assert validate_design(d, "confirmed", tempfile.gettempdir()) == []


def test_new_component_with_evidence_fails():
    d = good()
    d["options"][1]["components"][1]["evidence"] = CLS + ":1"
    errs = validate_design(d, "draft", ".")
    assert has(errs, "changeType new carries evidence"), errs


def test_existing_component_null_evidence():
    d = good()
    d["options"][1]["components"][0]["evidence"] = None
    assert has(validate_design(d, "draft", "."), "evidence is null")
    d["options"][1]["components"][0]["confidence"] = "Unverifiable"
    assert validate_design(d, "draft", ".") == []


def test_evidence_checked_against_root():
    root = make_root()
    try:
        d = good()
        d["options"][1]["components"][0]["evidence"] = CLS + ":99"
        assert validate_design(d, "draft", root) == []
        errs = validate_design(d, "draft", root, check_evidence=True)
        assert has(errs, "past the end"), errs
        d["options"][1]["components"][0]["evidence"] = "no-colon"
        assert has(validate_design(d, "draft", root), "is not 'path:line'")
    finally:
        shutil.rmtree(root)


def test_confirmed_needs_chosen_option():
    d = confirmed()
    del d["chosenOption"]
    assert has(validate_design(d, "confirmed", "."), "chosenOption is missing")
    d = confirmed()
    del d["confirmedBy"]
    assert has(validate_design(d, "confirmed", "."), "confirmedBy is missing")
    d = confirmed()
    d["chosenOption"] = "OPT-9"
    assert has(validate_design(d, "confirmed", "."), "chosenOption 'OPT-9' is not an option id")
    d = good()
    d["chosenOption"] = "OPT-2"
    assert has(validate_design(d, "draft", "."), "chosenOption is present in a draft")
    d = good()
    d["confirmedBy"] = "Tech Lead"
    assert has(validate_design(d, "draft", "."), "confirmedBy is present in a draft")
    assert has(validate_design(good(), "confirmed", "."), "status 'draft'")


def test_schema_keys_and_enums():
    d = good()
    d["extra"] = 1
    d["options"][1]["tradeOffs"][0]["criterion"] = "cost"
    d["options"][1]["components"][0]["changeType"] = "rewrite"
    d["options"][1]["components"][0]["confidence"] = "Sure"
    d["options"][0]["doNothing"] = "yes"
    del d["provenance"]["model"]
    d["schemaVersion"] = 2
    d["storyId"] = "bad id"
    errs = validate_design(d, "draft", ".")
    for text in ("unknown top-level key 'extra'", "criterion 'cost'", "changeType 'rewrite'",
                 "confidence 'Sure'", "doNothing is not true or false", "provenance.model",
                 "schemaVersion is not 1", "storyId 'bad id'"):
        assert has(errs, text), (text, errs)


def test_trade_offs_required():
    d = good()
    d["options"][1]["tradeOffs"] = []
    assert has(validate_design(d, "draft", "."), "options[1]: tradeOffs is empty")


def test_duplicate_component_in_option():
    d = good()
    d["options"][1]["components"].append(copy.deepcopy(d["options"][1]["components"][0]))
    assert has(validate_design(d, "draft", "."), "duplicate api 'WidgetService'")


def run_cli(args, cwd=None):
    p = subprocess.run([sys.executable, SCRIPT] + args, capture_output=True, text=True, cwd=cwd or REPO)
    return p.returncode, p.stdout + p.stderr


def test_cli_files_and_all():
    root = make_root()
    try:
        write(os.path.join(root, "index", "metadata.json"), json.dumps(IDX))
        f = os.path.join(root, "d.json")
        write(f, json.dumps(good()))
        code, out = run_cli([f, "--root", root, "--check-evidence", "--index", os.path.join(root, "index")])
        assert code == 0 and json.loads(out)["ok"] is True, out
        bad = good()
        bad["options"][1]["components"][0]["api"] = "GhostService"
        write(f, json.dumps(bad))
        code, out = run_cli([f, "--root", root, "--index", os.path.join(root, "index")])
        assert code == 1 and "GhostService" in out, out
        code, out = run_cli([f, "--root", root])
        assert code == 0, out
        code, out = run_cli([f, "--index", os.path.join(root, "missing")])
        assert code == 2 and "index" in out, out
        code, out = run_cli([])
        assert code == 2, out
        # --all over impacts/*/design.json, confirmed
        write(os.path.join(root, "impacts", "DEMO-921-widget-resize", "design.json"), json.dumps(confirmed()))
        code, out = run_cli(["--all", "--root", root])
        assert code == 0, out
        write(os.path.join(root, "impacts", "DEMO-921-wrong-folder", "design.json"), json.dumps(confirmed()))
        code, out = run_cli(["--all", "--root", root])
        assert code == 1 and "does not match storyId-slug" in out and "duplicate storyId" in out, out
        code, out = run_cli(["--all", "--stage", "draft", "--root", root])
        assert code == 2, out
    finally:
        shutil.rmtree(root)


def test_all_deep_nesting_reported_not_crash():
    root = make_root()
    try:
        write(os.path.join(root, "impacts", "DEMO-921-widget-resize", "design.json"),
              "[" * 100000 + "]" * 100000)
        p = subprocess.run([sys.executable, SCRIPT, "--all", "--root", root],
                           capture_output=True, text=True)
        assert p.returncode == 1, (p.returncode, p.stdout, p.stderr)
        out = json.loads(p.stdout)
        assert out["ok"] is False and "cannot read JSON" in out["results"][0]["errors"][0], out
        assert "Traceback" not in p.stderr, p.stderr
    finally:
        shutil.rmtree(root)


def main():
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    return run_tests(tests, show_pass=True)


if __name__ == "__main__":
    sys.exit(main())
