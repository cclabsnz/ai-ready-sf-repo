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
sys.path.insert(0, os.path.join(REPO, "tools", "stories"))
from story_md import render_md  # noqa: E402

PROMOTE = os.path.join(HERE, "promote.py")
SCAN = os.path.join(REPO, "tools", "guard", "scan_data.py")
# A synthetic 18-character Salesforce Account ID, a default-pack hit. Built at run time so this file holds no hit.
DATA_HIT = "".join(["001", "5g00000AbCdE", "FGH"])
CLS = "force-app/main/default/classes/WidgetService.cls"
DRAFT = "ai-context/DEMO-903-widget-change"
DEST = "impacts/DEMO-903-widget-change"
MD = "# Impact: DEMO-903 widget-change\n\nSynthetic.\n"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def email_like(local):
    # Built at runtime so no source line holds a literal email-shaped value.
    return local + "@" + "corp-x" + ".test"


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


def make_root(doc=None, md=MD, in_ctx=False):
    """in_ctx: make the root under the checkout's ai-context/ (removed by story_cleanup)."""
    if in_ctx:
        os.makedirs(CTX, exist_ok=True)
        root = tempfile.mkdtemp(prefix="promote_", dir=CTX)
        _ROOTS.append(root)
    else:
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
    assert scan.load_patterns()["salesforce_id_18"].search(DATA_HIT), "test string no longer matches the pattern"
    root = make_root(md=MD + "Account " + DATA_HIT + "\n")
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
             "answer": "None", "deferred": False, "deferredBy": None},
            {"id": "OQ-2", "text": "Label wording?", "ownerRole": "Product Owner",
             "answer": None, "deferred": True, "deferredBy": "Product Owner"}],
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
    md = read_bytes(os.path.join(dest, "story.md"))
    assert md != SMD.encode("utf-8")  # re-rendered, not copied
    assert md == render_md(doc, [], None).encode("utf-8")


@story_cleanup
def case_confirmed_md_matches_json():
    """I1: the committed story.md states what the confirmed story.json holds."""
    doc = story_doc()
    doc["openQuestions"][0]["answer"] = "Sizes S1 and S2"
    root = make_story_root(doc, md=SMD + "Status: draft. stale answer: none\n")
    code, out = story_run(root, who="Customer Care product owner")
    assert code == 0, out
    dest = os.path.join(root, SDEST)
    pj = json.loads(read_bytes(os.path.join(dest, "story.json")).decode("utf-8"))
    md = read_bytes(os.path.join(dest, "story.md")).decode("utf-8")
    assert "Status: confirmed. Confirmed by: Customer Care product owner." in md, md
    assert "Status: draft" not in md and "stale answer" not in md, md
    assert "(status draft)" not in md and "(status confirmed)" in md, md
    rows = {line.split("|")[1].strip(): [c.strip() for c in line.split("|")[1:-1]]
            for line in md.splitlines() if line.startswith("| OQ-")}
    for q in pj["openQuestions"]:
        row = rows[q["id"]]
        assert row[3] == (q["answer"] if q["answer"] is not None else "none"), row
        assert row[4] == ("yes" if q["deferred"] else "no"), row
        assert row[5] == (q["deferredBy"] if q["deferredBy"] is not None else "none"), row
    assert rows["OQ-1"][3] == "Sizes S1 and S2", rows
    assert rows["OQ-2"][4:] == ["yes", "Product Owner"], rows
    assert "- none recorded at refinement" in md, md
    assert pj["status"] == "confirmed" and pj["confirmedBy"] == "Customer Care product owner"


