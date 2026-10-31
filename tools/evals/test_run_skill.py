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
DEMO_FIELD = "demo/org/force-app/main/default/objects/Case/fields/Escalation_Level__c.field-meta.xml"
VR_DETAIL = "validation rule Case.Escalation_Needs_Level (active)"
TRIGGER_DETAIL = "trigger CaseTrigger (status not in index)"
FIELD_DETAIL = "field is not required; value left blank"

# A synthetic index for the seed recompute: tests never read <checkout>/index, whose content
# depends on whatever built it last. Evidence paths point at real demo files under the checkout.
_DIRS = []


def make_index():
    nodes = {"Case": {"type": "CustomObject", "path": None},
             "Case.Escalation_Needs_Level": {"type": "ValidationRule", "active": True, "path": DEMO_VR},
             "CaseTrigger": {"type": "ApexTrigger", "path": DEMO_TRIGGER},
             "Case.Escalation_Level__c": {"type": "CustomField", "fieldType": "Picklist",
                                          "required": False, "path": DEMO_FIELD}}
    edges = [{"from": "Case.Escalation_Needs_Level", "to": "Case", "kind": "validationRuleOf",
              "evidence": DEMO_VR + ":2"},
             {"from": "CaseTrigger", "to": "Case", "kind": "triggerOn", "evidence": DEMO_TRIGGER + ":1"},
             {"from": "Case.Escalation_Level__c", "to": "Case", "kind": "fieldOf"}]
    d = tempfile.mkdtemp(prefix="run_skill_index_")
    _DIRS.append(d)
    with open(os.path.join(d, "metadata.json"), "w", encoding="utf-8") as fh:
        json.dump({"nodes": nodes, "edges": edges, "stamp": {"commit": "x"}}, fh)
    return d


INDEX = make_index()


def scan_for(apis):
    """What query.py edge-seeds prints for apis over the synthetic index."""
    return run_skill.query.edge_seeds(run_skill.query.load(INDEX), apis, run_skill.ROOT)


def chk(text, asserts, out=None):
    return run_skill.check(text, asserts, out, INDEX)


FULL = scan_for(["Case"])["seeds"]
FIELD_SEEDS = scan_for(["Case.Escalation_Level__c"])["seeds"]
FIELD_EV = [s for s in FIELD_SEEDS if s["category"] == "blank"][0]["evidence"]


def ec(detail=VR_DETAIL, evidence=DEMO_VR + ":2", ident="EC-1", category="automation",
       component="Case", criterion="AC-1", reason=None, confidence="Confirmed"):
    return {"id": ident, "category": category, "component": component, "detail": detail,
            "evidence": evidence, "confidence": confidence, "becameCriterion": criterion,
            "reason": reason}


def seed(detail=VR_DETAIL, evidence=DEMO_VR + ":2", category="automation", component="Case"):
    return {"category": category, "component": component, "detail": detail,
            "evidence": evidence, "confidence": "Confirmed"}


def story(edge_cases=None, seeds=("Case",)):
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
            "edgeCases": edge_cases, "droppedSeeds": [], "overlaps": [], "seeds": list(seeds)}


def drop_rest(doc, seeds):
    """Drop every seed that is not an edge case, so seeds_accounted holds."""
    kept = {(c["component"], c["category"], c["detail"]) for c in doc["edgeCases"]}
    doc["droppedSeeds"] = [{"category": s["category"], "component": s["component"],
                            "detail": s["detail"], "reason": "not met by this story"}
                           for s in seeds if (s["component"], s["category"], s["detail"]) not in kept]
    return doc


def story_dir(doc=None, seeds=None, unresolved=None):
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
            json.dump({"seeds": seeds, "unresolved": unresolved or []}, fh)
    return tmp, out


def test_synthetic_index_scan():
    """The fixture scan is the real edge_seeds output, org-only seed included."""
    cats = sorted((s["category"], s["detail"]) for s in FULL)
    assert ("automation", VR_DETAIL) in cats and ("automation", TRIGGER_DETAIL) in cats, cats
    assert [s for s in FULL if s["category"] == "org-only" and s["confidence"] == "Unverifiable"
            and s["evidence"] is None], FULL
    assert FIELD_EV == DEMO_FIELD + ":7", FIELD_EV


