#!/usr/bin/env python3
"""Tests for package.py. Plain script: python3 tools/impacts/test_package.py

Each case builds a real git repo under <checkout>/ai-context/ (git-ignored) holding a tiny synthetic
source root, a hand-built index, and committed confirmed story, design and impact records. package.py
runs by subprocess with --root <temp repo> and --index <temp index>; it never reads <checkout>/index.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

from _testutil import SkipTest, run_tests  # noqa: E402

PACKAGE = os.path.join(HERE, "package.py")
REGISTER = os.path.join(HERE, "register.py")
CTX = os.path.join(REPO, "ai-context")
STORY = "DEMO-951"
SLUG = "widget-resize"
FOLDER = "impacts/%s-%s" % (STORY, SLUG)
SRC = "src"
BASE = SRC + "/force-app/main/default"
CLS = BASE + "/classes/WidgetService.cls"
TEST_CLS = BASE + "/classes/WidgetService_Test.cls"
HELPER = BASE + "/classes/WidgetHelper.cls"
TRIGGER = BASE + "/triggers/WidgetTrigger.trigger"
LWC = BASE + "/lwc/widgetCard"
FIELD = BASE + "/objects/Widget__c/fields/Size__c.field-meta.xml"
WHO = "Service Ops lead"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def git(repo, *args):
    """Test setup only: git with hooks off and a fixed identity."""
    return subprocess.run(["git", "-C", repo, "-c", "core.hooksPath=" + os.devnull,
                           "-c", "user.name=Test", "-c", "user.email=test-identity",
                           "-c", "commit.gpgsign=false"] + list(args),
                          capture_output=True, text=True, timeout=60)


def commit_all(repo, msg):
    git(repo, "add", "-A")
    p = git(repo, "commit", "-q", "-m", msg)
    assert p.returncode == 0, p.stderr
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def index_doc():
    return {"stamp": {"commit": "set-below"},
            "nodes": {
                "WidgetService": {"type": "ApexClass", "path": CLS, "isTest": False},
                "WidgetService_Test": {"type": "ApexClass", "path": TEST_CLS, "isTest": True},
                "WidgetHelper": {"type": "ApexClass", "path": HELPER, "isTest": False},
                "WidgetTrigger": {"type": "ApexTrigger", "path": TRIGGER, "isTest": False},
                "widgetCard": {"type": "LightningComponentBundle", "path": LWC},
                "Widget__c.Size__c": {"type": "CustomField", "path": FIELD},
                "Widget__c": {"type": "CustomObject", "path": None},
                "Account": {"type": "CustomObject", "path": None},
            },
            "edges": []}


def story_doc():
    return {
        "schemaVersion": 1, "storyId": STORY, "slug": SLUG, "status": "confirmed", "confirmedBy": WHO,
        "squad": "Service Ops", "persona": "Service agent", "goal": "Resize a widget",
        "benefit": "Widgets fit the page", "inScope": ["Widget size"], "outOfScope": [],
        "nonFunctional": [], "openQuestions": [],
        "acceptanceCriteria": [
            {"id": "AC-1", "given": "a widget of size 2", "when": "the agent sets size 3",
             "then": "the widget size is 3", "examples": ["2 -> 3"], "source": "stated"},
            {"id": "AC-2", "given": "a widget of size 3", "when": "the agent sets size 0",
             "then": "the save is refused with the message \"size must be positive\"",
             "examples": ["3 -> 0 refused"], "source": "stated"}],
        "edgeCases": [
            {"id": "EC-1", "category": "blank", "component": "Widget__c.Size__c",
             "detail": "Size is blank on legacy widgets", "evidence": FIELD + ":1",
             "confidence": "Confirmed", "becameCriterion": None, "reason": "Kept as an edge case"},
            {"id": "EC-2", "category": "bulk", "component": "WidgetService",
             "detail": "Two hundred widgets resized in one save", "evidence": None,
             "confidence": "Unverifiable", "becameCriterion": "AC-1", "reason": None}],
        "droppedSeeds": [], "overlaps": [], "seeds": ["widget"]}


def design_doc(chosen="OPT-2"):
    return {
        "schemaVersion": 1, "storyId": STORY, "slug": SLUG, "status": "confirmed",
        "confirmedBy": WHO, "chosenOption": chosen,
        "options": [
            {"id": "OPT-1", "title": "Do nothing", "summary": "Keep the current widget service.",
             "doNothing": True, "components": [],
             "tradeOffs": [{"criterion": "reuse", "note": "No change."}],
             "impactSummary": "No metadata changes."},
            {"id": "OPT-2", "title": "Extend WidgetService", "summary": "Add a resize method.",
             "doNothing": False,
             "components": [{"api": "WidgetService", "type": "ApexClass", "changeType": "modify",
                             "evidence": CLS + ":1", "confidence": "Confirmed"}],
             "tradeOffs": [{"criterion": "maintainability", "note": "One class holds the logic."}],
             "impactSummary": "One class changes."},
            {"id": "OPT-3", "title": "New resize flow", "summary": "A record-triggered flow.",
             "doNothing": False,
             "components": [{"api": "WidgetResize", "type": "Flow", "changeType": "new",
                             "evidence": None, "confidence": "Inferred"}],
             "tradeOffs": [{"criterion": "maintainability", "note": "Logic split across tools."}],
             "impactSummary": "One flow is added."}],
        "recommendation": {"optionId": "OPT-2", "reasons": ["Reuses the existing service."]},
        "provenance": {"indexStamp": {"commit": "feedc0de"}, "frameworkVersion": "0.1.0",
                       "model": "m", "assistantVersion": "n/a", "sourceRoot": SRC}}


def comp(api, typ, change, evidence=None, path=None, confidence="Confirmed"):
    return {"api": api, "type": typ, "changeType": change, "impact": "Medium",
            "confidence": confidence, "hop": 0, "evidence": evidence, "path": path}


def default_components():
    return [comp("WidgetService", "ApexClass", "modify", CLS + ":1", CLS),
            comp("Account", "CustomObject", "review", None, None, "Unverifiable")]


def impact_doc(stamp, components=None, chosen="OPT-2"):
    return {"schemaVersion": 1, "storyId": STORY, "slug": SLUG, "squad": "Service Ops",
            "status": "in-flight", "confirmedBy": WHO, "designOption": chosen, "chosenOption": chosen,
            "provenance": {"indexStamp": {"commit": stamp}, "frameworkVersion": "0.1.0",
                           "model": "m", "assistantVersion": "n/a", "hops": 1},
            "components": default_components() if components is None else components,
            "decisions": [], "unknowns": []}


_ROOTS = []


def make_repo(components=None, story=None, design=None, impact_chosen="OPT-2", stamp=None,
              source_root=SRC, extra_nodes=None, extra_files=None):
    """A committed temp repo; returns (root, index_dir, stamp)."""
    if shutil.which("git") is None:
        raise SkipTest("git unavailable")
    os.makedirs(CTX, exist_ok=True)
    root = tempfile.mkdtemp(prefix="package_", dir=CTX)
    _ROOTS.append(root)
    if git(root, "init", "-q").returncode != 0:
        raise SkipTest("git init failed")
    write(os.path.join(root, ".ai-framework.json"),
          json.dumps({"startingPoint": "existing", "sourceRoot": source_root}) + "\n")
    for p in (CLS, TEST_CLS, HELPER):
        name = os.path.basename(p)[:-4]
        write(os.path.join(root, p), "public with sharing class %s {\n}\n" % name)
        write(os.path.join(root, p + "-meta.xml"), "<ApexClass/>\n")
    write(os.path.join(root, TRIGGER), "trigger WidgetTrigger on Widget__c (before update) {\n}\n")
    write(os.path.join(root, TRIGGER + "-meta.xml"), "<ApexTrigger/>\n")
    for f in ("widgetCard.js", "widgetCard.html", "widgetCard.js-meta.xml", "__tests__/widgetCard.test.js",
              ".DS_Store"):
        write(os.path.join(root, LWC, f), "// x\n")
    write(os.path.join(root, FIELD), "<CustomField/>\n")
    for p, text in (extra_files or {}).items():
        write(os.path.join(root, p), text)
    src_commit = commit_all(root, "source")
    idx = index_doc()
    idx["stamp"]["commit"] = src_commit
    idx["nodes"].update(extra_nodes or {})
    # Outside the repo: a committed index would itself be source under sourceRoot ".".
    index_dir = tempfile.mkdtemp(prefix="package_idx_", dir=CTX)
    _ROOTS.append(index_dir)
    write(os.path.join(index_dir, "metadata.json"), json.dumps(idx, indent=1) + "\n")
    stamp = stamp or src_commit
    folder = os.path.join(root, FOLDER)
    write(os.path.join(folder, "story.json"), json.dumps(story or story_doc(), indent=2) + "\n")
    write(os.path.join(folder, "design.json"), json.dumps(design or design_doc(), indent=2) + "\n")
    write(os.path.join(folder, "impact.json"),
          json.dumps(impact_doc(stamp, components, impact_chosen), indent=2) + "\n")
    commit_all(root, "records")
    return root, index_dir, stamp


def run(root, index_dir, *extra, story=STORY, env_extra=None):
    env = None
    if env_extra:
        env = dict(os.environ)
        env.update(env_extra)
    p = subprocess.run([sys.executable, PACKAGE, story, "--root", root, "--index", index_dir] + list(extra),
                       capture_output=True, text=True, timeout=120, env=env)
    return p.returncode, p.stdout + p.stderr


def load_pkg(root):
    with open(os.path.join(root, FOLDER, "build-package.json"), encoding="utf-8") as fh:
        return json.load(fh)


def no_package(root):
    return not os.path.lexists(os.path.join(root, FOLDER, "build-package.json")) and \
        not os.path.lexists(os.path.join(root, FOLDER, "build-package.md"))


# ---- cases ----

def case_builds_package():
    root, idx, stamp = make_repo()
    code, out = run(root, idx)
    assert code == 0, out
    pkg = load_pkg(root)
    assert pkg["schemaVersion"] == 1 and pkg["storyId"] == STORY and pkg["slug"] == SLUG, pkg
    # AC-1, AC-2 and the kept EC-1; EC-2 became AC-1 and is covered by it.
    assert [c["id"] for c in pkg["criteria"]] == ["AC-1", "AC-2", "EC-1"], pkg["criteria"]
    assert pkg["criteria"][0] == {"id": "AC-1", "given": "a widget of size 2", "when": "the agent sets size 3",
                                  "then": "the widget size is 3", "examples": ["2 -> 3"]}
    ec = pkg["criteria"][2]
    assert ec["then"] == "Size is blank on legacy widgets" and ec["given"] == "Widget__c.Size__c", ec
    assert pkg["design"] == {"chosenOption": "OPT-2", "reasons": ["Reuses the existing service."],
                             "rejected": [{"id": "OPT-1", "title": "Do nothing"},
                                          {"id": "OPT-3", "title": "New resize flow"}]}, pkg["design"]
    assert pkg["scope"]["modify"] == [CLS, CLS + "-meta.xml"], pkg["scope"]
    assert pkg["scope"]["create"] == [], pkg["scope"]
    assert pkg["done"] == ["python3 tools/code/check_trace.py --skeletons %s" % STORY,
                           "python3 tools/code/check_rules.py --from-config",
                           "python3 tools/code/check_trace.py %s" % STORY], pkg["done"]
    ids = [r["id"] for r in pkg["rules"]]
    assert "apex-sharing" in ids and "apex-test-naming" in ids, ids
    assert all(r["check"] == "python3 tools/code/check_rules.py" for r in pkg["rules"])
    prov = pkg["provenance"]
    assert prov["indexStamp"] == {"commit": stamp}, prov
    assert prov["confirmedBy"] == {"story": WHO, "design": WHO, "impact": WHO}, prov
    assert all(len(prov[k]) == 40 for k in ("story", "design", "impact")), prov
    with open(os.path.join(root, FOLDER, "build-package.json"), encoding="utf-8", newline="") as fh:
        assert fh.read() == json.dumps(pkg, indent=2, sort_keys=True) + "\n"
    with open(os.path.join(root, FOLDER, "build-package.md"), encoding="utf-8") as fh:
        md = fh.read()
    assert STORY in md and "AC-1" in md and CLS in md, md
    for word in ("should", "approve", "block", "we recommend"):
        assert word not in md.lower(), word


def case_refuses_unconfirmed_story():
    s = story_doc()
    s["status"] = "draft"
    del s["confirmedBy"]
    root, idx, _ = make_repo(story=s)
    code, out = run(root, idx)
    assert code == 1 and "story.json" in out, out
    assert no_package(root)


def case_refuses_story_with_ac_findings():
    s = story_doc()
    s["acceptanceCriteria"][0]["then"] = "the widget resizes quickly"
    root, idx, _ = make_repo(story=s)
    code, out = run(root, idx)
    assert code == 1 and "acceptance criteria" in out and "vague-word" in out, out
    assert no_package(root)


def case_refuses_unconfirmed_design():
    d = design_doc()
    d["status"] = "draft"
    del d["confirmedBy"]
    del d["chosenOption"]
    root, idx, _ = make_repo(design=d)
    code, out = run(root, idx)
    assert code == 1 and "design.json" in out, out
    assert no_package(root)


def case_refuses_option_mismatch():
    root, idx, _ = make_repo(design=design_doc(chosen="OPT-3"))
    code, out = run(root, idx)
    assert code == 1 and "OPT-2" in out and "OPT-3" in out and "chosenOption" in out, out
    assert no_package(root)


def case_refuses_stale_stamp():
    root, idx, _ = make_repo()
    write(os.path.join(root, CLS), "public with sharing class WidgetService {\n  // edited\n}\n")
    commit_all(root, "source changed after the stamp")
    code, out = run(root, idx)
    assert code == 1 and "stale" in out and SRC in out, out
    assert no_package(root)


def case_stale_check_ignores_literal_pathspecs_env():
    # GIT_LITERAL_PATHSPECS=1 would make ':(literal)src' a literal path and the diff empty; GIT_DIR and
    # GIT_WORK_TREE would point git elsewhere. package.py strips every GIT_* variable, so it stays stale.
    root, idx, _ = make_repo()
    write(os.path.join(root, HELPER), "public with sharing class WidgetHelper {\n  // edited\n}\n")
    commit_all(root, "source changed after the stamp")
    bogus = os.path.join(root, "no-such-git-dir")
    for env in ({"GIT_LITERAL_PATHSPECS": "1"},
                {"GIT_LITERAL_PATHSPECS": "1", "GIT_DIR": bogus, "GIT_WORK_TREE": bogus}):
        code, out = run(root, idx, env_extra=env)
        assert code == 1 and "stale" in out and HELPER in out, (env, out)
        assert no_package(root)


def case_refuses_new_already_in_index():
    other = BASE + "/classes/sub/Dup.cls"
    comps = default_components() + [comp("dup", "ApexClass", "new", None, None, "Inferred")]
    root, idx, _ = make_repo(components=comps,
                             extra_nodes={"Dup": {"type": "ApexClass", "path": other, "isTest": False}},
                             extra_files={other: "public with sharing class Dup {\n}\n",
                                          other + "-meta.xml": "<ApexClass/>\n"})
    code, out = run(root, idx)
    assert code == 1 and "already exists as index node Dup" in out and other in out, out
    assert no_package(root)


def case_md_write_failure_removes_json():
    root, idx, _ = make_repo()
    os.makedirs(os.path.join(root, FOLDER, "build-package.md"))  # a folder: the .md write fails
    code, out = run(root, idx)
    assert code == 2 and "build-package.md" in out and "removed" in out, out
    assert not os.path.lexists(os.path.join(root, FOLDER, "build-package.json")), out


def case_refuses_unknown_stamp():
    root, idx, _ = make_repo(stamp="0123456789abcdef0123456789abcdef01234567")
    code, out = run(root, idx)
    assert code == 1 and "stale" in out and "unknown or unreachable" in out, out
    assert no_package(root)


def case_committed_impact_not_stale():
    root, idx, _ = make_repo()
    write(os.path.join(root, "impacts", "squads.json"), json.dumps({"squads": ["Service Ops"]}) + "\n")
    write(os.path.join(root, "docs", "note.md"), "outside the source root\n")
    commit_all(root, "only impacts/ and docs changed")
    code, out = run(root, idx)
    assert code == 0, out


def case_source_root_dot_not_stale_from_impacts():
    # sourceRoot ".": the impact's own commit (impacts/ only) is excluded from the stale diff, so the
    # package builds; its paths carry no "./" prefix. A later source change still makes the stamp stale.
    root, idx, _ = make_repo(source_root=".")
    write(os.path.join(root, "impacts", "squads.json"), json.dumps({"squads": ["Service Ops"]}) + "\n")
    commit_all(root, "another impacts/ change")
    code, out = run(root, idx)
    assert code == 0, out
    pkg = load_pkg(root)
    assert pkg["scope"]["modify"] == [CLS, CLS + "-meta.xml"], pkg["scope"]
    write(os.path.join(root, CLS), "public with sharing class WidgetService {\n  // edited\n}\n")
    commit_all(root, "source changed after the stamp")
    code, out = run(root, idx)
    assert code == 1 and "stale" in out and CLS in out, out


def case_refuses_delete():
    comps = default_components() + [comp("WidgetHelper", "ApexClass", "delete", HELPER + ":1", HELPER)]
    root, idx, _ = make_repo(components=comps)
    code, out = run(root, idx)
    assert code == 1 and "deletes are done by a human in this version" in out and "WidgetHelper" in out, out
    assert no_package(root)


def case_refuses_scope_escape():
    # A source root under tools/ makes every entry a reserved framework path. (With sourceRoot "."
    # the impact's own commit would already make the stamp stale.)
    bad = "tools/app/force-app/main/default/classes/Evil.cls"
    comps = [comp("Evil", "ApexClass", "modify", bad + ":1", bad)]
    root, idx, _ = make_repo(components=comps, source_root="tools/app",
                             extra_nodes={"Evil": {"type": "ApexClass", "path": bad, "isTest": False}},
                             extra_files={bad: "public with sharing class Evil {\n}\n",
                                          bad + "-meta.xml": "<ApexClass/>\n"})
    code, out = run(root, idx)
    assert code == 1 and "reserved framework path" in out, out
    assert no_package(root)
    # An index node outside sourceRoot.
    out_src = "other/force-app/main/default/classes/Stray.cls"
    comps = default_components() + [comp("Stray", "ApexClass", "modify", out_src + ":1", out_src)]
    root, idx, _ = make_repo(components=comps,
                             extra_nodes={"Stray": {"type": "ApexClass", "path": out_src, "isTest": False}},
                             extra_files={out_src: "public with sharing class Stray {\n}\n",
                                          out_src + "-meta.xml": "<ApexClass/>\n"})
    code, out = run(root, idx)
    assert code == 1 and "outside sourceRoot" in out, out
    assert no_package(root)
    # A '..' in an index path.
    dotted = SRC + "/../tools/x/Dot.cls"
    comps = default_components() + [comp("Dot", "ApexClass", "modify", CLS + ":1", None)]
    root, idx, _ = make_repo(components=comps,
                             extra_nodes={"Dot": {"type": "ApexClass", "path": dotted, "isTest": False}})
    code, out = run(root, idx)
    assert code == 1 and "'..'" in out, out
    assert no_package(root)


def case_refuses_unknown_new_type():
    comps = default_components() + [comp("WidgetResize", "Flow", "new")]
    root, idx, _ = make_repo(components=comps)
    code, out = run(root, idx)
    assert code == 1 and "Flow" in out and "WidgetResize" in out, out
    assert no_package(root)


def case_refuses_modify_not_in_index():
    comps = default_components() + [comp("Ghost", "ApexClass", "modify", CLS + ":1", None)]
    root, idx, _ = make_repo(components=comps)
    code, out = run(root, idx)
    assert code == 1 and "Ghost" in out and "index" in out, out


def case_companions_listed():
    comps = [comp("WidgetService", "ApexClass", "modify", CLS + ":1", CLS),
             comp("WidgetTrigger", "ApexTrigger", "modify", TRIGGER + ":1", TRIGGER),
             comp("widgetCard", "LightningComponentBundle", "modify", LWC + "/widgetCard.js:1", LWC),
             comp("Widget__c.Size__c", "CustomField", "modify", FIELD + ":1", FIELD),
             comp("WidgetPanel", "ApexClass", "new"),
             comp("widgetBadge", "LightningComponentBundle", "new"),
             comp("Widget__c.Colour__c", "CustomField", "new"),
             comp("Gadget__c", "CustomObject", "new")]
    root, idx, _ = make_repo(components=comps)
    code, out = run(root, idx)
    assert code == 0, out
    pkg = load_pkg(root)
    modify = pkg["scope"]["modify"]
    assert modify == sorted(modify), modify
    for p in (CLS, CLS + "-meta.xml", TRIGGER, TRIGGER + "-meta.xml", FIELD,
              LWC + "/widgetCard.html", LWC + "/widgetCard.js", LWC + "/widgetCard.js-meta.xml"):
        assert p in modify, (p, modify)
    assert not any(".DS_Store" in p or "__tests__" in p for p in modify), modify
    create = [(c["api"], c["type"], c["path"]) for c in pkg["scope"]["create"]]
    cls_dir = BASE + "/classes/"
    for entry in (("WidgetPanel", "ApexClass", cls_dir + "WidgetPanel.cls"),
                  ("WidgetPanel", "ApexClass", cls_dir + "WidgetPanel.cls-meta.xml"),
                  ("widgetBadge", "LightningComponentBundle", BASE + "/lwc/widgetBadge/widgetBadge.js"),
                  ("widgetBadge", "LightningComponentBundle", BASE + "/lwc/widgetBadge/widgetBadge.html"),
                  ("widgetBadge", "LightningComponentBundle",
                   BASE + "/lwc/widgetBadge/widgetBadge.js-meta.xml"),
                  ("Widget__c.Colour__c", "CustomField", BASE + "/objects/Widget__c/fields/Colour__c.field-meta.xml"),
                  ("Gadget__c", "CustomObject", BASE + "/objects/Gadget__c/Gadget__c.object-meta.xml")):
        assert entry in create, (entry, create)
    assert "pnpm exec sfdx-lwc-jest" in pkg["done"], pkg["done"]


def case_tests_derived():
    comps = [comp("WidgetService", "ApexClass", "modify", CLS + ":1", CLS),
             comp("WidgetService_Test", "ApexClass", "modify", TEST_CLS + ":1", TEST_CLS),
             comp("WidgetHelper", "ApexClass", "modify", HELPER + ":1", HELPER),
             comp("widgetCard", "LightningComponentBundle", "modify", LWC + "/widgetCard.js:1", LWC),
             comp("WidgetPanel", "ApexClass", "new"),
             comp("widgetBadge", "LightningComponentBundle", "new")]
    root, idx, _ = make_repo(components=comps)
    code, out = run(root, idx)
    assert code == 0, out
    pkg = load_pkg(root)
    tests = pkg["scope"]["tests"]
    cls_dir = BASE + "/classes/"
    expected = sorted([TEST_CLS, TEST_CLS + "-meta.xml",
                       cls_dir + "WidgetHelper_Test.cls", cls_dir + "WidgetHelper_Test.cls-meta.xml",
                       cls_dir + "WidgetPanel_Test.cls", cls_dir + "WidgetPanel_Test.cls-meta.xml",
                       LWC + "/__tests__/widgetCard.test.js",
                       BASE + "/lwc/widgetBadge/__tests__/widgetBadge.test.js"])
    assert tests == expected, tests
    # A test class listed as modify is a test, never a non-test scope entry, and gets no _Test_Test.
    assert TEST_CLS not in pkg["scope"]["modify"], pkg["scope"]["modify"]
    assert not any("_Test_Test" in p for p in tests), tests


def case_refuses_nothing_to_build():
    comps = [comp("Account", "CustomObject", "review", None, None, "Unverifiable")]
    root, idx, _ = make_repo(components=comps)
    code, out = run(root, idx)
    assert code == 1 and "nothing to build" in out, out


def case_missing_index_exit_2():
    root, _, _ = make_repo()
    code, out = run(root, os.path.join(root, "no-such-index"))
    assert code == 2, out
    assert no_package(root)


def case_bad_story_id_exit_2():
    root, idx, _ = make_repo()
    code, out = run(root, idx, story="not-a-story")
    assert code == 2, out


def case_no_folder_refused():
    root, idx, _ = make_repo()
    code, out = run(root, idx, story="DEMO-9999")
    assert code == 1 and "DEMO-9999" in out, out


def case_refuses_root_not_toplevel():
    root, idx, _ = make_repo()
    sub = os.path.join(root, "nested")
    os.makedirs(os.path.join(sub, "impacts"))
    shutil.copytree(os.path.join(root, FOLDER), os.path.join(sub, FOLDER))
    write(os.path.join(sub, ".ai-framework.json"), json.dumps({"sourceRoot": "."}) + "\n")
    code, out = run(sub, idx)
    assert code == 1 and "top level" in out, out


def case_deterministic():
    comps = [comp("WidgetService", "ApexClass", "modify", CLS + ":1", CLS),
             comp("widgetCard", "LightningComponentBundle", "modify", LWC + "/widgetCard.js:1", LWC),
             comp("WidgetPanel", "ApexClass", "new")]
    root, idx, _ = make_repo(components=comps)
    code, out = run(root, idx)
    assert code == 0, out
    outs = []
    for name in ("build-package.json", "build-package.md"):
        with open(os.path.join(root, FOLDER, name), "rb") as fh:
            outs.append(fh.read())
    code, out = run(root, idx)
    assert code == 0, out
    for name, first in zip(("build-package.json", "build-package.md"), outs):
        with open(os.path.join(root, FOLDER, name), "rb") as fh:
            assert fh.read() == first, name
        assert b"\r\n" not in first, name


def case_refuses_symlinked_output():
    root, idx, _ = make_repo()
    target = os.path.join(root, "elsewhere.json")
    write(target, "{}\n")
    try:
        os.symlink(target, os.path.join(root, FOLDER, "build-package.json"))
    except (OSError, NotImplementedError):
        raise SkipTest("symlinks unavailable")
    code, out = run(root, idx)
    assert code == 1 and "symlink" in out, out
    with open(target, encoding="utf-8") as fh:
        assert fh.read() == "{}\n"


def case_validate_package_matches_guard_rules():
    import importlib.util
    spec = importlib.util.spec_from_file_location("package_mod", PACKAGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    good = {"schemaVersion": 1, "storyId": STORY, "slug": SLUG,
            "criteria": [{"id": "AC-1"}],
            "scope": {"modify": [CLS], "create": [], "tests": []}}
    assert mod.validate_package(good, SRC) == []
    for mutate, text in (
            (lambda p: p.update(schemaVersion=True), "schemaVersion"),
            (lambda p: p.update(schemaVersion=1.0), "schemaVersion"),
            (lambda p: p.update(criteria=[]), "criteria"),
            (lambda p: p.update(criteria=[{"id": "OQ-1"}]), "AC-<n>"),
            (lambda p: p.update(criteria=[{"id": "AC-1"}, {"id": "AC-1"}]), "duplicate criterion"),
            (lambda p: p["scope"].update(modify=["/abs/x.cls"]), "absolute"),
            (lambda p: p["scope"].update(modify=[SRC + "/a/../b.cls"]), "'..'"),
            (lambda p: p["scope"].update(modify=[SRC + "/a/*.cls"]), "glob"),
            (lambda p: p["scope"].update(modify=[SRC + "/a\tb.cls"]), "control character"),
            (lambda p: p["scope"].update(modify=["other/x.cls"]), "outside sourceRoot"),
            (lambda p: p["scope"].update(modify=[CLS, CLS]), "duplicate entry"),
            (lambda p: p["scope"].update(create=[{"api": "X", "type": "ApexClass"}]), "no string path"),
            (lambda p: p["scope"].update(tests="x"), "scope.tests is not a list")):
        pkg = json.loads(json.dumps(good))
        mutate(pkg)
        errs = mod.validate_package(pkg, SRC)
        assert errs and any(text in e for e in errs), (text, errs)
    assert any("reserved" in e for e in mod.validate_package(
        dict(good, scope={"modify": ["impacts/x.cls"], "create": [], "tests": []}), "."))


FIXTURES = os.path.join(HERE, "scope_fixtures.json")
SCOPE_CORE = os.path.join(REPO, "tools", "guard", "scope_core.py")


def _package_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location("package_mod", PACKAGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fixture_runs():
    """[(case, pkg, top)] for the shared scope fixtures, in a temp folder holding src/, elsewhere/ and the
    src/link symlink the fixtures expect. The symlink case is left out where symlinks cannot be made."""
    import copy
    with open(FIXTURES, encoding="utf-8") as fh:
        doc = json.load(fh)
    os.makedirs(CTX, exist_ok=True)
    top = tempfile.mkdtemp(prefix="scope_fx_", dir=CTX)
    _ROOTS.append(top)
    os.makedirs(os.path.join(top, "src"))
    os.makedirs(os.path.join(top, "elsewhere"))
    try:
        os.symlink(os.path.join(top, "elsewhere"), os.path.join(top, "src", "link"))
        can_link = True
    except (OSError, NotImplementedError):
        can_link = False
    top = os.path.realpath(top)
    runs = []
    for case in doc["cases"]:
        if case["name"] == "symlinked-entry" and not can_link:
            continue
        pkg = copy.deepcopy(case["pkg"])
        fill = case.get("fill")
        if fill:
            pkg["scope"][fill["key"]] = [fill["pattern"] % n for n in range(fill["count"])]
        runs.append((case, pkg, top))
    return doc, runs


def case_shared_scope_fixtures_package_verdicts():
    # package.validate_package reaches each shared fixture's recorded verdict (no guard core needed).
    mod = _package_mod()
    doc, runs = _fixture_runs()
    assert len(runs) >= 10 and any(c["accept"] for c, _, _ in runs) and not all(c["accept"] for c, _, _ in runs)
    for case, pkg, top in runs:
        got = mod.validate_package(pkg, case["sourceRoot"], root=top) == []
        assert got == case["accept"], (case["sourceRoot"], case["name"], mod.validate_package(pkg, case["sourceRoot"], root=top))


def case_drift_package_vs_guard_scope_core():
    # The drift check behind "package.py mirrors scope_core's validation": over the shared fixtures, the
    # guard's own tools/guard/scope_core.py and package.validate_package give the same verdict. SKIP while the
    # core is absent (the WS8 guard patch not applied); a present core without _validate fails.
    if not os.path.isfile(SCOPE_CORE):
        raise SkipTest("tools/guard/scope_core.py is absent (WS8 guard patch not applied)")
    import types
    with open(SCOPE_CORE, "rb") as fh:
        source = fh.read()
    core = types.ModuleType("scope_core_for_drift")
    core.__file__ = SCOPE_CORE
    exec(compile(source, SCOPE_CORE, "exec"), core.__dict__)
    assert callable(getattr(core, "_validate", None)), "scope_core has no _validate; the drift check cannot run"
    mod = _package_mod()
    doc, runs = _fixture_runs()
    active = "%s-%s" % (doc["storyId"], doc["slug"])
    drift = []
    for case, pkg, top in runs:
        import copy
        mine = mod.validate_package(copy.deepcopy(pkg), case["sourceRoot"], root=top) == []
        guard = core._validate(top, case["sourceRoot"], active, copy.deepcopy(pkg)) is None
        if mine != guard or mine != case["accept"]:
            drift.append((case["sourceRoot"], case["name"], mine, guard))
    assert not drift, drift


def case_register_scope_prefers_package():
    comps = [comp("WidgetService", "ApexClass", "modify", CLS + ":1", CLS),
             comp("WidgetPanel", "ApexClass", "new")]
    root, idx, _ = make_repo(components=comps)
    # Before a package exists: today's behaviour, marked as from the impact.
    p = subprocess.run([sys.executable, REGISTER, "scope", STORY, "--root", root],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert data["source"] == "impact" and data["components"] == ["WidgetService", "WidgetPanel"], data
    assert "paths" not in data, data
    code, out = run(root, idx)
    assert code == 0, out
    p = subprocess.run([sys.executable, REGISTER, "scope", STORY, "--root", root],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    pkg = load_pkg(root)
    expected = sorted(set(pkg["scope"]["modify"] + [c["path"] for c in pkg["scope"]["create"]]
                          + pkg["scope"]["tests"]))
    assert data["source"] == "build-package" and data["paths"] == expected, data
    assert data["storyId"] == STORY and data["squad"] == "Service Ops", data
    assert data["components"] == ["WidgetService", "WidgetPanel"], data
    assert BASE + "/classes/WidgetPanel.cls" in data["paths"], data


def cleanup():
    for r in _ROOTS:
        shutil.rmtree(r, ignore_errors=True)


def main():
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("case_")]
    try:
        return run_tests(tests)
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