@story_cleanup
def case_story_prints_deferrals_and_answers_before_writing():
    """I2: the confirmer sees every deferred question and every answer before the record is written."""
    doc = story_doc()
    doc["openQuestions"].append({"id": "OQ-3", "text": "Retire size XL?", "ownerRole": "Salesforce Admin",
                                 "answer": None, "deferred": True, "deferredBy": "Product Owner"})
    root = make_story_root(doc)
    code, out = story_run(root)
    assert code == 0, out
    lines = out.splitlines()
    dest_line = lines.index(os.path.join(root, SDEST))
    want = ["- OQ-2 (owner role: Product Owner; deferred by: Product Owner): Label wording?",
            "- OQ-3 (owner role: Salesforce Admin; deferred by: Product Owner): Retire size XL?",
            "- OQ-1 (owner role: Product Owner): Which sizes are retired? -> answer: None"]
    for w in want:
        assert w in lines and lines.index(w) < dest_line, (w, out)
    assert lines.index("Deferred:") < lines.index(want[0]) < lines.index("Answered:") < lines.index(want[2])
    for word in ("approve", "should", "block", "recommend"):
        assert word not in out.lower(), (word, out)
    # A refused run prints no summary.
    code, out = story_run(root)
    assert code == 1 and "already exists" in out and "Deferred:" not in out, out


@story_cleanup
def case_story_refuses_deferred_without_deferred_by():
    doc = story_doc()
    doc["openQuestions"][1]["deferredBy"] = None
    root = make_story_root(doc)
    code, out = story_run(root)
    assert code == 1 and "deferredBy is required" in out, out
    assert not os.path.exists(os.path.join(root, SDEST))
    doc = story_doc()
    doc["openQuestions"][0]["deferredBy"] = "Product Owner"
    root = make_story_root(doc)
    code, out = story_run(root)
    assert code == 1 and "deferredBy is set but deferred is not true" in out, out
    assert not os.path.exists(os.path.join(root, SDEST))


@story_cleanup
def case_story_final_md_scanned():
    """A data hit in a story.json answer, which the re-rendered md would carry, is refused.

    The draft scan catches it first; scan_final then runs on the rendered md bytes as well."""
    doc = story_doc()
    doc["openQuestions"][0]["answer"] = "Account " + DATA_HIT
    root = make_story_root(doc)
    code, out = story_run(root)
    assert code == 1 and "data guard" in out, out
    assert not os.path.exists(os.path.join(root, SDEST))


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
    root = make_story_root(md=SMD + "Account " + DATA_HIT + "\n")
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
    code, out = story_run(root, who=email_like("po"))
    assert code == 1 and "email" in out, out
    assert not os.path.exists(os.path.join(root, SDEST))


def case_impact_refuses_email_confirmer():
    root = make_root()
    code, out = run(root, who=email_like("tl"))
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


# --- WS10: design.json promoted with the impact -------------------------------------------------

DDRAFT = "ai-context/DEMO-905-widget-resize"
DDEST = "impacts/DEMO-905-widget-resize"


def design_doc():
    return {
        "schemaVersion": 1, "storyId": "DEMO-905", "slug": "widget-resize", "status": "draft",
        "options": [
            {"id": "OPT-1", "title": "Do nothing", "summary": "Keep the widget service.",
             "doNothing": True, "components": [],
             "tradeOffs": [{"criterion": "reuse", "note": "No change to the build."}],
             "impactSummary": "No metadata changes."},
            {"id": "OPT-2", "title": "Extend WidgetService", "summary": "Add a resize method.",
             "doNothing": False,
             "components": [{"api": "WidgetService", "type": "ApexClass", "changeType": "modify",
                             "evidence": CLS + ":2", "confidence": "Confirmed"}],
             "tradeOffs": [{"criterion": "maintainability", "note": "One class holds widget logic."}],
             "impactSummary": "One class changes."},
            {"id": "OPT-3", "title": "New resize object", "summary": "Store sizes on a new object.",
             "doNothing": False,
             "components": [{"api": "WidgetSize__c", "type": "CustomObject", "changeType": "new",
                             "evidence": None, "confidence": "Inferred"}],
             "tradeOffs": [{"criterion": "data-volume", "note": "One row per widget size."}],
             "impactSummary": "One object is added."}],
        "recommendation": {"optionId": "OPT-2", "reasons": ["Reuses the existing service."]},
        "provenance": {"indexStamp": {"commit": "feedc0de"}, "frameworkVersion": "0.1.0",
                       "model": "m", "assistantVersion": "unknown", "sourceRoot": "."}}