def test_story_json_valid_assertion():
    asserts = {"story_json_valid": True}
    tmp, out = story_dir()
    try:
        fails = chk("x", asserts, out)
        assert fails and "unreadable" in fails[0], fails
        assert chk("x", asserts) != []
    finally:
        shutil.rmtree(tmp)
    tmp, out = story_dir(story())
    try:
        assert chk("x", asserts, out) == []
    finally:
        shutil.rmtree(tmp)
    bad = story()
    bad["edgeCases"][0]["evidence"] = DEMO_VR + ":99999"
    tmp, out = story_dir(bad)
    try:
        fails = chk("x", asserts, out)
        assert fails and "past the end" in fails[0], fails
    finally:
        shutil.rmtree(tmp)
    vague = story()
    vague["acceptanceCriteria"][0]["then"] = "the save fails quickly"
    tmp, out = story_dir(vague)
    try:
        fails = chk("x", asserts, out)
        assert fails and any("vague-word" in f for f in fails), fails
    finally:
        shutil.rmtree(tmp)


def test_must_keep_edge_assertion():
    asserts = {"must_keep_edge": ["Escalation_Needs_Level"]}
    tmp, out = story_dir(story(), FULL)
    try:
        assert chk("x", asserts, out) == []
        assert chk("x", {"must_keep_edge": ["Case"]}, out) == []
        fails = chk("x", {"must_keep_edge": ["Escalation_Needs"]}, out)
        assert fails == ["edge case not kept for Escalation_Needs"], fails
        fails = chk("x", {"must_keep_edge": ["Cas"]}, out)
        assert fails == ["edge case not kept for Cas"], fails
    finally:
        shutil.rmtree(tmp)
    # The rule's file as evidence does not count: only component or a whole word of detail.
    trigger = story([ec(detail=TRIGGER_DETAIL, evidence=DEMO_TRIGGER + ":1")])
    tmp, out = story_dir(trigger, FULL)
    try:
        fails = chk("x", asserts, out)
        assert fails == ["edge case not kept for Escalation_Needs_Level"], fails
    finally:
        shutil.rmtree(tmp)
    field = story([ec(category="blank", component="Case.Escalation_Level__c", detail=FIELD_DETAIL,
                      evidence=FIELD_EV)], seeds=["Case.Escalation_Level__c"])
    tmp, out = story_dir(field, FIELD_SEEDS)
    try:
        assert chk("x", {"must_keep_edge": ["Case.Escalation_Level__c"]}, out) == []
        assert chk("x", {"must_keep_edge": ["Escalation_Level__c"]}, out) != []
    finally:
        shutil.rmtree(tmp)
    # Missing story.json or missing scan/edge-seeds.json fails.
    tmp, out = story_dir(None, FULL)
    try:
        fails = chk("x", asserts, out)
        assert fails and "story.json unreadable" in fails[0], fails
    finally:
        shutil.rmtree(tmp)
    tmp, out = story_dir(story())
    try:
        fails = chk("x", asserts, out)
        assert fails and "edge-seeds.json unreadable" in fails[0], fails
    finally:
        shutil.rmtree(tmp)


def test_must_become_criterion_assertion():
    asserts = {"must_become_criterion": ["Escalation_Needs_Level"]}
    tmp, out = story_dir(story(), FULL)
    try:
        assert chk("x", asserts, out) == []
    finally:
        shutil.rmtree(tmp)
    kept_only = story([ec(criterion=None, reason="kept, no criterion")])
    tmp, out = story_dir(kept_only, FULL)
    try:
        assert chk("x", {"must_keep_edge": ["Escalation_Needs_Level"]}, out) == []
        fails = chk("x", asserts, out)
        assert fails == ["no edge case for Escalation_Needs_Level became a criterion"], fails
    finally:
        shutil.rmtree(tmp)
    # A criterion on another edge case does not count for this name.
    other = story([ec(criterion=None, reason="kept, no criterion"),
                   ec(ident="EC-2", detail=TRIGGER_DETAIL, evidence=DEMO_TRIGGER + ":1")])
    tmp, out = story_dir(other, FULL)
    try:
        fails = chk("x", asserts, out)
        assert fails == ["no edge case for Escalation_Needs_Level became a criterion"], fails
    finally:
        shutil.rmtree(tmp)
    tmp, out = story_dir(story())
    try:
        fails = chk("x", asserts, out)
        assert fails and "edge-seeds.json unreadable" in fails[0], fails
    finally:
        shutil.rmtree(tmp)


