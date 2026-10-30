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

from _testutil import run_tests, symlink  # noqa: E402
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
    symlink(target, os.path.join(root, DEST))
    code, out = run(root, "--replace")
    assert code == 1 and "symlink" in out, out
    assert os.listdir(target) == []


def case_refuses_symlinked_impacts_folder():
    root = make_root()
    outside = tempfile.mkdtemp(prefix="promote_outside_")
    symlink(outside, os.path.join(root, "impacts"))
    code, out = run(root)
    assert code == 1 and "symlink" in out, out
    assert os.listdir(outside) == []


def case_refuses_symlink_destination_file():
    root = make_root()
    target = os.path.join(tempfile.mkdtemp(prefix="promote_target_"), "victim.txt")
    write(target, "keep\n")
    os.makedirs(os.path.join(root, DEST))
    symlink(target, os.path.join(root, DEST, "impact.md"))
    code, out = run(root, "--replace")
    assert code == 1 and "symlink" in out, out
    with open(target, encoding="utf-8") as fh:
        assert fh.read() == "keep\n"


CTX = os.path.join(REPO, "ai-context")
SDRAFT = "ai-context/DEMO-904-widget-size"
SDEST = "impacts/DEMO-904-widget-size"
FIELD = "force-app/main/default/objects/Widget__c/fields/Size__c.field-meta.xml"
SMD = "# Story: DEMO-904 widget-size\n\nSynthetic.\n"
_ROOTS = []


def story_doc():
    return {
        "schemaVersion": 1, "storyId": "DEMO-904", "slug": "widget-size", "status": "draft",
        "squad": "Service Ops", "persona": "a service agent",
        "goal": "record a widget size", "benefit": "agents pick the right part",
        "inScope": ["Widget size"], "outOfScope": ["Pricing"], "nonFunctional": [],
        "openQuestions": [
            {"id": "OQ-1", "text": "Which sizes are retired?", "ownerRole": "Product Owner",
             "answer": "None", "deferred": False},
            {"id": "OQ-2", "text": "Label wording?", "ownerRole": "Product Owner",
             "answer": None, "deferred": True}],
        "acceptanceCriteria": [
            {"id": "AC-1", "given": "a widget with no size", "when": "the agent saves it",
             "then": "the widget saves with a blank size", "examples": ["Widget W-1 saves"],
             "source": "edge-case"}],
        "edgeCases": [
            {"id": "EC-1", "category": "blank", "component": "Widget__c.Size__c",
             "detail": "field is not required; value left blank", "evidence": FIELD + ":2",
             "confidence": "Confirmed", "becameCriterion": "AC-1", "reason": None}],
        "droppedSeeds": [], "overlaps": [], "seeds": ["Widget__c.Size__c"]}


def make_story_root(doc=None, md=SMD):
    os.makedirs(CTX, exist_ok=True)
    root = tempfile.mkdtemp(prefix="promote_story_", dir=CTX)
    _ROOTS.append(root)
    write(os.path.join(root, FIELD), "<CustomField>\n    <required>false</required>\n</CustomField>\n")
    write(os.path.join(root, "impacts", "squads.json"),
          json.dumps({"version": 1, "squads": ["Customer Care", "Service Ops"]}))
    write(os.path.join(root, SDRAFT, "story.json"), json.dumps(doc or story_doc(), indent=2) + "\n")
    write(os.path.join(root, SDRAFT, "story.md"), md)
    return root


