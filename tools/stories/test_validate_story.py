#!/usr/bin/env python3
"""Tests for validate_story.py. Temp trees only; the repo is not written.

Run: python3 tools/stories/test_validate_story.py
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
import validate_story as S  # noqa: E402

CLI = os.path.join(HERE, "validate_story.py")

TMP = tempfile.mkdtemp(prefix="validate_story_")
atexit.register(shutil.rmtree, TMP, True)


def good():
    return {
        "schemaVersion": 1,
        "storyId": "DEMO-301",
        "slug": "service-level-escalation",
        "status": "draft",
        "squad": "Customer Care",
        "persona": "a service agent",
        "goal": "escalate a premium case",
        "benefit": "premium customers are answered first",
        "inScope": ["Case escalation"],
        "outOfScope": ["Email templates"],
        "nonFunctional": [],
        "openQuestions": [
            {"id": "OQ-1", "text": "Who owns the queue?", "ownerRole": "Product Owner",
             "answer": None, "deferred": False, "deferredBy": None}],
        "acceptanceCriteria": [
            {"id": "AC-1", "given": "a premium case", "when": "the agent escalates it",
             "then": "the case moves to the premium queue", "examples": ["Case 1 moves"],
             "source": "stated"},
            {"id": "AC-2", "given": "a case with no priority", "when": "the agent escalates it",
             "then": "the agent sees an error", "examples": ["blank priority"],
             "source": "edge-case"}],
        "edgeCases": [
            {"id": "EC-1", "category": "blank", "component": "Case.Priority",
             "detail": "field is not required; value left blank",
             "evidence": "a.cls:3", "confidence": "Confirmed", "becameCriterion": "AC-2",
             "reason": None},
            {"id": "EC-2", "category": "bulk", "component": "Case",
             "detail": "a bulk change of 200 records or more",
             "evidence": None, "confidence": "Unverifiable", "becameCriterion": None,
             "reason": "bulk loads are out of scope"}],
        "droppedSeeds": [{"category": "record-type", "component": "Case",
                          "detail": "record type Case.Support", "reason": "one record type"}],
        "overlaps": [
            {"api": "Case", "type": "CustomObject", "kind": "watch",
             "stories": [{"storyId": "DEMO-202", "squad": "Service Ops", "status": "in-flight",
                          "changeType": "modify", "type": "CustomObject", "commit": "abc1234"}]}],
        "seeds": ["Case.Priority"],
    }


def confirmed():
    d = good()
    d["status"] = "confirmed"
    d["confirmedBy"] = "Product Owner"
    d["openQuestions"][0]["answer"] = "Support lead"
    return d


def has(errors, word):
    return any(word in e for e in errors)


def v(doc, stage="draft", **kw):
    return S.validate_story(doc, stage, REPO, **kw)


def mkroot(name):
    d = os.path.join(TMP, name)
    os.makedirs(d)
    return d


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="\n") as fh:
        fh.write(text)


def test_good_draft_is_valid():
    assert v(good()) == [], v(good())


def test_good_confirmed_is_valid():
    assert v(confirmed(), "confirmed") == [], v(confirmed(), "confirmed")


def test_unknown_key():
    d = good()
    d["foo"] = 1
    assert has(v(d), "foo")
    d = good()
    d["acceptanceCriteria"][0]["extra"] = 1
    assert has(v(d), "extra")


def test_trailing_newline_rejected():
    d = good()
    d["storyId"] = "DEMO-301\n"
    assert has(v(d), "storyId")
    d = good()
    d["slug"] = "abc\n"
    assert has(v(d), "slug")


def test_edge_case_criterion_links():
    d = good()
    d["edgeCases"][0]["becameCriterion"] = "AC-9"
    assert has(v(d), "AC-9")
    d = good()
    d["edgeCases"][1]["reason"] = None
    assert has(v(d), "reason is required")
    d = good()
    d["edgeCases"][0]["reason"] = "why"
    assert has(v(d), "reason is present")


def test_evidence_null_only_when_unverifiable():
    d = good()
    d["edgeCases"][1]["confidence"] = "Inferred"
    assert has(v(d), "evidence is null")
    d = good()
    d["edgeCases"][0]["category"] = "nonsense"
    assert has(v(d), "nonsense")


def test_confirmed_needs_resolved_questions():
    d = confirmed()
    d["openQuestions"][0]["answer"] = None
    assert has(v(d, "confirmed"), "not answered and not deferred")
    d["openQuestions"][0]["deferred"] = True
    d["openQuestions"][0]["deferredBy"] = "Product Owner"
    assert v(d, "confirmed") == []
    d = confirmed()
    del d["confirmedBy"]
    assert has(v(d, "confirmed"), "confirmedBy")


def test_deferred_by_rules():
    # Required and non-empty when deferred is true, in both stages.
    for stage, make in (("draft", good), ("confirmed", confirmed)):
        d = make()
        d["openQuestions"][0]["deferred"] = True
        assert has(v(d, stage), "deferredBy is required"), (stage, v(d, stage))
        d["openQuestions"][0]["deferredBy"] = "   "
        assert has(v(d, stage), "deferredBy is required"), stage
        d["openQuestions"][0]["deferredBy"] = 7
        assert has(v(d, stage), "deferredBy is required"), stage
        d["openQuestions"][0]["deferredBy"] = "Product Owner"
        assert v(d, stage) == [], (stage, v(d, stage))
    # Null otherwise.
    d = good()
    d["openQuestions"][0]["deferredBy"] = "Product Owner"
    assert has(v(d), "deferredBy is set but deferred is not true"), v(d)
    # The key is required, as every openQuestions key is.
    d = good()
    del d["openQuestions"][0]["deferredBy"]
    assert has(v(d), "missing key 'deferredBy'"), v(d)


def test_org_only_category_accepted():
    d = good()
    d["edgeCases"][1] = {"id": "EC-2", "category": "org-only", "component": "Case",
                         "detail": "sharing settings and real data volumes are org configuration, "
                                   "not in this repo",
                         "evidence": None, "confidence": "Unverifiable", "becameCriterion": None,
                         "reason": "sharing is org configuration"}
    assert v(d) == [], v(d)
    d["droppedSeeds"][0]["category"] = "org-only"
    assert v(d) == [], v(d)
    d["edgeCases"][1]["category"] = "org-config"
    assert has(v(d), "category 'org-config' is not one of"), v(d)


def test_ids_unique_and_gapless():
    d = good()
    d["acceptanceCriteria"][1]["id"] = "AC-3"
    assert has(v(d), "gaps")
    d = good()
    d["acceptanceCriteria"][1]["id"] = "AC-1"
    assert has(v(d), "duplicate id")


def test_seed_detail_required():
    for key in ("edgeCases", "droppedSeeds"):
        d = good()
        del d[key][0]["detail"]
        assert has(v(d), "missing key 'detail'"), (key, v(d))
        d = good()
        d[key][0]["detail"] = " "
        assert has(v(d), "detail is not a non-empty string"), (key, v(d))


def test_dropped_seed_needs_reason():
    d = good()
    d["droppedSeeds"][0]["reason"] = " "
    assert has(v(d), "reason")


def test_overlap_shape():
    d = good()
    d["overlaps"][0]["stories"][0]["bogus"] = 1
    assert has(v(d), "bogus")
    d = good()
    d["overlaps"][0]["kind"] = "clash"
    assert has(v(d), "kind")


def test_check_evidence_line_range():
    root = mkroot("ev")
    write(os.path.join(root, "a.cls"), "one\ntwo\nthree\n")
    d = good()
    assert S.validate_story(d, "draft", root, check_evidence=True) == []
    d["edgeCases"][0]["evidence"] = "a.cls:4"
    assert has(S.validate_story(d, "draft", root, check_evidence=True), "past the end")
    d["edgeCases"][0]["evidence"] = "missing.cls:1"
    assert has(S.validate_story(d, "draft", root, check_evidence=True), "does not exist")
    d["edgeCases"][0]["evidence"] = "../x:1"
    assert has(S.validate_story(d, "draft", root, check_evidence=True), "outside")


def test_nul_in_evidence_does_not_crash():
    d = good()
    d["edgeCases"][0]["evidence"] = "a\u0000b:3"
    errs = S.validate_story(d, "draft", REPO, check_evidence=True)
    assert has(errs, "evidence path unreadable"), errs


def test_squad_checked_against_list():
    root = mkroot("squads")
    write(os.path.join(root, "impacts", "squads.json"), json.dumps({"squads": ["Other"]}))
    assert has(S.validate_story(good(), "draft", root), "squads.json")


def run(args):
    return subprocess.run([sys.executable, CLI] + args, capture_output=True, text=True)


def test_cli_exit_codes():
    root = mkroot("cli")
    ok = os.path.join(root, "ok.json")
    bad = os.path.join(root, "bad.json")
    write(ok, json.dumps(good()))
    b = copy.deepcopy(good())
    b["foo"] = 1
    write(bad, json.dumps(b))
    assert run([ok, "--root", root]).returncode == 0
    assert run([bad, "--root", root]).returncode == 1
    assert run([]).returncode == 2
    assert run([ok, "--all"]).returncode == 2
    assert run([ok, "--stage", "nope"]).returncode == 2
    assert run(["--all", "--stage", "draft", "--root", root]).returncode == 2
    assert run(["--all", "--check-evidence", "--root", root]).returncode == 2


def test_all_checks_folder_and_empty():
    root = mkroot("all")
    assert run(["--all", "--root", root]).returncode == 0
    write(os.path.join(root, "impacts", "WRONG", "story.json"), json.dumps(confirmed()))
    p = run(["--all", "--root", root])
    assert p.returncode == 1 and "does not match storyId-slug" in p.stdout, p.stdout
    root2 = mkroot("all2")
    write(os.path.join(root2, "impacts", "DEMO-301-service-level-escalation", "story.json"),
          json.dumps(confirmed()))
    assert run(["--all", "--root", root2]).returncode == 0


def test_all_runs_check_ac_on_confirmed():
    root = mkroot("all_ac")
    vague = confirmed()
    vague["acceptanceCriteria"][0]["then"] = "the case moves quickly to the premium queue"
    path = os.path.join(root, "impacts", "DEMO-301-service-level-escalation", "story.json")
    write(path, json.dumps(vague))
    assert S.validate_story(vague, "confirmed", root) == []  # schema-valid; only the criteria fail
    p = run(["--all", "--root", root])
    assert p.returncode == 1, p.stdout
    errs = json.loads(p.stdout)["results"][0]["errors"]
    assert errs == ["acceptance criterion AC-1: vague-word: then contains 'quickly'"], errs
    none = confirmed()
    none["acceptanceCriteria"] = []
    none["edgeCases"][0]["becameCriterion"] = None
    none["edgeCases"][0]["reason"] = "no criterion"
    write(path, json.dumps(none))
    p = run(["--all", "--root", root])
    errs = json.loads(p.stdout)["results"][0]["errors"]
    assert p.returncode == 1 and any("no-criteria" in e for e in errs), p.stdout


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