def test_invented_edge_fails_must_keep_edge():
    """Review fix 1: an edge case named after the rule, with the real seed dropped, is not kept."""
    invented = story([ec(component="Escalation_Needs_Level", detail="invented")])
    invented["droppedSeeds"] = [{"category": "automation", "component": "Case", "detail": VR_DETAIL,
                                 "reason": "x"}]
    tmp, out = story_dir(invented, FULL)
    try:
        fails = chk("x", {"must_keep_edge": ["Escalation_Needs_Level"]}, out)
        assert fails == ["edge case not kept for Escalation_Needs_Level"], fails
        # The case-002 assertion set, now with edges_from_seeds_only, fails as a whole.
        case = {"story_json_valid": True, "must_keep_edge": ["Escalation_Needs_Level"],
                "seeds_accounted": True, "edges_from_seeds_only": True}
        fails = chk("x", case, out)
        assert "edge case not kept for Escalation_Needs_Level" in fails, fails
        assert any("is not in scan/edge-seeds.json" in f for f in fails), fails
    finally:
        shutil.rmtree(tmp)


def test_real_triple_with_other_evidence_fails():
    """Review fix 3: evidence and confidence are copied from the seed unchanged."""
    asserts = {"edges_from_seeds_only": True}
    forged = story([ec(evidence=DEMO_TRIGGER + ":1")])
    tmp, out = story_dir(forged, FULL)
    try:
        fails = chk("x", asserts, out)
        assert len(fails) == 1 and "differ from the seed's" in fails[0], fails
    finally:
        shutil.rmtree(tmp)
    relabelled = story([ec(confidence="Inferred")])
    tmp, out = story_dir(relabelled, FULL)
    try:
        fails = chk("x", asserts, out)
        assert len(fails) == 1 and "differ from the seed's" in fails[0], fails
    finally:
        shutil.rmtree(tmp)
    spaced = story([ec(detail=VR_DETAIL + " ")])
    tmp, out = story_dir(spaced, FULL)
    try:
        fails = chk("x", asserts, out)
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
    tmp, out = story_dir(story(), FULL)
    try:
        assert chk("x", asserts, out) == []
    finally:
        shutil.rmtree(tmp)
    invented = story()
    invented["edgeCases"].append(ec(ident="EC-2", category="record-type", detail="record type Case.Nope",
                                    criterion=None, reason="one record type"))
    tmp, out = story_dir(invented, FULL)
    try:
        fails = chk("x", asserts, out)
        assert fails == ["edge case EC-2 (Case, record-type, record type Case.Nope) "
                         "is not in scan/edge-seeds.json"], fails
    finally:
        shutil.rmtree(tmp)
    # Same component and category as a real seed, but a detail the scan never emitted.
    reworded = story([ec(detail="validation rule Case.Something_Else (active)")])
    tmp, out = story_dir(reworded, FULL)
    try:
        fails = chk("x", asserts, out)
        assert len(fails) == 1 and "Something_Else" in fails[0], fails
    finally:
        shutil.rmtree(tmp)
    tmp, out = story_dir(story())
    try:
        fails = chk("x", asserts, out)
        assert fails and "edge-seeds.json unreadable" in fails[0], fails
    finally:
        shutil.rmtree(tmp)
    assert chk("x", asserts) != []


