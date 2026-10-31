#!/usr/bin/env python3
"""Tests for consistency.py. Plain script: python3 tools/evals/test_consistency.py

Fixtures are synthetic and built under a temp folder inside <checkout>/ai-context/, removed after.
"""
import copy
import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKOUT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import consistency  # noqa: E402

CLS = "demo/org/force-app/main/default/classes/CaseEscalationService.cls"


def impact():
    return {"schemaVersion": 1, "storyId": "DEMO-1", "slug": "x", "squad": "Customer Care",
            "status": "draft", "provenance": {"indexStamp": {"commit": "abc1234"}},
            "components": [
                {"api": "CaseEscalationService", "type": "ApexClass", "changeType": "modify",
                 "impact": "High", "confidence": "Confirmed", "hop": 0, "evidence": CLS + ":1", "path": CLS},
                {"api": "CaseTrigger", "type": "ApexTrigger", "changeType": "review",
                 "impact": "Medium", "confidence": "Inferred", "hop": 1, "evidence": "demo/x.trigger:3",
                 "path": "demo/x.trigger"},
                {"api": "Case.Tier__c", "type": "CustomField", "changeType": "new",
                 "impact": "Low", "confidence": "Confirmed", "hop": None, "evidence": None, "path": None}],
            "decisions": [{"ownerRole": "Product owner", "text": "Confirm the tier values."}],
            "unknowns": []}


def story():
    return {"storyId": "DEMO-2", "edgeCases": [
        {"id": "EC-1", "category": "blank", "component": "Account.Tier__c", "detail": "a blank tier",
         "evidence": None, "confidence": "Unverifiable", "becameCriterion": "AC-1", "reason": None},
        {"id": "EC-2", "category": "bulk", "component": "Account", "detail": "a bulk change",
         "evidence": None, "confidence": "Unverifiable", "becameCriterion": None, "reason": "covered"}],
        "acceptanceCriteria": [{"id": "AC-1", "then": "wording one"}],
        "overlaps": [{"api": "CaseTrigger", "type": "ApexTrigger", "kind": "watch", "stories": []}]}


def design(rec_id="OPT-2", order=("OPT-1", "OPT-2", "OPT-3")):
    opts = {
        "OPT-1": {"id": "OPT-1", "title": "Do nothing", "doNothing": True, "components": []},
        "OPT-2": {"id": "OPT-2", "title": "Reuse the service", "doNothing": False,
                  "components": [{"api": "CaseAssignmentService", "changeType": "modify"},
                                 {"api": "CaseTrigger", "changeType": "review"}]},
        "OPT-3": {"id": "OPT-3", "title": "New flow", "doNothing": False,
                  "components": [{"api": "Case_Round_Robin", "changeType": "new"}]},
    }
    return {"options": [opts[o] for o in order], "recommendation": {"optionId": rec_id, "reasons": ["r"]}}


def change(files=("force-app/a.cls",)):
    return {"storyId": "DEMO-3", "files": [{"path": f, "component": "A"} for f in files],
            "criteriaToTests": {"AC-1": ["force-app/a_Test.cls#t1"], "AC-2": ["force-app/a_Test.cls#t2"]},
            "done": [{"command": "python3 tools/x.py", "exit": 0}]}


class Tree:
    def __init__(self):
        self.base = tempfile.mkdtemp(prefix="consistency_", dir=os.path.join(CHECKOUT, "ai-context"))

    def run(self, i, name, doc):
        d = os.path.join(self.base, "run-%d" % i)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(doc, fh)
        return d

    def text(self, rel, body):
        p = os.path.join(self.base, rel)
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        return p

    def close(self):
        shutil.rmtree(self.base, ignore_errors=True)