def design_impact(option="OPT-2", recommended=True):
    doc = draft_doc()
    doc["storyId"], doc["slug"] = "DEMO-905", "widget-resize"
    doc["designOption"] = option
    if recommended:
        doc["provenance"]["recommendedBy"] = "assistant"
    if option == "OPT-3":
        doc["components"] = [{"api": "WidgetSize__c", "type": "CustomObject", "changeType": "new",
                              "impact": "Medium", "confidence": "Inferred", "hop": 0,
                              "evidence": None, "path": None}]
    return doc


def make_design_root(impact=None, design=None):
    """A temp root under the checkout's ai-context/, with a synthetic index at <root>/index."""
    os.makedirs(CTX, exist_ok=True)
    root = tempfile.mkdtemp(prefix="promote_design_", dir=CTX)
    _ROOTS.append(root)
    write(os.path.join(root, CLS), "public with sharing class WidgetService {\n"
                                   "    public static void run() {}\n}\n")
    write(os.path.join(root, "index", "metadata.json"), json.dumps(
        {"stamp": {"commit": "feedc0de"}, "edges": [],
         "nodes": {"WidgetService": {"type": "ApexClass", "path": CLS}}}))
    write(os.path.join(root, DDRAFT, "impact.json"), json.dumps(impact or design_impact(), indent=2) + "\n")
    write(os.path.join(root, DDRAFT, "impact.md"), MD)
    write(os.path.join(root, DDRAFT, "design.json"), json.dumps(design or design_doc(), indent=2) + "\n")
    write(os.path.join(root, DDRAFT, "design.md"), "# Design: draft\n")
    return root