def test_seeds_accounted_assertion():
    asserts = {"seeds_accounted": True}
    tmp, out = story_dir(story(), FULL)
    try:
        fails = chk("x", asserts, out)
        want = sorted("seed (%s, %s, %s) is neither an edge case nor a dropped seed"
                      % (s["component"], s["category"], s["detail"])
                      for s in FULL if s["detail"] != VR_DETAIL)
        assert sorted(fails) == want, fails
        assert any("org-only" in f for f in fails) and any(TRIGGER_DETAIL in f for f in fails), fails
    finally:
        shutil.rmtree(tmp)
    accounted = drop_rest(story(), FULL)
    tmp, out = story_dir(accounted, FULL)
    try:
        assert chk("x", asserts, out) == []
    finally:
        shutil.rmtree(tmp)
    as_edge = drop_rest(story([ec(), ec(ident="EC-2", detail=TRIGGER_DETAIL, evidence=DEMO_TRIGGER + ":1",
                                        criterion=None, reason="kept, no criterion")]), FULL)
    tmp, out = story_dir(as_edge, FULL)
    try:
        assert chk("x", asserts, out) == []
    finally:
        shutil.rmtree(tmp)
    tmp, out = story_dir(story())
    try:
        fails = chk("x", asserts, out)
        assert fails and "edge-seeds.json unreadable" in fails[0], fails
    finally:
        shutil.rmtree(tmp)
    tmp, out = story_dir(None, FULL)
    try:
        fails = chk("x", asserts, out)
        assert fails and "story.json unreadable" in fails[0], fails
    finally:
        shutil.rmtree(tmp)


SEED_ASSERTS = {"must_keep_edge": ["Escalation_Needs_Level"], "seeds_accounted": True,
                "edges_from_seeds_only": True}


def test_omitted_seed_fails_recompute():
    """I4: the skill drops a seed from its saved scan and from the story; the recompute catches it."""
    omitted = [s for s in FULL if s["category"] != "org-only"]
    doc = drop_rest(story(), omitted)
    tmp, out = story_dir(doc, omitted)
    try:
        fails = chk("x", SEED_ASSERTS, out)
        assert fails and fails[0].startswith("scan/edge-seeds.json differs from query.py edge-seeds"), fails
        assert any("omitted seed" in f and "org-only" in f for f in fails), fails
        # Reported once, not once per seed-reading assertion.
        assert sum(1 for f in fails if f.startswith("scan/edge-seeds.json differs")) == 1, fails
    finally:
        shutil.rmtree(tmp)
    # An empty saved scan is the extreme case: every seed omitted.
    tmp, out = story_dir(story(), [])
    try:
        fails = chk("x", {"seeds_accounted": True}, out)
        assert fails and "differs" in fails[0], fails
    finally:
        shutil.rmtree(tmp)


def test_invented_seed_fails_recompute():
    """I4: the skill adds a seed to its saved scan, then keeps it as an edge case."""
    fake = seed(category="record-type", detail="record type Case.Invented", evidence=DEMO_VR + ":1")
    doc = drop_rest(story([ec(), ec(ident="EC-2", category="record-type", detail="record type Case.Invented",
                                    evidence=DEMO_VR + ":1", criterion=None, reason="x")]), FULL)
    tmp, out = story_dir(doc, FULL + [fake])
    try:
        fails = chk("x", SEED_ASSERTS, out)
        assert fails and "differs" in fails[0], fails
        assert any("seed not in the recomputed scan" in f and "Case.Invented" in f for f in fails), fails
    finally:
        shutil.rmtree(tmp)
    tmp, out = story_dir(drop_rest(story(), FULL), FULL, unresolved=["Made_Up__c"])
    try:
        fails = chk("x", SEED_ASSERTS, out)
        assert any("unresolved differs" in f for f in fails), fails
    finally:
        shutil.rmtree(tmp)


def test_recompute_ignores_order():
    doc = drop_rest(story(), FULL)
    tmp, out = story_dir(doc, list(reversed(FULL)))
    try:
        assert chk("x", SEED_ASSERTS, out) == []
    finally:
        shutil.rmtree(tmp)


