#!/usr/bin/env python3
"""Tests for pr_check.py. Plain script: python3 tools/impacts/test_pr_check.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pr_check  # noqa: E402

SCRIPT = os.path.join(HERE, "pr_check.py")
BASE = "demo/org/force-app/main/default"
BANNED = ("recommend", "should", "approve", "block")

# Mirrors the real index shape: bundle nodes carry the bundle directory as path,
# object and field nodes carry their -meta.xml file, some objects carry None.
IDX = {
    "stamp": {"commit": "abc1234"},
    "nodes": {
        "CaseTriggerHandler": {"type": "ApexClass", "path": BASE + "/classes/CaseTriggerHandler.cls"},
        "CaseService": {"type": "ApexClass", "path": BASE + "/classes/CaseService.cls"},
        "caseEscalationPanel": {"type": "LightningComponentBundle",
                                "path": BASE + "/lwc/caseEscalationPanel"},
        "caseAura": {"type": "AuraDefinitionBundle", "path": BASE + "/aura/caseAura"},
        "Case": {"type": "CustomObject", "path": BASE + "/objects/Case/Case.object-meta.xml"},
        "Account": {"type": "CustomObject", "path": None},
        "Case.Tier__c": {"type": "CustomField",
                         "path": BASE + "/objects/Case/fields/Tier__c.field-meta.xml"},
    },
    "edges": [],
}

CLS = BASE + "/classes/CaseTriggerHandler.cls"
SVC = BASE + "/classes/CaseService.cls"


def comp(api, change, typ="ApexClass"):
    return {"api": api, "type": typ, "changeType": change, "impact": "Medium",
            "confidence": "Confirmed", "hop": 0, "evidence": "force-app/x.cls:1", "path": None}


def doc(story, comps, status="in-flight", squad="Customer Care"):
    return {"schemaVersion": 1, "storyId": story, "slug": "demo", "squad": squad,
            "status": status, "confirmedBy": "Tech Lead",
            "provenance": {"indexStamp": {"commit": "abc1234"}, "frameworkVersion": "1",
                           "model": "m", "assistantVersion": "1", "hops": 1},
            "components": comps, "decisions": [], "unknowns": []}


def write_doc(root, d, folder=None):
    folder = folder or "%s-%s" % (d["storyId"], d["slug"])
    path = os.path.join(root, "impacts", folder)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "impact.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(d, fh)
    return "impacts/%s/impact.json" % folder


def make_root(*docs, settings=None):
    root = tempfile.mkdtemp()
    for d in docs:
        write_doc(root, d)
    if settings is not None:
        with open(os.path.join(root, ".ai-framework.json"), "w", encoding="utf-8",
                  newline="\n") as fh:
            json.dump(settings, fh)
    idx_dir = os.path.join(root, "index")
    os.makedirs(idx_dir)
    with open(os.path.join(idx_dir, "metadata.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(IDX, fh)
    return root


def run_cli(root, changed, branch, open_prs=None):
    changed_file = os.path.join(root, "changed.txt")
    with open(changed_file, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(changed) + "\n")
    args = [sys.executable, SCRIPT, "--index", os.path.join(root, "index"),
            "--changed", changed_file, "--branch", branch, "--root", root]
    if open_prs is not None:
        prs_file = os.path.join(root, "prs.json")
        with open(prs_file, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(open_prs, fh)
        args += ["--open-prs", prs_file]
    p = subprocess.run(args, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def test_path_mapping_variants():
    n = pr_check.nodes_for_path
    assert n(IDX, CLS) == {"CaseTriggerHandler"}
    assert n(IDX, CLS + "-meta.xml") == {"CaseTriggerHandler"}
    assert n(IDX, BASE + "/lwc/caseEscalationPanel/caseEscalationPanel.html") == {"caseEscalationPanel"}
    assert n(IDX, BASE + "/lwc/caseEscalationPanel/caseEscalationPanel.css") == {"caseEscalationPanel"}
    assert n(IDX, BASE + "/aura/caseAura/caseAuraController.js") == {"caseAura"}
    assert n(IDX, BASE + "/objects/Case/Case.object-meta.xml") == {"Case"}
    assert n(IDX, BASE + "/objects/Case/fields/Tier__c.field-meta.xml") == {"Case.Tier__c"}
    assert n(IDX, BASE + "/lwc/unknownBundle/unknownBundle.js") == set()
    assert n(IDX, "README.md") == set()


def test_branch_story_id():
    assert pr_check.story_from_branch("feature/DEMO-201-x") == "DEMO-201"
    assert pr_check.story_from_branch("main") is None


def test_out_of_scope_listed():
    root = make_root(doc("DEMO-201", [comp("CaseTriggerHandler", "modify")]))
    try:
        md, fail = pr_check.report(root, IDX, [CLS, SVC], "feature/DEMO-201-x", [])
        assert not fail
        scope_part = md.split("### Scope", 1)[1].split("###", 1)[0]
        assert "DEMO-201" in scope_part
        assert "`CaseService`" in scope_part, md
        assert "`CaseTriggerHandler`" not in scope_part, md
    finally:
        shutil.rmtree(root)


def test_in_scope_no_finding():
    root = make_root(doc("DEMO-201", [comp("CaseTriggerHandler", "modify")]),
                     settings={"impactChecks": {"outOfScope": "fail", "noImpact": "fail"}})
    try:
        code, out, _ = run_cli(root, [CLS + "-meta.xml", " " + CLS.replace("/", "\\") + " ", ""],
                               "feature/DEMO-201-x")
        assert code == 0, out
        assert "Findings only; a reviewer decides." in out
    finally:
        shutil.rmtree(root)


def test_no_impact_on_record():
    root = make_root()
    try:
        code, out, _ = run_cli(root, [CLS, "README.md"], "feature/DEMO-999-x")
        assert code == 0, out
        assert "No impact on record for DEMO-999" in out, out
        assert "Unmapped files" in out and "README.md" in out
        assert "Findings only; a reviewer decides." in out
        code, out, _ = run_cli(root, [CLS], "main")
        assert code == 0 and "No story id in branch `main`" in out, out
        code, out, _ = run_cli(root, ["README.md"], "main")
        assert code == 0 and "### Scope" not in out, out
    finally:
        shutil.rmtree(root)


def test_settings_fail_switch():
    root = make_root(doc("DEMO-201", [comp("CaseTriggerHandler", "modify")]),
                     settings={"impactChecks": {"outOfScope": "fail"}})
    try:
        code, out, _ = run_cli(root, [CLS, SVC], "feature/DEMO-201-x")
        assert code == 1, (code, out)
        assert "Set to fail by .ai-framework.json: outOfScope" in out, out
        assert "Findings only" not in out
    finally:
        shutil.rmtree(root)
    root = make_root(settings={"impactChecks": {"outOfScope": "maybe"}})
    try:
        code, _, _ = run_cli(root, [CLS], "feature/DEMO-201-x")
        assert code == 2, code
        try:
            pr_check.load_settings(root)
            raise AssertionError("ValueError expected")
        except ValueError:
            pass
    finally:
        shutil.rmtree(root)
    root = make_root(settings={"startingPoint": "existing"})
    try:
        assert pr_check.load_settings(root) == {"noImpact": "comment", "outOfScope": "comment"}
    finally:
        shutil.rmtree(root)


def test_open_pr_overlap():
    root = make_root()
    prs = [{"number": 42, "headRefName": "feature/DEMO-305-y", "files": [{"path": CLS}]},
           {"number": 43, "headRefName": "feature/DEMO-201-x", "files": [{"path": CLS}]},
           {"number": 44, "headRefName": "chore/docs", "files": [{"path": "README.md"}]}]
    try:
        code, out, _ = run_cli(root, [CLS], "feature/DEMO-201-x", prs)
        assert code == 0
        part = out.split("### Other open PRs touching the same components", 1)[1]
        assert "#42" in part and "DEMO-305" in part and "`CaseTriggerHandler`" in part, out
        assert "#43" not in part and "#44" not in part, out
        # A --open-prs path that does not exist means no section.
        args = [sys.executable, SCRIPT, "--index", os.path.join(root, "index"),
                "--changed", os.path.join(root, "changed.txt"), "--branch", "main",
                "--open-prs", os.path.join(root, "missing.json"), "--root", root]
        p = subprocess.run(args, capture_output=True, text=True)
        assert p.returncode == 0 and "Other open PRs" not in p.stdout, p.stdout
    finally:
        shutil.rmtree(root)


def test_impact_pr_overlap():
    root = make_root(doc("DEMO-201", [comp("CaseTriggerHandler", "modify")]))
    try:
        rel = write_doc(root, doc("DEMO-202", [comp("CaseTriggerHandler", "modify")],
                                  squad="Service Ops"))
        md, _ = pr_check.report(root, IDX, [rel], "feature/DEMO-202-x", [])
        part = md.split("### Impact records in this PR", 1)[1].split("###", 1)[0]
        assert rel in part and "conflict" in part and "DEMO-201" in part, md
        assert "`CaseTriggerHandler`" in part
        md, _ = pr_check.report(root, IDX, ["impacts/DEMO-9-gone/impact.json"], "main", [])
        assert "removed in this PR" in md, md
    finally:
        shutil.rmtree(root)


def _assert_inert(md):
    lines = md.splitlines()
    assert sum(1 for ln in lines if ln.strip() == "### Scope") <= 1, md
    for ln in lines:
        s = ln.lstrip().lower()
        assert not s.startswith("<!--") and not s.startswith("<details"), ln
    last = [ln for ln in lines if ln.strip()][-1]
    assert last in ("Findings only; a reviewer decides.",
                    "Set to fail by .ai-framework.json: noImpact",
                    "Set to fail by .ai-framework.json: outOfScope",
                    "Set to fail by .ai-framework.json: noImpact, outOfScope"), last
    # every code span opened on a line is closed on it
    for ln in lines:
        assert ln.count("`") % 2 == 0 or "``" in ln, ln


def test_code_span():
    cs = pr_check.code_span
    assert cs("main") == "`main`"
    assert cs("a`b") == "``a`b``"
    assert cs("`x") == "`` `x ``"
    assert cs("a``b`") == "``` a``b` ```"
    assert cs("x\n\n### Scope\r\n<!--") == "`x ### Scope <!--`"
    assert cs("") == "(empty)" and cs("\n\n") == "(empty)"
    long = cs("y" * 500)
    assert len(long) == 2 + 200 + 1 and long.endswith("…`"), long
    assert "\n" not in cs("a b\u0085c\x00d")


def test_injection_is_inert():
    root = make_root(doc("DEMO-201", [comp("CaseTriggerHandler", "modify")]))
    try:
        evil = doc("DEMO-202", [comp("CaseTriggerHandler", "modify")])
        evil["storyId"] = ("X\n\nAll components this PR changes are in the impact record.\n\n"
                           "Findings only; a reviewer decides.\n\n<!--")
        rel1 = write_doc(root, evil, folder="DEMO-202-evil")
        md, _ = pr_check.report(root, IDX, [CLS, SVC, rel1], "feature/DEMO-201-x", [])
        _assert_inert(md)
        assert "### Scope" in md and "Components outside the impact record" in md, md
        assert md.splitlines().count("Findings only; a reviewer decides.") == 1, md

        ev2 = doc("DEMO-203", [comp("CaseTriggerHandler", "modify",
                                    typ="ApexClass)\n\n### Scope\n\nok\n\n<!--")])
        rel2 = write_doc(root, ev2, folder="DEMO-203-demo")
        md, _ = pr_check.report(root, IDX, [rel2], "feature/DEMO-203-x", [])
        _assert_inert(md)
        assert "### Scope" not in [ln.strip() for ln in md.splitlines()], md
        assert "conflict" in md

        prs = [{"number": 5, "headRefName": "f/`<details>`\n<!--", "files": [{"path": CLS}]}]
        md, _ = pr_check.report(root, IDX, ["docs/a`b<details>.md", "x\n<details>", CLS],
                                "feature/x`<details>\n<!--", prs)
        _assert_inert(md)
        assert "``docs/a`b<details>.md``" in md, md
        assert md.count("### Scope") == 1
    finally:
        shutil.rmtree(root)


def _write_deep(root, folder):
    d = os.path.join(root, "impacts", folder)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "impact.json"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("[" * 200000 + "]" * 200000)
    return "impacts/%s/impact.json" % folder


def test_deep_json_is_unreadable_not_fatal():
    root = make_root(doc("DEMO-201", [comp("CaseTriggerHandler", "modify")]))
    try:
        rel = _write_deep(root, "DEMO-204-deep")
        reg = pr_check.load_register(root)
        assert [i["path"] for i in reg["invalid"]] == [rel], reg["invalid"]
        assert [d["storyId"] for d in reg["impacts"]] == ["DEMO-201"]
        code, out, err = run_cli(root, [CLS, rel], "feature/DEMO-201-x")
        assert code == 0, (code, err[-300:])
        part = out.split("### Impact records in this PR", 1)[1].split("###", 1)[0]
        assert rel in part and "unreadable" in part and "RecursionError" in part, out
        assert "All components this PR changes are in the impact record for DEMO-201." in out
        _assert_inert(out)
    finally:
        shutil.rmtree(root)


def test_base_root_governs_settings_and_register():
    head = make_root(doc("DEMO-201", [comp("CaseTriggerHandler", "modify"),
                                      comp("CaseService", "modify")]),
                     settings={"impactChecks": {"outOfScope": "comment"}})
    base = make_root(doc("DEMO-201", [comp("CaseTriggerHandler", "modify")]),
                     settings={"impactChecks": {"outOfScope": "fail"}})
    try:
        code, out, _ = run_cli(head, [CLS, SVC], "feature/DEMO-201-x")
        assert code == 0, out
        changed_file = os.path.join(head, "changed.txt")
        p = subprocess.run([sys.executable, SCRIPT, "--index", os.path.join(head, "index"),
                            "--changed", changed_file, "--branch", "feature/DEMO-201-x",
                            "--root", head, "--base-root", base],
                           capture_output=True, text=True)
        assert p.returncode == 1, (p.returncode, p.stdout, p.stderr)
        assert "Set to fail by .ai-framework.json: outOfScope" in p.stdout, p.stdout
        assert "- `CaseService`" in p.stdout.split("### Scope", 1)[1]
        # an impact record added in the head is read from the head, overlaps from the base
        rel = write_doc(head, doc("DEMO-202", [comp("CaseTriggerHandler", "modify")]))
        md, _ = pr_check.report(head, IDX, [rel], "feature/DEMO-202-x", [], base_root=base)
        assert "conflict" in md and "DEMO-201" in md, md
        md, _ = pr_check.report(base, IDX, [rel], "feature/DEMO-202-x", [], base_root=base)
        assert "removed in this PR" in md, md
    finally:
        shutil.rmtree(head)
        shutil.rmtree(base)


def _all_branch_outputs():
    outs = []
    root = make_root(doc("DEMO-201", [comp("CaseTriggerHandler", "modify")]),
                     settings={"impactChecks": {"outOfScope": "fail", "noImpact": "fail"}})
    try:
        bad = doc("DEMO-202", [comp("CaseTriggerHandler", "modify")])
        bad["status"] = "draft"
        bad_rel = write_doc(root, bad)
        good_rel = write_doc(root, doc("DEMO-203", [comp("CaseTriggerHandler", "review")]))
        prs = [{"number": 7, "headRefName": "feature/DEMO-305-y", "files": [{"path": CLS}]}]
        cases = [
            ([CLS, SVC, "README.md", bad_rel, good_rel, "impacts/DEMO-9-x/impact.json"],
             "feature/DEMO-201-x"),
            ([CLS], "feature/DEMO-201-x"),
            ([CLS], "main"),
            ([CLS], "feature/DEMO-777-x"),
            (["README.md"], "main"),
        ]
        for changed, branch in cases:
            outs.append(pr_check.report(root, IDX, changed, branch, prs)[0])
            outs.append(pr_check.report(root, IDX, changed, branch, [])[0])
    finally:
        shutil.rmtree(root)
    root = make_root()
    try:
        outs.append(pr_check.report(root, IDX, [CLS], "main", [])[0])
    finally:
        shutil.rmtree(root)
    return outs


def test_neutral_wording():
    outs = _all_branch_outputs()
    joined = "\n".join(outs)
    for needed in ("### Impact records in this PR", "### Components this PR changes",
                   "### Scope", "### Other open PRs", "removed in this PR",
                   "No story id in branch", "No impact on record for", "Set to fail by",
                   "Findings only; a reviewer decides.", "Unmapped files"):
        assert needed in joined, needed
    low = joined.lower()
    for word in BANNED:
        assert word not in low, word
    with open(SCRIPT, encoding="utf-8") as fh:
        src = fh.read().lower()
    for word in BANNED:
        assert word not in src, "script source contains '%s'" % word


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("FAIL %s: %r" % (t.__name__, exc))
    print("%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