def design_run(root, *extra, who="Service Ops lead", draft=DDRAFT, index=True):
    args = [sys.executable, PROMOTE, os.path.join(root, draft), "--confirmed-by", who, "--root", root]
    if index:
        args += ["--index", os.path.join(root, "index")]
    p = subprocess.run(args + list(extra), capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def _design_md():
    sys.path.insert(0, os.path.join(REPO, "tools", "designs"))
    import design_md
    from validate_design import validate_design
    return design_md, validate_design


@story_cleanup
def case_promote_with_design_records_choice():
    design_md, validate_design = _design_md()
    root = make_design_root()
    code, out = design_run(root)
    assert code == 0, out
    dest = os.path.join(root, DDEST)
    assert sorted(os.listdir(dest)) == ["design.json", "design.md", "impact.json", "impact.md"]
    imp = load(os.path.join(dest, "impact.json"))
    assert imp["chosenOption"] == "OPT-2" and imp["designOption"] == "OPT-2", imp
    assert imp["provenance"]["recommendedBy"] == "assistant", imp
    assert validate(imp, "promoted", root) == []
    raw = read_bytes(os.path.join(dest, "design.json")).decode("utf-8")
    des = json.loads(raw)
    assert raw == json.dumps(des, indent=2, sort_keys=True) + "\n"
    assert des["status"] == "confirmed" and des["confirmedBy"] == "Service Ops lead", des
    assert des["chosenOption"] == "OPT-2", des
    assert validate_design(des, "confirmed", root) == []
    md = read_bytes(os.path.join(dest, "design.md"))
    assert md == design_md.render_md(des).encode("utf-8")
    text = md.decode("utf-8")
    assert "Status: confirmed. Confirmed by: Service Ops lead. Chosen option: OPT-2." in text, text
    assert "| OPT-2 (chosen) | Extend WidgetService |" in text, text
    assert "Chosen option: OPT-2 (Extend WidgetService), confirmed by Service Ops lead at promotion." in text
    assert "provisional" not in text, text
    assert read_bytes(os.path.join(dest, "impact.md")) == MD.encode("utf-8")
    assert "Chosen option: OPT-2 (recommended: OPT-2), confirmed by Service Ops lead." in out, out
    assert ("Design sourceRoot: '.'. Validated against index: %s (commit feedc0de). promote.py does "
            "not check which source root that index was built from." % os.path.join(root, "index")) in out, out
    # An owner who picks another option promotes once the impact assesses that option.
    root = make_design_root(impact=design_impact("OPT-3", recommended=False))
    code, out = design_run(root, "--option", "OPT-3")
    assert code == 0, out
    assert load(os.path.join(root, DDEST, "design.json"))["chosenOption"] == "OPT-3"
    assert load(os.path.join(root, DDEST, "impact.json"))["chosenOption"] == "OPT-3"
    text = read_bytes(os.path.join(root, DDEST, "design.md")).decode("utf-8")
    assert "Confirmed by: Service Ops lead. Chosen option: OPT-3." in text, text
    assert "| OPT-3 (chosen) |" in text and "| OPT-2 | Extend WidgetService |" in text, text
    assert "Recommended option: OPT-2 (Extend WidgetService)." in text, text


@story_cleanup
def case_option_mismatch_refused():
    root = make_design_root()
    code, out = design_run(root, "--option", "OPT-3")
    assert code == 1, out
    assert "impact assesses OPT-2; re-run story-impact for OPT-3 before promoting" in out, out
    assert not os.path.exists(os.path.join(root, DDEST))
    # Recommendation OPT-2, impact sized for OPT-3, no --option: refused the same way.
    root = make_design_root(impact=design_impact("OPT-3", recommended=False))
    code, out = design_run(root)
    assert code == 1 and "impact assesses OPT-3; re-run story-impact for OPT-2" in out, out
    assert not os.path.exists(os.path.join(root, DDEST))
    # An impact with no designOption beside a design is refused too.
    imp = design_impact()
    del imp["designOption"], imp["provenance"]["recommendedBy"]
    root = make_design_root(impact=imp)
    code, out = design_run(root)
    assert code == 1 and "impact assesses no design option; re-run story-impact for OPT-2" in out, out
    # An option the design does not hold.
    root = make_design_root()
    code, out = design_run(root, "--option", "OPT-9")
    assert code == 1 and "OPT-9 is not an option in design.json" in out, out
    assert not os.path.exists(os.path.join(root, DDEST))


@story_cleanup
def case_option_without_design_is_usage_error():
    root = make_root(in_ctx=True)
    for opt in ("OPT-2", "bogus"):
        code, out = run(root, "--option", opt)
        assert code == 2, out
    assert not os.path.exists(os.path.join(root, DEST))
    root = make_story_root()
    code, out = story_run(root, "--option", "OPT-1")
    assert code == 2, out
    assert not os.path.exists(os.path.join(root, SDEST))


@story_cleanup
def case_design_symlink_refused():
    root = make_design_root()
    secret = os.path.join(root, "data", "secret.json")
    write(secret, json.dumps(design_doc()))
    src = os.path.join(root, DDRAFT, "design.json")
    os.remove(src)
    symlink(secret, src)
    code, out = design_run(root)
    assert code == 1 and "symlink" in out, out
    assert not os.path.exists(os.path.join(root, DDEST))
    # A dangling symlink is a design to refuse, not "no design".
    os.remove(secret)
    code, out = design_run(root)
    assert code == 1 and "symlink" in out, out
    assert not os.path.exists(os.path.join(root, DDEST))
    # A symlinked destination design file is never written through.
    for name in ("design.json", "design.md"):
        root = make_design_root()
        target = os.path.join(root, "data", "victim.txt")
        write(target, "keep\n")
        os.makedirs(os.path.join(root, DDEST))
        symlink(target, os.path.join(root, DDEST, name))
        code, out = design_run(root, "--replace")
        assert code == 1 and "symlink" in out, (name, out)
        with open(target, encoding="utf-8") as fh:
            assert fh.read() == "keep\n"


@story_cleanup
def case_design_data_hit_refused():
    d = design_doc()
    d["options"][1]["summary"] = "Account " + DATA_HIT
    root = make_design_root(design=d)
    code, out = design_run(root)
    assert code == 1 and "data guard" in out, out
    assert not os.path.exists(os.path.join(root, DDEST))


@story_cleanup
def case_design_same_id_other_folder_refused():
    root = make_design_root()
    write(os.path.join(root, "impacts", "DEMO-905-old-slug", "design.json"), '{"storyId": "DEMO-905"}\n')
    code, out = design_run(root)
    assert code == 1 and "already has a record" in out and "design.json" in out, out
    assert not os.path.exists(os.path.join(root, DDEST))


@story_cleanup
def case_design_invalid_or_mismatched_refused():
    # A modify component missing from the index fails the draft design check.
    d = design_doc()
    d["options"][1]["components"][0]["api"] = "GhostService"
    root = make_design_root(design=d)
    code, out = design_run(root)
    assert code == 1 and "GhostService" in out and "draft design is not valid" in out, out
    # A design for another story.
    d = design_doc()
    d["slug"] = "other-thing"
    root = make_design_root(design=d)
    code, out = design_run(root)
    assert code == 1 and "design.json is for DEMO-905-other-thing" in out, out
    assert not os.path.exists(os.path.join(root, DDEST))
    # An unreadable index is a usage error.
    root = make_design_root()
    code, out = design_run(root, "--index", os.path.join(root, "no-index"), index=False)
    assert code == 2 and "cannot load index" in out, out
    assert not os.path.exists(os.path.join(root, DDEST))


@story_cleanup
def case_do_nothing_option_refuses_changes():
    # The impact assesses OPT-1 (do nothing) but still modifies WidgetService: refused.
    imp = design_impact("OPT-1", recommended=False)
    root = make_design_root(impact=imp)
    code, out = design_run(root, "--option", "OPT-1")
    assert code == 1, out
    assert "the chosen option is do nothing; the impact must not change components" in out, out
    assert "WidgetService" in out, out
    assert not os.path.exists(os.path.join(root, DDEST))
    for ct in ("new", "delete"):
        imp = design_impact("OPT-1", recommended=False)
        imp["components"][0]["changeType"] = ct
        if ct == "new":
            imp["components"][0]["evidence"] = None
        root = make_design_root(impact=imp)
        code, out = design_run(root, "--option", "OPT-1")
        assert code == 1 and "the chosen option is do nothing" in out, (ct, out)
    # review components only, or none, promote.
    for comps in ("review", None):
        imp = design_impact("OPT-1", recommended=False)
        if comps:
            imp["components"][0]["changeType"] = "review"
        else:
            imp["components"] = []
        root = make_design_root(impact=imp)
        code, out = design_run(root, "--option", "OPT-1")
        assert code == 0, (comps, out)
        assert load(os.path.join(root, DDEST, "impact.json"))["chosenOption"] == "OPT-1"


@story_cleanup
def case_impact_without_design_unchanged():
    # A designOption with no design.json beside it is refused, never promoted half-way.
    root = make_root(in_ctx=True)
    write(os.path.join(root, "ai-context", "DEMO-905-widget-resize", "impact.json"),
          json.dumps(design_impact()))
    write(os.path.join(root, "ai-context", "DEMO-905-widget-resize", "impact.md"), MD)
    code, out = run(root, draft="ai-context/DEMO-905-widget-resize")
    assert code == 1 and "impact assesses OPT-2 but" in out and "design.json is missing" in out, out
    # The WS2 path writes no design files and no chosenOption.
    root = make_root(in_ctx=True)
    code, out = run(root)
    assert code == 0, out
    doc = load(os.path.join(root, DEST, "impact.json"))
    assert "chosenOption" not in doc and "designOption" not in doc, doc
    # --replace over a folder that holds a confirmed design, from a draft without one, is refused.
    write(os.path.join(root, DEST, "design.json"), "{}\n")
    code, out = run(root, "--replace")
    assert code == 1 and "the draft has no design.json" in out, out


@story_cleanup
def case_impact_after_story_needs_no_replace():
    root = make_root()
    dest = os.path.join(root, DEST)
    write(os.path.join(dest, "story.json"), '{"keep": 1}\n')
    write(os.path.join(dest, "story.md"), "keep\n")
    code, out = run(root)
    assert code == 0, out
    assert read_bytes(os.path.join(dest, "story.json")) == b'{"keep": 1}\n'
    assert read_bytes(os.path.join(dest, "story.md")) == b"keep\n"
    assert sorted(os.listdir(dest)) == ["impact.json", "impact.md", "story.json", "story.md"]


@story_cleanup
def case_impact_over_existing_impact_needs_replace():
    root = make_root()
    dest = os.path.join(root, DEST)
    write(os.path.join(dest, "story.json"), '{"keep": 1}\n')
    assert run(root)[0] == 0
    code, out = run(root)
    assert code == 1 and "already exists and holds" in out and "impact.json" in out, out
    code, out = run(root, "--replace")
    assert code == 0, out
    assert read_bytes(os.path.join(dest, "story.json")) == b'{"keep": 1}\n'


VALIDATE = os.path.join(HERE, "validate.py")
VALIDATE_DESIGN = os.path.join(REPO, "tools", "designs", "validate_design.py")
BUILD_INDEX = os.path.join(REPO, "tools", "index", "build_index.py")
OBJ = "force-app/main/default/objects/WidgetSize__c/WidgetSize__c.object-meta.xml"


def _py(*args):
    p = subprocess.run([sys.executable] + list(args), capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def _rebuild_index(root):
    """Build a real index from the temp root's source into <root>/index (absolute --out)."""
    code, out = _py(BUILD_INDEX, "--root", root, "--out", os.path.join(root, "index"))
    assert code == 0, out
    return load(os.path.join(root, "index", "metadata.json"))


def _all_checks_pass(root):
    for script in (VALIDATE, VALIDATE_DESIGN):
        code, out = _py(script, "--all", "--root", root)
        assert code == 0 and json.loads(out)["ok"] is True, (script, out)


@story_cleanup
def case_confirmed_design_valid_after_code_lands():
    """The owner confirms OPT-3 (WidgetSize__c, changeType new). The object then lands in the
    source and the index is rebuilt: the confirmed records stay valid under both --all checks."""
    root = make_design_root(impact=design_impact("OPT-3", recommended=False))
    code, out = design_run(root, "--option", "OPT-3")
    assert code == 0, out
    _all_checks_pass(root)
    write(os.path.join(root, OBJ), '<?xml version="1.0" encoding="UTF-8"?>\n'
          '<CustomObject xmlns="http://soap.sforce.com/2006/04/metadata">\n'
          '    <label>Widget Size</label>\n</CustomObject>\n')
    idx = _rebuild_index(root)
    assert "WidgetSize__c" in idx["nodes"], sorted(idx["nodes"])
    _all_checks_pass(root)
    # The rebuilt index does hold the clash: the same record checked against it at draft time
    # (file mode with --index) is refused, so the --all pass above is not vacuous.
    code, out = _py(VALIDATE_DESIGN, os.path.join(root, DDEST, "design.json"), "--stage", "confirmed",
                    "--root", root, "--index", os.path.join(root, "index"))
    assert code == 1 and "'WidgetSize__c' (changeType new) already exists as index node" in out, out


@story_cleanup
def case_confirmed_design_valid_after_delete_ships():
    """The owner confirms an option that deletes WidgetService. The class is then removed and the
    index rebuilt: both --all checks still pass."""
    design = design_doc()
    design["options"][1]["components"][0]["changeType"] = "delete"
    design["options"][1]["title"] = "Retire WidgetService"
    imp = design_impact("OPT-2")
    imp["components"][0]["changeType"] = "delete"
    root = make_design_root(impact=imp, design=design)
    code, out = design_run(root)
    assert code == 0, out
    _all_checks_pass(root)
    os.remove(os.path.join(root, CLS))
    idx = _rebuild_index(root)
    assert "WidgetService" not in idx["nodes"], sorted(idx["nodes"])
    _all_checks_pass(root)
    code, out = _py(VALIDATE_DESIGN, os.path.join(root, DDEST, "design.json"), "--stage", "confirmed",
                    "--root", root, "--index", os.path.join(root, "index"))
    assert code == 1 and "'WidgetService' (changeType delete) is not a node in the index" in out, out


def main():
    cases =[(n, f) for n, f in sorted(globals().items()) if n.startswith("case_") and callable(f)]
    return run_tests(cases)


if __name__ == "__main__":
    sys.exit(main())