def test_missing_index_fails_cleanly():
    doc = drop_rest(story(), FULL)
    tmp, out = story_dir(doc, FULL)
    try:
        fails = run_skill.check("x", {"seeds_accounted": True}, out, os.path.join(tmp, "no-index"))
        assert len(fails) == 1 and fails[0].startswith("cannot recompute edge seeds from index"), fails
    finally:
        shutil.rmtree(tmp)


def design(recommend="OPT-2", trigger_change="modify"):
    """A draft design.json over the synthetic index: OPT-1 do nothing, OPT-2 reuses CaseTrigger."""
    trig = {"api": "CaseTrigger", "type": "ApexTrigger", "changeType": trigger_change,
            "evidence": DEMO_TRIGGER + ":1", "confidence": "Confirmed"}
    if trigger_change == "new":
        trig["evidence"] = None
    return {"schemaVersion": 1, "storyId": "DEMO-1", "slug": "x", "status": "draft",
            "options": [
                {"id": "OPT-1", "title": "Do nothing", "summary": "s", "doNothing": True,
                 "components": [], "tradeOffs": [{"criterion": "reuse", "note": "n"}],
                 "impactSummary": "none"},
                {"id": "OPT-2", "title": "Extend", "summary": "s", "doNothing": False,
                 "components": [trig,
                                {"api": "Case.New_Field__c", "type": "CustomField", "changeType": "new",
                                 "evidence": None, "confidence": "Inferred"}],
                 "tradeOffs": [{"criterion": "maintainability", "note": "n"}],
                 "impactSummary": "one trigger"}],
            "recommendation": {"optionId": recommend, "reasons": ["r"]},
            "provenance": {"indexStamp": {"commit": "x"}, "frameworkVersion": "0.1.0",
                           "model": "m", "assistantVersion": "unknown", "sourceRoot": "demo/org"}}