def call(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = consistency.main(argv)
    return code, out.getvalue(), err.getvalue()


def as_json(stdout):
    """The JSON object at the start of stdout (--text appends the grid after it)."""
    obj, _ = json.JSONDecoder().raw_decode(stdout)
    return obj


def case_identical_runs_give_5_of_5():
    t = Tree()
    try:
        dirs = [t.run(i, "impact.json", impact()) for i in range(1, 6)]
        code, out, _ = call(dirs + ["--text"])
        assert code == 0, code
        r = as_json(out)
        assert r["kind"] == "impact" and r["runs"] == 5 and r["identical"] == 5, r
        assert all(f["agree"] for f in r["fields"].values()), r
        assert out.rstrip("\n").splitlines()[-1] == "5/5 identical", out
        assert "Disagreements" not in out, out
    finally:
        t.close()


def case_one_drifted_component_gives_4_of_5():
    t = Tree()
    try:
        dirs = [t.run(i, "impact.json", impact()) for i in range(1, 5)]
        drift = impact()
        drift["components"][1]["impact"] = "High"
        dirs.append(t.run(5, "impact.json", drift))
        code, out, _ = call(dirs + ["--text"])
        assert code == 0, code
        r = as_json(out)
        assert r["identical"] == 4, r
        f = r["fields"]
        assert f["components"]["agree"] and f["evidence"]["agree"] and f["decisions"]["agree"], f
        assert not f["componentRatings"]["agree"], f
        assert ["CaseTrigger", "High", "Inferred"] in f["componentRatings"]["values"][4], f
        assert ["CaseTrigger", "Medium", "Inferred"] in f["componentRatings"]["values"][0], f
        assert '["CaseTrigger","High","Inferred"]' in out.replace(" ", ""), out
        lines = out.rstrip("\n").splitlines()
        assert lines[-1] == "4/5 identical", lines[-1]
        row = [l for l in lines if l.startswith("componentRatings ")][0]
        assert row.split()[1:] == ["=", "=", "=", "=", "x", "no"], row
    finally:
        t.close()


def case_reordered_lists_stay_identical():
    t = Tree()
    try:
        a = impact()
        b = copy.deepcopy(a)
        b["components"].reverse()
        s1, s2 = story(), story()
        s2["edgeCases"].reverse()
        s2["acceptanceCriteria"][0]["then"] = "different wording"
        r1 = consistency.compare([t.run(1, "impact.json", a), t.run(2, "impact.json", b)])
        assert r1["identical"] == 2, r1
        r2 = consistency.compare([t.run(3, "story.json", s1), t.run(4, "story.json", s2)])
        assert r2["identical"] == 2, r2
    finally:
        t.close()


def case_story_kept_seed_difference_detected():
    t = Tree()
    try:
        drift = story()
        drift["edgeCases"] = drift["edgeCases"][:1]
        dirs = [t.run(1, "story.json", story()), t.run(2, "story.json", story()), t.run(3, "story.json", drift)]
        r = consistency.compare(dirs)
        assert r["kind"] == "story" and r["identical"] == 2, r
        assert not r["fields"]["keptEdgeSeeds"]["agree"] and r["fields"]["overlapApis"]["agree"], r
        assert ["Account", "bulk", "a bulk change"] not in r["fields"]["keptEdgeSeeds"]["values"][2], r
        over = story()
        over["overlaps"] = []
        r = consistency.compare([t.run(4, "story.json", story()), t.run(5, "story.json", over)])
        assert not r["fields"]["overlapApis"]["agree"], r
    finally:
        t.close()


def case_design_recommended_set_rule():
    t = Tree()
    try:
        same = design(order=("OPT-3", "OPT-1", "OPT-2"))  # same set, different id and order
        same["options"][2]["id"] = "OPT-9"
        same["options"][2]["title"] = "Other wording"
        same["recommendation"]["optionId"] = "OPT-9"
        r = consistency.compare([t.run(1, "design.json", design()), t.run(2, "design.json", same)])
        assert r["identical"] == 2, r
        assert r["fields"]["recommendedComponents"]["values"][0] == ["CaseAssignmentService", "CaseTrigger"], r
        other = design(rec_id="OPT-3")
        r = consistency.compare([t.run(3, "design.json", design()), t.run(4, "design.json", other)])
        assert not r["fields"]["recommendedComponents"]["agree"] and r["fields"]["doNothingPresent"]["agree"], r
        no_dn = design()
        no_dn["options"][0]["doNothing"] = False
        r = consistency.compare([t.run(5, "design.json", design()), t.run(6, "design.json", no_dn)])
        assert not r["fields"]["doNothingPresent"]["agree"], r
        assert r["fields"]["doNothingPresent"]["values"] == [True, False], r
    finally:
        t.close()


def case_change_files_come_from_diff_names():
    t = Tree()
    try:
        d1 = t.run(1, "change.json", change(("force-app/a.cls",)))
        d2 = t.run(2, "change.json", change(("force-app/a.cls",)))
        n1 = t.text("n1.txt", "force-app/a.cls\nforce-app/a_Test.cls\n")
        n2 = t.text("n2.txt", "force-app/a.cls\nforce-app/b.cls\n")
        code, out, _ = call([d1, d2, "--diff-names", n1, n2])
        assert code == 0, code
        r = as_json(out)
        assert r["kind"] == "change" and not r["fields"]["filesTouched"]["agree"], r
        assert r["fields"]["filesTouched"]["values"][1] == ["force-app/a.cls", "force-app/b.cls"], r
        # different change.json files, same diff names (blank lines, backslashes, repeats): agree
        d3 = t.run(3, "change.json", change(("force-app/a.cls",)))
        d4 = t.run(4, "change.json", change(("force-app/z.cls", "force-app/y.cls")))
        n3 = t.text("n3.txt", "force-app/a.cls\n\nforce-app/a_Test.cls\n")
        n4 = t.text("n4.txt", "force-app\\a_Test.cls\r\nforce-app/a.cls\nforce-app/a.cls\n")
        code, out, _ = call([d3, d4, "--diff-names", n3, "--diff-names", n4])
        r = as_json(out)
        assert code == 0 and r["fields"]["filesTouched"]["agree"] and r["identical"] == 2, r
    finally:
        t.close()


def case_change_checks_and_criteria_map():
    t = Tree()
    try:
        failed = change()
        failed["done"][0]["exit"] = 1
        remap = change()
        remap["criteriaToTests"]["AC-2"] = ["force-app/a_Test.cls#t3"]
        dirs = [t.run(1, "change.json", change()), t.run(2, "change.json", failed),
                t.run(3, "change.json", remap)]
        names = [t.text("n%d.txt" % i, "force-app/a.cls\n") for i in range(1, 4)]
        r = consistency.compare(dirs, names)
        assert r["fields"]["checksPass"]["values"] == [True, False, True], r
        assert not r["fields"]["criteriaToTests"]["agree"] and r["identical"] == 1, r
    finally:
        t.close()


def case_bad_usage_and_mixed_kinds_exit_2():
    t = Tree()
    try:
        a = t.run(1, "impact.json", impact())
        b = t.run(2, "story.json", story())
        code, out, err = call([a, b])
        assert code == 2 and out == "" and "mixed kinds" in err, (code, err)
        c = t.run(3, "change.json", change())
        n = t.text("n.txt", "x\n")
        assert call([c])[0] == 2  # change without --diff-names
        assert call([a, "--diff-names", n])[0] == 2  # diff names on a non-change kind
        empty = os.path.join(t.base, "empty")
        os.makedirs(empty)
        assert call([empty])[0] == 2  # no folder sets the kind
        assert call([empty, os.path.join(t.base, "empty")])[0] == 2
        both = t.run(4, "impact.json", impact())
        t.run(4, "story.json", story())
        assert call([both])[0] == 2
        assert call([])[0] == 2
        assert call([os.path.join(t.base, "missing")])[0] == 2
        bad = t.run(5, "impact.json", impact())
        t.text("run-5/impact.json", "{not json")
        code, _, err = call([bad])
        assert code == 2 and "Traceback" not in err, err
    finally:
        t.close()


def case_malformed_record_is_drift_not_error():
    t = Tree()
    try:
        broken = impact()
        broken["components"] = "oops"
        code, out, _ = call([t.run(1, "impact.json", impact()), t.run(2, "impact.json", broken)])
        r = as_json(out)
        assert code == 0 and r["fields"]["components"]["values"][1] is None and r["identical"] == 1, r
    finally:
        t.close()


def case_run_without_output_is_drift():
    t = Tree()
    try:
        dirs = [t.run(i, "impact.json", impact()) for i in range(1, 5)]
        missing = os.path.join(t.base, "run-5")
        os.makedirs(missing)
        t.text("run-5/run.json", "{}")
        code, out, _ = call(dirs + [missing, "--text"])
        r = as_json(out)
        assert code == 0 and r["identical"] == 4, r
        assert all(f["values"][4] is None for f in r["fields"].values()), r
        assert out.rstrip("\n").splitlines()[-1] == "4/5 identical", out
    finally:
        t.close()


def case_output_is_byte_identical():
    t = Tree()
    try:
        dirs = [t.run(i, "impact.json", impact()) for i in range(1, 4)]
        first = call(dirs + ["--text"])
        second = call(dirs + ["--text"])
        assert first == second, "outputs differ"
    finally:
        t.close()


def main():
    failures = passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("case_") and callable(fn):
            try:
                fn()
                passed += 1
                print("PASS %s" % name)
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print("FAIL %s: %r" % (name, exc))
    print("%d passed, %d failed" % (passed, failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
