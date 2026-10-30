#!/usr/bin/env python3
"""Tests for run_skill.py's check(). Plain script: python3 tools/evals/test_run_skill.py"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_skill  # noqa: E402

DEMO_CLS = "demo/org/force-app/main/default/classes/CaseEscalationService.cls"


def md_with_overlaps(rows, extra=""):
    lines = ["# Impact: DEMO-1 x", "",
             "| Component | Layer | Type | Ownership | Change | Impact | Scale | Hop | Evidence | Confidence |",
             "|---|---|---|---|---|---|---|---|---|---|",
             "| `CaseEscalationService` | Apex | ApexClass | Custom | modify | High | S | 0 | `%s:1` | Confirmed |"
             % DEMO_CLS, "", "## Overlaps with other stories", "",
             "| Component | Kind | Other story | Squad | Status | Their change | Register commit |",
             "|---|---|---|---|---|---|---|"]
    lines += ["| `%s` | watch | DEMO-202 | Service Ops | in-flight | modify | `abc1234` |" % r for r in rows]
    lines += ["", "## Unverifiable", "", "- none", extra]
    return "\n".join(lines) + "\n"


def draft(evidence):
    return {"schemaVersion": 1, "storyId": "DEMO-1", "slug": "x", "squad": "Customer Care",
            "status": "draft",
            "provenance": {"indexStamp": {"commit": "abc1234"}, "frameworkVersion": "0.1.0",
                           "model": "m", "assistantVersion": "unknown", "hops": 2},
            "components": [{"api": "CaseEscalationService", "type": "ApexClass",
                            "changeType": "modify", "impact": "High", "confidence": "Confirmed",
                            "hop": 0, "evidence": evidence, "path": DEMO_CLS}],
            "decisions": [], "unknowns": []}


def test_demo_evidence_checked():
    fails = run_skill.check("see `demo/org/missing.cls:1`", {})
    assert any("demo/org/missing.cls" in f for f in fails), fails
    assert run_skill.check("see `%s:1`" % DEMO_CLS, {}) == []


def test_impact_json_valid_assertion():
    tmp = tempfile.mkdtemp(prefix="run_skill_")
    try:
        out = os.path.join(tmp, "impact.md")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("x\n")
        asserts = {"impact_json_valid": True}
        fails = run_skill.check("x", asserts, out)
        assert fails and "unreadable" in fails[0], fails
        with open(os.path.join(tmp, "impact.json"), "w", encoding="utf-8") as fh:
            json.dump(draft(DEMO_CLS + ":1"), fh)
        assert run_skill.check("x", asserts, out) == []
        with open(os.path.join(tmp, "impact.json"), "w", encoding="utf-8") as fh:
            json.dump(draft(DEMO_CLS + ":99999"), fh)
        fails = run_skill.check("x", asserts, out)
        assert fails and "past the end" in fails[0], fails
        assert run_skill.check("x", asserts) != []
    finally:
        shutil.rmtree(tmp)


def test_must_flag_overlap_assertion():
    asserts = {"must_flag_overlap": ["CaseTrigger"]}
    assert run_skill.check(md_with_overlaps(["CaseTrigger"]), asserts) == []
    elsewhere = md_with_overlaps([], extra="| `CaseTrigger` | Confirmed |")
    fails = run_skill.check(elsewhere, asserts)
    assert fails == ["overlap not flagged for CaseTrigger"], fails


def test_must_flag_overlap_exact():
    fails = run_skill.check(md_with_overlaps(["CaseTriggerHandler"]),
                            {"must_flag_overlap": ["CaseTrigger"]})
    assert fails == ["overlap not flagged for CaseTrigger"], fails


def test_overlap_rows_need_no_label():
    md = md_with_overlaps(["CaseTrigger", "CaseTriggerHandler"])
    assert run_skill.check(md, {"must_label_every_claim": True}) == []
    unlabelled = md.replace("| Confirmed |", "| |")
    fails = run_skill.check(unlabelled, {"must_label_every_claim": True})
    assert fails == ["1 table row(s) without a confidence label"], fails


DEMO_VR = "demo/org/force-app/main/default/objects/Case/validationRules/Escalation_Needs_Level.validationRule-meta.xml"
DEMO_TRIGGER = "demo/org/force-app/main/default/triggers/CaseTrigger.trigger"
VR_DETAIL = "validation rule Case.Escalation_Needs_Level (active)"
TRIGGER_DETAIL = "trigger CaseTrigger (status not in index)"


def ec(detail=VR_DETAIL, evidence=DEMO_VR + ":2", ident="EC-1", category="automation",
       component="Case", criterion="AC-1", reason=None):
    return {"id": ident, "category": category, "component": component, "detail": detail,
            "evidence": evidence, "confidence": "Confirmed", "becameCriterion": criterion,
            "reason": reason}


def seed(detail=VR_DETAIL, evidence=DEMO_VR + ":2", category="automation", component="Case"):
    return {"category": category, "component": component, "detail": detail,
            "evidence": evidence, "confidence": "Confirmed"}


def story(edge_cases=None):
    if edge_cases is None:
        edge_cases = [ec()]
    return {"schemaVersion": 1, "storyId": "DEMO-1", "slug": "x", "status": "draft",
            "squad": "Customer Care", "persona": "a service agent", "goal": "escalate a case",
            "benefit": "premium customers are answered first", "inScope": [], "outOfScope": [],
            "nonFunctional": [], "openQuestions": [],
            "acceptanceCriteria": [{"id": "AC-1", "given": "a premium case with no level",
                                    "when": "the agent escalates it",
                                    "then": "the save fails with the level message",
                                    "examples": ["Case 1 fails"], "source": "edge-case"}],
            "edgeCases": edge_cases, "droppedSeeds": [], "overlaps": [], "seeds": ["Case"]}


def story_dir(doc=None, seeds=None):
    tmp = tempfile.mkdtemp(prefix="run_skill_story_")
    out = os.path.join(tmp, "story.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("x\n")
    if doc is not None:
        with open(os.path.join(tmp, "story.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
    if seeds is not None:
        os.makedirs(os.path.join(tmp, "scan"))
        with open(os.path.join(tmp, "scan", "edge-seeds.json"), "w", encoding="utf-8") as fh:
            json.dump({"seeds": seeds, "unresolved": []}, fh)
    return tmp, out


def test_story_json_valid_assertion():
    asserts = {"story_json_valid": True}
    tmp, out = story_dir()
    try:
        fails = run_skill.check("x", asserts, out)
        assert fails and "unreadable" in fails[0], fails
        assert run_skill.check("x", asserts) != []
    finally:
        shutil.rmtree(tmp)
    tmp, out = story_dir(story())
    try:
        assert run_skill.check("x", asserts, out) == []
    finally:
        shutil.rmtree(tmp)
    bad = story()
    bad["edgeCases"][0]["evidence"] = DEMO_VR + ":99999"
    tmp, out = story_dir(bad)
    try:
        fails = run_skill.check("x", asserts, out)
        assert fails and "past the end" in fails[0], fails
    finally:
        shutil.rmtree(tmp)
    vague = story()
    vague["acceptanceCriteria"][0]["then"] = "the save fails quickly"
    tmp, out = story_dir(vague)
    try:
        fails = run_skill.check("x", asserts, out)
        assert fails and any("vague-word" in f for f in fails), fails
    finally:
        shutil.rmtree(tmp)


FIELD_DETAIL = "field is not required; value left blank"
FIELD_EV = "demo/org/force-app/main/default/objects/Case/fields/Escalation_Level__c.field-meta.xml:7"
SEEDS = [seed(), seed(detail=TRIGGER_DETAIL, evidence=DEMO_TRIGGER + ":1"),
         seed(category="blank", component="Case.Escalation_Level__c", detail=FIELD_DETAIL,
              evidence=FIELD_EV)]


def test_must_keep_edge_assertion():
    asserts = {"must_keep_edge": ["Escalation_Needs_Level"]}
    tmp, out = story_dir(story(), SEEDS)
    try:
        assert run_skill.check("x", asserts, out) == []
        assert run_skill.check("x", {"must_keep_edge": ["Case"]}, out) == []
        fails = run_skill.check("x", {"must_keep_edge": ["Escalation_Needs"]}, out)
        assert fails == ["edge case not kept for Escalation_Needs"], fails
        fails = run_skill.check("x", {"must_keep_edge": ["Cas"]}, out)
        assert fails == ["edge case not kept for Cas"], fails
    finally:
        shutil.rmtree(tmp)
    # The rule's file as evidence does not count: only component or a whole word of detail.
    trigger = story([ec(detail=TRIGGER_DETAIL, evidence=DEMO_TRIGGER + ":1")])
    tmp, out = story_dir(trigger, SEEDS)
    try:
        fails = run_skill.check("x", asserts, out)
        assert fails == ["edge case not kept for Escalation_Needs_Level"], fails
    finally:
        shutil.rmtree(tmp)
    field = story([ec(category="blank", component="Case.Escalation_Level__c", detail=FIELD_DETAIL,
                      evidence=FIELD_EV)])
    tmp, out = story_dir(field, SEEDS)
    try:
        assert run_skill.check("x", {"must_keep_edge": ["Case.Escalation_Level__c"]}, out) == []
        assert run_skill.check("x", {"must_keep_edge": ["Escalation_Level__c"]}, out) != []
    finally:
        shutil.rmtree(tmp)
    # Missing story.json or missing scan/edge-seeds.json fails.
    tmp, out = story_dir(None, SEEDS)
    try:
        fails = run_skill.check("x", asserts, out)
        assert fails and "story.json unreadable" in fails[0], fails
    finally:
        shutil.rmtree(tmp)
    tmp, out = story_dir(story())
    try:
        fails = run_skill.check("x", asserts, out)
        assert fails and "edge-seeds.json unreadable" in fails[0], fails
    finally:
        shutil.rmtree(tmp)


def test_invented_edge_fails_must_keep_edge():
    """Review fix 1: an edge case named after the rule, with the real seed dropped, is not kept."""
    invented = story([ec(component="Escalation_Needs_Level", detail="invented")])
    invented["droppedSeeds"] = [{"category": "automation", "component": "Case", "detail": VR_DETAIL,
                                 "reason": "x"}]
    seeds = [seed()]
    tmp, out = story_dir(invented, seeds)
    try:
        fails = run_skill.check("x", {"must_keep_edge": ["Escalation_Needs_Level"]}, out)
        assert fails == ["edge case not kept for Escalation_Needs_Level"], fails
        # The case-002 assertion set, now with edges_from_seeds_only, fails as a whole.
        case = {"story_json_valid": True, "must_keep_edge": ["Escalation_Needs_Level"],
                "seeds_accounted": True, "edges_from_seeds_only": True}
        fails = run_skill.check("x", case, out)
        assert "edge case not kept for Escalation_Needs_Level" in fails, fails
        assert any("is not in scan/edge-seeds.json" in f for f in fails), fails
    finally:
        shutil.rmtree(tmp)


def test_real_triple_with_other_evidence_fails():
    """Review fix 3: evidence and confidence are copied from the seed unchanged."""
    asserts = {"edges_from_seeds_only": True}
    forged = story([ec(evidence=DEMO_TRIGGER + ":1")])
    tmp, out = story_dir(forged, [seed()])
    try:
        fails = run_skill.check("x", asserts, out)
        assert len(fails) == 1 and "differ from the seed's" in fails[0], fails
    finally:
        shutil.rmtree(tmp)
    relabelled = story()
    relabelled["edgeCases"][0]["confidence"] = "Inferred"
    tmp, out = story_dir(relabelled, [seed()])
    try:
        fails = run_skill.check("x", asserts, out)
        assert len(fails) == 1 and "differ from the seed's" in fails[0], fails
    finally:
        shutil.rmtree(tmp)
    spaced = story([ec(detail=VR_DETAIL + " ")])
    tmp, out = story_dir(spaced, [seed()])
    try:
        fails = run_skill.check("x", asserts, out)
        assert len(fails) == 1 and "is not in scan/edge-seeds.json" in fails[0], fails
    finally:
        shutil.rmtree(tmp)


def test_must_list_overlap_exact():
    asserts = {"must_list_overlap": ["CaseTrigger"]}
    assert run_skill.check(md_with_overlaps(["CaseTrigger"]), asserts) == []
    fails = run_skill.check(md_with_overlaps(["CaseTriggerHandler"]), asserts)
    assert fails == ["overlap not listed for CaseTrigger"], fails
    elsewhere = md_with_overlaps([], extra="| `CaseTrigger` | Confirmed |")
    fails = run_skill.check(elsewhere, asserts)
    assert fails == ["overlap not listed for CaseTrigger"], fails


def test_edges_from_seeds_only_assertion():
    asserts = {"edges_from_seeds_only": True}
    seeds = [seed(), seed(detail=TRIGGER_DETAIL, evidence=DEMO_TRIGGER + ":1")]
    tmp, out = story_dir(story(), seeds)
    try:
        assert run_skill.check("x", asserts, out) == []
    finally:
        shutil.rmtree(tmp)
    invented = story()
    invented["edgeCases"].append(ec(ident="EC-2", category="record-type", detail="record type Case.Nope",
                                    criterion=None, reason="one record type"))
    tmp, out = story_dir(invented, seeds)
    try:
        fails = run_skill.check("x", asserts, out)
        assert fails == ["edge case EC-2 (Case, record-type, record type Case.Nope) "
                         "is not in scan/edge-seeds.json"], fails
    finally:
        shutil.rmtree(tmp)
    # Same component and category as a real seed, but a detail the scan never emitted.
    reworded = story([ec(detail="validation rule Case.Something_Else (active)")])
    tmp, out = story_dir(reworded, seeds)
    try:
        fails = run_skill.check("x", asserts, out)
        assert len(fails) == 1 and "Something_Else" in fails[0], fails
    finally:
        shutil.rmtree(tmp)
    tmp, out = story_dir(story())
    try:
        fails = run_skill.check("x", asserts, out)
        assert fails and "edge-seeds.json unreadable" in fails[0], fails
    finally:
        shutil.rmtree(tmp)
    assert run_skill.check("x", asserts) != []


def test_seeds_accounted_assertion():
    asserts = {"seeds_accounted": True}
    seeds = [seed(), seed(detail=TRIGGER_DETAIL, evidence=DEMO_TRIGGER + ":1")]
    tmp, out = story_dir(story(), seeds)
    try:
        fails = run_skill.check("x", asserts, out)
        assert fails == ["seed (Case, automation, %s) is neither an edge case nor a dropped seed"
                         % TRIGGER_DETAIL], fails
    finally:
        shutil.rmtree(tmp)
    accounted = story()
    accounted["droppedSeeds"] = [{"category": "automation", "component": "Case",
                                  "detail": TRIGGER_DETAIL, "reason": "trigger unchanged"}]
    tmp, out = story_dir(accounted, seeds)
    try:
        assert run_skill.check("x", asserts, out) == []
    finally:
        shutil.rmtree(tmp)
    as_edge = story([ec(), ec(ident="EC-2", detail=TRIGGER_DETAIL, evidence=DEMO_TRIGGER + ":1",
                              criterion=None, reason="kept, no criterion")])
    tmp, out = story_dir(as_edge, seeds)
    try:
        assert run_skill.check("x", asserts, out) == []
    finally:
        shutil.rmtree(tmp)
    tmp, out = story_dir(story(), [])
    try:
        assert run_skill.check("x", asserts, out) == []
    finally:
        shutil.rmtree(tmp)
    tmp, out = story_dir(story())
    try:
        fails = run_skill.check("x", asserts, out)
        assert fails and "edge-seeds.json unreadable" in fails[0], fails
    finally:
        shutil.rmtree(tmp)
    tmp, out = story_dir(None, seeds)
    try:
        fails = run_skill.check("x", asserts, out)
        assert fails and "story.json unreadable" in fails[0], fails
    finally:
        shutil.rmtree(tmp)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print("PASS", t.__name__)
        except Exception as exc:
            failed += 1
            print("FAIL", t.__name__, "-", exc)
    print("%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
