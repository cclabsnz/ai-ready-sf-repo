#!/usr/bin/env python3
"""Tests for check_answers.py. The index is built into a temp dir; demo/ is only read.

Run: python3 tools/demo/test_check_answers.py
"""
import atexit
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CHECK = os.path.join(HERE, "check_answers.py")
BUILD = os.path.join(REPO, "tools", "index", "build_index.py")
KEYS = sorted(glob.glob(os.path.join(REPO, "demo", "stories", "*.answer.json")))

TMP = tempfile.mkdtemp(prefix="check_answers_")
atexit.register(shutil.rmtree, TMP, True)
INDEX = os.path.join(TMP, "index")


def build():
    subprocess.run([sys.executable, BUILD, "--root", os.path.join(REPO, "demo", "org"), "--out", INDEX],
                   check=True, capture_output=True)


def run(keys):
    p = subprocess.run([sys.executable, CHECK, "--index", INDEX] + keys, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def load(story):
    with open(os.path.join(REPO, "demo", "stories", story + ".answer.json")) as fh:
        return json.load(fh)


def write_key(name, key):
    path = os.path.join(TMP, name)
    with open(path, "w") as fh:
        json.dump(key, fh)
    return path


def case_keys_match_index():
    assert len(KEYS) == 3, KEYS
    code, out = run(KEYS)
    assert code == 0, out
    assert out.count("[PASS]") == 3 and "[FAIL]" not in out, out


def case_missing_component_detected():
    key = load("DEMO-201")
    key["components"] = [c for c in key["components"] if c["api"] != "EscalationNotifier"]
    code, out = run([write_key("missing.json", key)])
    assert code == 1, out
    assert "[FAIL]" in out and "extra in index, not in key: EscalationNotifier" in out, out


def case_extra_component_detected():
    key = load("DEMO-202")
    key["components"].append({"api": "NoSuchClass", "type": "ApexClass", "changeType": "modify",
                              "hop": 1, "why": "does not exist"})
    code, out = run([write_key("extra.json", key)])
    assert code == 1, out
    assert "missing from index: NoSuchClass" in out, out


def case_wrong_hop_detected():
    key = load("DEMO-201")
    for c in key["components"]:
        if c["api"] == "Case_Escalate_Premium":
            c["hop"] = 3
    code, out = run([write_key("hop.json", key)])
    assert code == 1 and "wrong hop: Case_Escalate_Premium" in out, out


def _comp(key, api):
    return next(c for c in key["components"] if c["api"] == api)


def _judgement(api, evidence, **kw):
    c = {"api": api, "type": "ApexClass", "changeType": "review", "hop": None, "source": "judgement",
         "evidence": evidence, "why": "weigh this"}
    c.update(kw)
    return c


def case_type_mismatch_detected():
    key = load("DEMO-202")
    _comp(key, "CaseTriggerHandler")["type"] = "Flow"
    code, out = run([write_key("type.json", key)])
    assert code == 1 and "wrong type: CaseTriggerHandler" in out, out


def case_new_component_already_in_index_detected():
    key = load("DEMO-101")
    _comp(key, "Account.Customer_Tier__c")["api"] = "Case.Escalation_Level__c"
    code, out = run([write_key("newexists.json", key)])
    assert code == 1 and "new component already exists in the index: Case.Escalation_Level__c" in out, out


def case_new_component_with_hop_detected():
    key = load("DEMO-101")
    _comp(key, "Account.Customer_Tier__c")["hop"] = 1
    code, out = run([write_key("newhop.json", key)])
    assert code == 1 and "new component must have hop null" in out, out


def case_seed_missing_from_index_detected():
    key = load("DEMO-202")
    key["seeds"].append("NoSuchSeed")
    code, out = run([write_key("seed.json", key)])
    assert code == 1 and "seed not in index: NoSuchSeed" in out, out


def case_component_in_index_but_not_reached_detected():
    key = load("DEMO-202")
    key["components"].append({"api": "LegacyCaseMerge", "type": "ApexClass", "changeType": "review",
                              "hop": 1, "why": "exists but nothing links it to the seed"})
    code, out = run([write_key("unreached.json", key)])
    assert code == 1 and "in key, not found by the index within 2 hops: LegacyCaseMerge" in out, out


def case_judgement_reachable_detected():
    key = load("DEMO-202")
    key["components"].append(_judgement("CaseTriggerHandler_Test", "demo/stories/DEMO-202.md"))
    key["components"] = [c for c in key["components"] if not (c["api"] == "CaseTriggerHandler_Test"
                                                              and c.get("source") != "judgement")]
    code, out = run([write_key("reach.json", key)])
    assert code == 1 and "judgement component is reachable from the seeds" in out, out


def case_judgement_missing_evidence_file_detected():
    key = load("DEMO-202")
    _comp(key, "Escalation_Agents")["evidence"] = "demo/org/force-app/main/default/queues/Nope.queue-meta.xml"
    code, out = run([write_key("noevidence.json", key)])
    assert code == 1 and "judgement evidence file not found: Escalation_Agents" in out, out


def case_malformed_key_exits_2_cleanly():
    key = load("DEMO-202")
    key["components"][0]["changeType"] = "rewrite"
    code, out = run([write_key("bad.json", key)])
    assert code == 2 and "Traceback" not in out and "changeType" in out, out
    key = load("DEMO-202")
    key["components"].append(dict(key["components"][0]))
    code, out = run([write_key("dup.json", key)])
    assert code == 2 and "duplicate component" in out, out
    key = load("DEMO-202")
    key["decisions"] = [{"text": "no owner"}]
    code, out = run([write_key("dec.json", key)])
    assert code == 2 and "decisions" in out, out
    code, out = run([os.path.join(TMP, "does-not-exist.json")])
    assert code == 2 and "Traceback" not in out, out


def _malformed(mutate, expect):
    key = load("DEMO-202")
    mutate(key)
    code, out = run([write_key("mal.json", key)])
    assert code == 2 and "Traceback" not in out and expect in out, (code, out)


def case_schema_negatives_exit_2():
    _malformed(lambda k: k.update(version=2), "version must be 1")
    _malformed(lambda k: k.update(hops=4), "hops must be")
    _malformed(lambda k: k.update(hops=0), "hops must be")
    _malformed(lambda k: k["components"][0].update(why="  "), "why must be")
    _malformed(lambda k: k["components"][0].update(source="guess"), "source must be")
    _malformed(lambda k: _comp(k, "Escalation_Agents").pop("evidence"), "needs an evidence path")
    _malformed(lambda k: k.update(assumptions="one string"), "assumptions must be")
    _malformed(lambda k: k.update(assumptions=[1]), "assumptions must be")


def case_evidence_path_escape_rejected():
    _malformed(lambda k: _comp(k, "Escalation_Agents").update(evidence="/etc/hosts"), "inside the repo")
    _malformed(lambda k: _comp(k, "Escalation_Agents").update(evidence="demo/../../x"), "inside the repo")


def case_judgement_with_hop_detected():
    key = load("DEMO-202")
    _comp(key, "Escalation_Agents")["hop"] = 1
    code, out = run([write_key("jhop.json", key)])
    assert code == 1 and "judgement component must have hop null: Escalation_Agents" in out, out


def case_judgement_type_mismatch_detected():
    key = load("DEMO-101")
    _comp(key, "caseEscalationPanel")["type"] = "ApexClass"
    code, out = run([write_key("jtype.json", key)])
    assert code == 1 and "wrong type: caseEscalationPanel" in out, out


def case_missing_index_exits_2_cleanly():
    p = subprocess.run([sys.executable, CHECK, "--index", os.path.join(TMP, "nope"), KEYS[0]],
                       capture_output=True, text=True)
    assert p.returncode == 2 and "Traceback" not in p.stderr, p.stderr


def case_overlap_present():
    a = {c["api"] for c in load("DEMO-201")["components"]}
    b = {c["api"] for c in load("DEMO-202")["components"]}
    assert "CaseTriggerHandler" in a & b, a & b


def main():
    build()
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("case_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
