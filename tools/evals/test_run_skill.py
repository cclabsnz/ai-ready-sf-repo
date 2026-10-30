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