def design_dir(doc):
    tmp = tempfile.mkdtemp(prefix="run_skill_design_")
    out = os.path.join(tmp, "design.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("x\n")
    if doc is not None:
        with open(os.path.join(tmp, "design.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
    return tmp, out


def test_design_json_valid_assertion():
    asserts = {"design_json_valid": True}
    tmp, out = design_dir(design())
    try:
        assert chk("x", asserts, out) == [], chk("x", asserts, out)
    finally:
        shutil.rmtree(tmp)
    ghost = design()
    ghost["options"][1]["components"][0]["api"] = "GhostTrigger"
    tmp, out = design_dir(ghost)
    try:
        fails = chk("x", asserts, out)
        assert fails and "GhostTrigger" in fails[0] and "index" in fails[0], fails
    finally:
        shutil.rmtree(tmp)
    bad_ev = design()
    bad_ev["options"][1]["components"][0]["evidence"] = DEMO_TRIGGER + ":99999"
    tmp, out = design_dir(bad_ev)
    try:
        fails = chk("x", asserts, out)
        assert fails and "past the end" in fails[0], fails
    finally:
        shutil.rmtree(tmp)
    tmp, out = design_dir(None)
    try:
        fails = chk("x", asserts, out)
        assert fails and "unreadable" in fails[0], fails
        fails = run_skill.check("x", asserts, out, os.path.join(tmp, "no-index"))
        assert any("design.json" in f for f in fails), fails
    finally:
        shutil.rmtree(tmp)
    tmp, out = design_dir(design())
    try:
        fails = run_skill.check("x", asserts, out, os.path.join(tmp, "no-index"))
        assert len(fails) == 1 and fails[0].startswith("cannot load index"), fails
    finally:
        shutil.rmtree(tmp)


def test_recommends_assertion():
    tmp, out = design_dir(design())
    try:
        assert chk("x", {"recommends": "change"}, out) == []
        fails = chk("x", {"recommends": "do-nothing"}, out)
        assert fails == ["recommends: expected do-nothing, design recommends OPT-2 (a change option)"], fails
    finally:
        shutil.rmtree(tmp)
    tmp, out = design_dir(design(recommend="OPT-1"))
    try:
        assert chk("x", {"recommends": "do-nothing"}, out) == []
        fails = chk("x", {"recommends": "change"}, out)
        assert fails == ["recommends: expected change, design recommends OPT-1 (the do-nothing option)"], fails
    finally:
        shutil.rmtree(tmp)
    tmp, out = design_dir(design(recommend="OPT-9"))
    try:
        fails = chk("x", {"recommends": "change"}, out)
        assert fails and "OPT-9" in fails[0], fails
    finally:
        shutil.rmtree(tmp)


def test_must_reuse_assertion():
    tmp, out = design_dir(design())
    try:
        assert chk("x", {"must_reuse": ["CaseTrigger"]}, out) == []
        fails = chk("x", {"must_reuse": ["CaseTrigger", "CaseTriggerHandler"]}, out)
        assert fails == ["must_reuse: recommended option OPT-2 does not reuse CaseTriggerHandler"], fails
        fails = chk("x", {"must_reuse": ["Case.New_Field__c"]}, out)
        assert fails == ["must_reuse: recommended option OPT-2 does not reuse Case.New_Field__c"], fails
    finally:
        shutil.rmtree(tmp)
    tmp, out = design_dir(design(recommend="OPT-1"))
    try:
        fails = chk("x", {"must_reuse": ["CaseTrigger"]}, out)
        assert fails == ["must_reuse: recommended option OPT-1 does not reuse CaseTrigger"], fails
    finally:
        shutil.rmtree(tmp)


def _reuse_fails_for(change):
    tmp, out = design_dir(design(trigger_change=change))
    try:
        return chk("x", {"must_reuse": ["CaseTrigger"]}, out)
    finally:
        shutil.rmtree(tmp)


def test_delete_is_not_reuse():
    fails = _reuse_fails_for("delete")
    assert fails == ["must_reuse: recommended option OPT-2 does not reuse CaseTrigger"], fails


def test_review_is_not_reuse():
    fails = _reuse_fails_for("review")
    assert fails == ["must_reuse: recommended option OPT-2 does not reuse CaseTrigger"], fails
    assert _reuse_fails_for("modify") == []


def _label_fails(md_text, doc=None):
    tmp, out = design_dir(doc or design())
    try:
        return run_skill.check(md_text, {"must_label_every_claim": True}, out)
    finally:
        shutil.rmtree(tmp)


def test_design_md_every_component_labelled():
    sys.path.insert(0, os.path.join(run_skill.ROOT, "tools", "designs"))
    from design_md import render_md
    md = render_md(design())
    assert _label_fails(md) == [], _label_fails(md)
    # A label removed from a row: the generic check and the design check both report it.
    trig_row = [l for l in md.splitlines() if l.startswith("| `CaseTrigger`")][0]
    fails = _label_fails(md.replace(trig_row, trig_row.replace("| Confirmed |", "| |")))
    assert fails == ["1 table row(s) without a confidence label",
                     "design.md: Components row for CaseTrigger under OPT-2 is labelled ''; "
                     "design.json says 'Confirmed'"], fails
    # A row dropped from the table: the generic check alone would pass on what is left.
    fails = _label_fails(md.replace(trig_row + "\n", ""))
    assert fails == ["design.md: no Components row for CaseTrigger under OPT-2"], fails
    # Every row dropped: never a vacuous pass.
    no_rows = "\n".join(l for l in md.splitlines() if not l.startswith("| `"))
    fails = _label_fails(no_rows)
    assert len(fails) == 2 and all("no Components row" in f for f in fails), fails
    # A wrong label (still one of the three) is caught against design.json.
    fails = _label_fails(md.replace(trig_row, trig_row.replace("| Confirmed |", "| Inferred |")))
    assert fails == ["design.md: Components row for CaseTrigger under OPT-2 is labelled 'Inferred'; "
                     "design.json says 'Confirmed'"], fails
    # An output that is not design.md (story-impact's impact.md beside a design.json) is unchanged.
    tmp, out = design_dir(design())
    try:
        impact_md = os.path.join(tmp, "impact.md")
        assert run_skill.check("no rows\n", {"must_label_every_claim": True}, impact_md) == []
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
    for d in _DIRS:
        shutil.rmtree(d, ignore_errors=True)
    print("%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
