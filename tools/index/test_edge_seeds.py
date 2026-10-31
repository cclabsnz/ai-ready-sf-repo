#!/usr/bin/env python3
"""Tests for `query.py edge-seeds` and its edge_seeds() function. Synthetic index and temp files only.

Run: python3 tools/index/test_edge_seeds.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
QUERY = os.path.join(HERE, "query.py")
_spec = importlib.util.spec_from_file_location("query", QUERY)
query = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(query)

FIELD_PATH = "objects/Thing__c/fields/Pick__c.field-meta.xml"
FIELD_FILE = ('<?xml version="1.0" encoding="UTF-8"?>\n'
              '<CustomField>\n'
              '    <required>false</required>\n'
              '    <type>Picklist</type>\n'
              '</CustomField>\n')
GLOBAL_PATH = "objects/Thing__c/fields/Glob__c.field-meta.xml"
GLOBAL_FILE = ('<CustomField>\n'
               '    <type>Picklist</type>\n'
               '    <valueSet>\n'
               '        <valueSetName>Shared_Set</valueSetName>\n'
               '    </valueSet>\n'
               '</CustomField>\n')
OBJECT_PATH = "objects/Thing__c/Thing__c.object-meta.xml"
OBJECT_FILE = '<?xml version="1.0"?>\n<CustomObject>\n</CustomObject>\n'

_DIRS = []


def make_root():
    root = tempfile.mkdtemp()
    _DIRS.append(root)
    for rel, body in ((FIELD_PATH, FIELD_FILE), (GLOBAL_PATH, GLOBAL_FILE), (OBJECT_PATH, OBJECT_FILE)):
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
    return root


def make_idx(integration=True):
    nodes = {
        "Thing__c": {"type": "CustomObject", "path": OBJECT_PATH},
        "Thing__c.Pick__c": {
            "type": "CustomField", "fieldType": "Picklist", "required": False, "path": FIELD_PATH,
            "picklistValues": [{"value": "Open", "active": True, "line": 7},
                               {"value": "Old", "active": False, "line": 11}]},
        "Thing__c.Glob__c": {"type": "CustomField", "fieldType": "Picklist", "required": True,
                             "path": GLOBAL_PATH, "globalValueSet": "Shared_Set"},
        "Thing__c.Plain__c": {"type": "CustomField", "fieldType": "Text", "required": True,
                              "path": FIELD_PATH},
        "Thing__c.Rule": {"type": "ValidationRule", "active": True, "path": "r.xml"},
        "Thing__c.Biz": {"type": "RecordType", "path": "rt.xml"},
        "Thing_Flow": {"type": "Flow", "status": "Active", "path": "f.xml"},
        "ThingTrigger": {"type": "ApexTrigger", "path": "t.trigger"},
        "Case": {"type": "CustomObject", "path": None},
        "Reader_Perm": {"type": "PermissionSet", "path": "p.xml"},
        "Sales_Edit": {"type": "PermissionSet", "path": "p2.xml"},
        "Apex_Helper": {"type": "ApexClass", "path": "h.cls"},
    }
    edges = [
        {"from": "Thing__c.Pick__c", "to": "Thing__c", "kind": "fieldOf"},
        {"from": "Thing__c.Glob__c", "to": "Thing__c", "kind": "fieldOf"},
        {"from": "Thing__c.Plain__c", "to": "Thing__c", "kind": "fieldOf"},
        {"from": "Thing__c.Rule", "to": "Thing__c", "kind": "validationRuleOf", "evidence": "r.xml:2"},
        {"from": "Thing__c.Biz", "to": "Thing__c", "kind": "recordTypeOf", "evidence": "rt.xml:2"},
        {"from": "Thing_Flow", "to": "Thing__c", "kind": "flowTriggerObject", "evidence": "f.xml:9"},
        {"from": "ThingTrigger", "to": "Thing__c", "kind": "triggerOn", "evidence": "t.trigger:1"},
        {"from": "Reader_Perm", "to": "Thing__c.Pick__c", "kind": "fieldPermission", "editable": False,
         "evidence": "p.xml:5"},
        {"from": "Sales_Edit", "to": "Thing__c.Pick__c", "kind": "fieldPermission", "editable": True,
         "evidence": "p2.xml:5"},
    ]
    if integration:
        nodes["Integration_Writer"] = {"type": "PermissionSet", "path": "p3.xml"}
        edges.append({"from": "Integration_Writer", "to": "Thing__c.Pick__c", "kind": "fieldPermission",
                      "editable": True, "evidence": "p3.xml:5"})
    return {"nodes": nodes, "edges": edges, "stamp": {"commit": "x"}}


def by(seeds, category, component=None):
    return [s for s in seeds if s["category"] == category and (component is None or s["component"] == component)]


def case_field_seed_covers_field_and_object():
    r = query.edge_seeds(make_idx(), ["Thing__c.Pick__c"], make_root())
    comps = {s["component"] for s in r["seeds"]}
    assert comps == {"Thing__c.Pick__c", "Thing__c"}, comps
    blank = by(r["seeds"], "blank")[0]
    assert blank["evidence"] == f"{FIELD_PATH}:3" and blank["confidence"] == "Confirmed", blank
    assert {s["detail"] for s in by(r["seeds"], "field-access")} == {
        "Reader_Perm read", "Sales_Edit edit", "Integration_Writer edit"}
    assert by(r["seeds"], "record-type", "Thing__c")[0]["evidence"] == "rt.xml:2"
    auto = {s["detail"] for s in by(r["seeds"], "automation", "Thing__c")}
    assert auto == {"validation rule Thing__c.Rule (active)", "flow Thing_Flow (Active)",
                    "trigger ThingTrigger (status not in index)"}, auto
    bulk = by(r["seeds"], "bulk")[0]
    assert bulk["evidence"] == "t.trigger:1", bulk
    assert r["unresolved"] == []


def case_object_seed_covers_object_only():
    r = query.edge_seeds(make_idx(), ["Thing__c"], make_root())
    assert {s["component"] for s in r["seeds"]} == {"Thing__c"}
    assert not by(r["seeds"], "blank") and not by(r["seeds"], "picklist-value")
    assert by(r["seeds"], "automation") and by(r["seeds"], "bulk")


def case_inactive_value_marked():
    r = query.edge_seeds(make_idx(), ["Thing__c.Pick__c"], make_root())
    vals = {s["detail"]: s for s in by(r["seeds"], "picklist-value")}
    assert set(vals) == {"Open", "Old (inactive)"}, set(vals)
    assert vals["Old (inactive)"]["evidence"] == f"{FIELD_PATH}:11"
    assert vals["Old (inactive)"]["confidence"] == "Confirmed"


def case_global_value_set_unverifiable():
    r = query.edge_seeds(make_idx(), ["Thing__c.Glob__c"], make_root())
    pv = by(r["seeds"], "picklist-value")
    assert len(pv) == 1, pv
    assert pv[0]["detail"] == "global value set; values not in this repo"
    assert pv[0]["confidence"] == "Unverifiable"
    assert pv[0]["evidence"] == f"{GLOBAL_PATH}:4"
    assert not by(r["seeds"], "blank")  # required field


def case_unresolved_seed_listed():
    r = query.edge_seeds(make_idx(), ["Nope__c.Missing__c", "Apex_Helper", "Case"], make_root())
    assert r["unresolved"] == ["Nope__c.Missing__c", "Apex_Helper"], r["unresolved"]
    case_seeds = [s for s in r["seeds"] if s["component"] == "Case"]
    bulk = by(case_seeds, "bulk")[0]
    assert bulk["evidence"] is None and bulk["confidence"] == "Unverifiable", bulk


def case_integration_user_only_when_permset_matches():
    root = make_root()
    with_perm = query.edge_seeds(make_idx(True), ["Thing__c.Pick__c"], root)
    integ = by(with_perm["seeds"], "integration-user")
    assert len(integ) == 1 and integ[0]["confidence"] == "Inferred", integ
    assert integ[0]["evidence"] == "p3.xml:5" and "Integration_Writer" in integ[0]["detail"]
    without = query.edge_seeds(make_idx(False), ["Thing__c.Pick__c"], root)
    assert not by(without["seeds"], "integration-user")


def case_org_only_once_per_object_unverifiable():
    r = query.edge_seeds(make_idx(), ["Thing__c.Pick__c", "Thing__c", "Thing__c.Glob__c", "Case"],
                         make_root())
    org = by(r["seeds"], "org-only")
    assert sorted(s["component"] for s in org) == ["Case", "Thing__c"], org
    for s in org:
        assert s["detail"] == ("sharing settings and real data volumes are org configuration, "
                               "not in this repo"), s
        assert s["evidence"] is None and s["confidence"] == "Unverifiable", s
    assert not [s for s in org if s["component"].startswith("Thing__c.")]
    assert query.edge_seeds(make_idx(), ["Nope__c"], make_root())["seeds"] == []


def case_no_blank_seed_for_derived_or_master_detail():
    idx = make_idx()
    for name, extra in (("Md", {"fieldType": "MasterDetail"}), ("Auto", {"fieldType": "AutoNumber"}),
                        ("Roll", {"fieldType": "Summary"}), ("Frm", {"fieldType": "Text", "formula": True})):
        idx["nodes"]["Thing__c." + name] = {"type": "CustomField", "required": False,
                                            "path": FIELD_PATH, **extra}
        idx["edges"].append({"from": "Thing__c." + name, "to": "Thing__c", "kind": "fieldOf"})
        r = query.edge_seeds(idx, ["Thing__c." + name], make_root())
        assert not by(r["seeds"], "blank"), (name, r["seeds"])
    idx["nodes"]["Thing__c.Txt"] = {"type": "CustomField", "required": False, "fieldType": "Text",
                                    "path": FIELD_PATH}
    assert by(query.edge_seeds(idx, ["Thing__c.Txt"], make_root())["seeds"], "blank")


def case_unresolved_deduplicated_in_order():
    r = query.edge_seeds(make_idx(), ["Foo", "Bar", "Foo", "Apex_Helper", "Apex_Helper"], make_root())
    assert r["unresolved"] == ["Foo", "Bar", "Apex_Helper"], r["unresolved"]


def case_deterministic_order():
    root = make_root()
    a = json.dumps(query.edge_seeds(make_idx(), ["Thing__c.Pick__c", "Thing__c", "Case"], root))
    b = json.dumps(query.edge_seeds(make_idx(), ["Thing__c.Pick__c", "Thing__c", "Case"], root))
    assert a == b
    seeds = json.loads(a)["seeds"]
    keys = [(s["component"], s["category"], s["detail"]) for s in seeds]
    assert keys == sorted(keys) and len(keys) == len(set(keys))


def _write_index(idx):
    d = tempfile.mkdtemp()
    _DIRS.append(d)
    with open(os.path.join(d, "metadata.json"), "w") as fh:
        json.dump(idx, fh)
    return d


def _run(*args):
    return subprocess.run([sys.executable, QUERY, *args], capture_output=True, text=True)


def case_cli_multiple_apis():
    root = make_root()
    index = _write_index(make_idx())
    p = _run("edge-seeds", "Thing__c.Pick__c", "Nope__c", "--index", index, "--root", root)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["unresolved"] == ["Nope__c"] and by(out["seeds"], "picklist-value")
    allbad = _run("edge-seeds", "Nope__c", "--index", index, "--root", root)
    assert allbad.returncode == 0 and json.loads(allbad.stdout) == {"seeds": [], "unresolved": ["Nope__c"]}
    assert _run("edge-seeds", "--index", index).returncode == 2


def case_other_subcommands_unchanged():
    index = _write_index(make_idx())
    e = json.loads(_run("exists", "Thing__c", "--index", index).stdout)
    assert e == {"api": "Thing__c", "exists": True, "note": None}, e
    m = json.loads(_run("exists", "Nope", "--index", index).stdout)
    assert m["exists"] is False and m["note"].startswith("zero hits in index")
    t = json.loads(_run("type", "Thing__c", "--index", index).stdout)
    assert t["found"] is True and t["node"]["type"] == "CustomObject"
    c = json.loads(_run("consumers", "Thing__c", "--hops", "1", "--index", index).stdout)
    assert c["api"] == "Thing__c" and c["hops"] == 1 and c["count"] >= 4
    assert _run("exists", "A", "B", "--index", index).returncode == 2


def main():
    passed = failed = 0
    for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("case_") and callable(f)):
        try:
            fn()
            passed += 1
            print(f"[PASS] {name[5:]}")
        except Exception as exc:
            failed += 1
            print(f"[FAIL] {name[5:]}: {type(exc).__name__}: {exc}")
    for d in _DIRS:
        shutil.rmtree(d, ignore_errors=True)
    print(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