def story_run(root, *extra, who="Product Owner", draft=SDRAFT):
    args = [sys.executable, PROMOTE, "--story", os.path.join(root, draft)]
    if who is not None:
        args += ["--confirmed-by", who]
    p = subprocess.run(args + ["--root", root] + list(extra), capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def story_cleanup(fn):
    def wrapped():
        try:
            fn()
        finally:
            while _ROOTS:
                shutil.rmtree(_ROOTS.pop(), ignore_errors=True)
    wrapped.__name__ = fn.__name__
    return wrapped


@story_cleanup
def case_story_promote_sets_confirmed():
    root = make_story_root()
    code, out = story_run(root)
    assert code == 0, out
    dest = os.path.join(root, SDEST)
    raw = read_bytes(os.path.join(dest, "story.json")).decode("utf-8")
    doc = json.loads(raw)
    assert doc["status"] == "confirmed" and doc["confirmedBy"] == "Product Owner", doc
    assert raw == json.dumps(doc, indent=2, sort_keys=True) + "\n"
    assert read_bytes(os.path.join(dest, "story.md")) == SMD.encode("utf-8")


@story_cleanup
def case_story_promote_leaves_impact_alone():
    root = make_story_root()
    dest = os.path.join(root, SDEST)
    write(os.path.join(dest, "impact.json"), '{"keep": 1}\n')
    write(os.path.join(dest, "impact.md"), "keep\n")
    code, out = story_run(root)
    assert code == 0, out
    assert read_bytes(os.path.join(dest, "impact.json")) == b'{"keep": 1}\n'
    assert read_bytes(os.path.join(dest, "impact.md")) == b"keep\n"
    assert sorted(os.listdir(dest)) == ["impact.json", "impact.md", "story.json", "story.md"]


@story_cleanup
def case_story_refuses_open_question():
    doc = story_doc()
    doc["openQuestions"][0]["answer"] = None
    root = make_story_root(doc)
    code, out = story_run(root)
    assert code == 1 and "OQ-1" in out, out
    assert not os.path.exists(os.path.join(root, SDEST))


@story_cleanup
def case_story_refuses_vague_ac():
    doc = story_doc()
    doc["acceptanceCriteria"][0]["then"] = "the widget saves quickly"
    root = make_story_root(doc)
    code, out = story_run(root)
    assert code == 1 and "vague-word" in out, out
    assert not os.path.exists(os.path.join(root, SDEST))


@story_cleanup
def case_story_refuses_bad_evidence():
    doc = story_doc()
    doc["edgeCases"][0]["evidence"] = FIELD + ":99"
    root = make_story_root(doc)
    code, out = story_run(root)
    assert code == 1, out
    assert not os.path.exists(os.path.join(root, SDEST))


@story_cleanup
def case_story_refuses_data_scan_hit():
    bank = "-".join(["12", "3456", "7890123", "00"])
    root = make_story_root(md=SMD + "Account " + bank + "\n")
    code, out = story_run(root)
    assert code == 1, out
    assert not os.path.exists(os.path.join(root, SDEST))


@story_cleanup
def case_story_copies_only_two_files():
    root = make_story_root()
    write(os.path.join(root, SDRAFT, "inputs", "x.txt"), "x\n")
    write(os.path.join(root, SDRAFT, "impact.json"), "{}\n")
    code, out = story_run(root)
    assert code == 0, out
    assert sorted(os.listdir(os.path.join(root, SDEST))) == ["story.json", "story.md"]


@story_cleanup
def case_story_refuses_existing_without_replace():
    root = make_story_root()
    assert story_run(root)[0] == 0
    code, out = story_run(root)
    assert code == 1 and "already exists" in out, out
    code, out = story_run(root, "--replace")
    assert code == 0, out


@story_cleanup
def case_story_same_id_other_folder_refused():
    root = make_story_root()
    assert story_run(root)[0] == 0
    doc = story_doc()
    doc["slug"] = "widget-size-two"
    write(os.path.join(root, "ai-context", "DEMO-904-widget-size-two", "story.json"), json.dumps(doc))
    write(os.path.join(root, "ai-context", "DEMO-904-widget-size-two", "story.md"), SMD)
    code, out = story_run(root, "--replace", draft="ai-context/DEMO-904-widget-size-two")
    assert code == 1 and "already has a record" in out, out
    assert not os.path.exists(os.path.join(root, "impacts", "DEMO-904-widget-size-two"))


@story_cleanup
def case_story_refuses_impact_under_other_slug_folder():
    root = make_story_root()
    write(os.path.join(root, "impacts", "DEMO-904-old-slug", "impact.json"), '{"storyId": "DEMO-904"}\n')
    code, out = story_run(root)
    assert code == 1 and "already has a record" in out, out
    assert not os.path.exists(os.path.join(root, SDEST))


@story_cleanup
def case_impact_refuses_story_or_impact_under_other_folder():
    for rec in ("story.json", "impact.json"):
        root = make_root()
        write(os.path.join(root, "impacts", "DEMO-903-old-slug", rec), '{"storyId": "DEMO-903"}\n')
        code, out = run(root)
        assert code == 1 and "already has a record" in out, out
        assert not os.path.exists(os.path.join(root, DEST))


@story_cleanup
def case_story_refuses_email_confirmer():
    root = make_story_root()
    code, out = story_run(root, who="po@real-company.test")
    assert code == 1 and "email" in out, out
    assert not os.path.exists(os.path.join(root, SDEST))


def case_impact_refuses_email_confirmer():
    root = make_root()
    code, out = run(root, who="tl@real-company.test")
    assert code == 1 and "email" in out, out
    assert not os.path.exists(os.path.join(root, DEST))


def case_impact_source_symlink_refused():
    for name in ("impact.md", "impact.json"):
        root = make_root()
        secret = os.path.join(root, "data", "secret.txt")
        write(secret, "outside ai-context\n")
        src = os.path.join(root, DRAFT, name)
        os.remove(src)
        symlink(secret, src)
        code, out = run(root)
        assert code == 1 and "symlink" in out, out
        assert not os.path.exists(os.path.join(root, DEST))


def case_impact_deep_nesting_refused():
    root = make_root()
    write(os.path.join(root, DRAFT, "impact.json"), "[" * 100000 + "]" * 100000)
    code, out = run(root)
    assert code == 1 and "cannot read impact.json" in out, out
    assert not os.path.exists(os.path.join(root, DEST))


@story_cleanup
def case_story_deep_nesting_refused():
    root = make_story_root()
    write(os.path.join(root, SDRAFT, "story.json"), "[" * 100000 + "]" * 100000)
    code, out = story_run(root)
    assert code == 1 and "cannot read story.json" in out, out
    assert not os.path.exists(os.path.join(root, SDEST))


@story_cleanup
def case_story_refuses_symlink_json_source():
    root = make_story_root()
    secret = os.path.join(root, "outside", "secret.json")
    write(secret, json.dumps(story_doc()))
    src = os.path.join(root, SDRAFT, "story.json")
    os.remove(src)
    symlink(secret, src)
    code, out = story_run(root)
    assert code == 1 and "symlink" in out, out
    assert not os.path.exists(os.path.join(root, SDEST))


@story_cleanup
def case_story_missing_confirmed_by_is_usage_error():
    root = make_story_root()
    assert story_run(root, who=None)[0] == 2
    assert story_run(root, who="   ")[0] == 2
    assert not os.path.exists(os.path.join(root, SDEST))


@story_cleanup
def case_story_draft_outside_ai_context_is_usage_error():
    root = make_story_root()
    shutil.copytree(os.path.join(root, SDRAFT), os.path.join(root, "elsewhere"))
    code, out = story_run(root, draft="elsewhere")
    assert code == 2, out
    assert not os.path.exists(os.path.join(root, SDEST))


@story_cleanup
def case_story_refuses_symlink_source():
    root = make_story_root()
    real = os.path.join(root, SDRAFT, "real.md")
    os.rename(os.path.join(root, SDRAFT, "story.md"), real)
    symlink(real, os.path.join(root, SDRAFT, "story.md"))
    code, out = story_run(root)
    assert code == 1 and "symlink" in out, out
    assert not os.path.exists(os.path.join(root, SDEST))


@story_cleanup
def case_story_refuses_symlink_destination():
    root = make_story_root()
    target = tempfile.mkdtemp(prefix="promote_target_")
    os.makedirs(os.path.join(root, "impacts"), exist_ok=True)
    symlink(target, os.path.join(root, SDEST))
    code, out = story_run(root, "--replace")
    assert code == 1 and "symlink" in out, out
    assert os.listdir(target) == []
    shutil.rmtree(target, ignore_errors=True)


@story_cleanup
def case_story_refuses_symlinked_impacts_folder():
    root = make_story_root()
    outside = tempfile.mkdtemp(prefix="promote_outside_")
    shutil.move(os.path.join(root, "impacts", "squads.json"), outside)
    shutil.rmtree(os.path.join(root, "impacts"))
    symlink(outside, os.path.join(root, "impacts"))
    code, out = story_run(root)
    assert code == 1 and "symlink" in out, out
    assert os.listdir(outside) == ["squads.json"]
    shutil.rmtree(outside, ignore_errors=True)


@story_cleanup
def case_story_refuses_symlink_destination_file():
    root = make_story_root()
    target = os.path.join(tempfile.mkdtemp(prefix="promote_target_"), "victim.txt")
    write(target, "keep\n")
    os.makedirs(os.path.join(root, SDEST))
    symlink(target, os.path.join(root, SDEST, "story.md"))
    code, out = story_run(root, "--replace")
    assert code == 1 and "symlink" in out, out
    with open(target, encoding="utf-8") as fh:
        assert fh.read() == "keep\n"
    shutil.rmtree(os.path.dirname(target), ignore_errors=True)


def main():
    cases =[(n, f) for n, f in sorted(globals().items()) if n.startswith("case_") and callable(f)]
    return run_tests(cases)


if __name__ == "__main__":
    sys.exit(main())
