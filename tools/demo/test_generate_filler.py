#!/usr/bin/env python3
"""Tests for generate_filler.py. Each case builds its own temp dirs; demo/org is only read.

Run: python3 tools/demo/test_generate_filler.py
"""
import atexit
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
GEN = os.path.join(HERE, "generate_filler.py")
DEFAULT = "force-app/main/default"
NS = {"m": "http://soap.sforce.com/2006/04/metadata"}

# The hand-written story core (Task 5). Fixed list on purpose: demo/org also holds the filler, so
# scanning it could not tell the two apart. case_core_list_is_current keeps this list honest.
CORE_NAMES = sorted([
    "CaseAccountSummaryController", "CaseAccountSummaryController_Test",
    "CaseAssignmentService", "CaseAssignmentService_Test",
    "CaseEscalationService", "CaseEscalationService_Test",
    "CaseTriggerHandler", "CaseTriggerHandler_Test",
    "EscalationNotifier", "EscalationNotifier_Test",
    "LegacyCaseMerge", "LegacyCaseMerge_Test",
    "CaseTrigger", "caseAccountSummary", "caseEscalationPanel",
    "Case_Escalate_Premium", "Case_Agent_Console",
    "Service_Level__c", "Escalation_Level__c", "Escalation_Reason__c", "Premium_SLA_Hours__c",
    "Escalation_Needs_Level", "Premium_Support", "Premium_Support_Process",
    "Sales_Rep", "Service_Agent", "Team_Lead", "Escalation_Agents",
])
CORE_FILES = [
    "classes/CaseAccountSummaryController.cls", "classes/CaseAssignmentService.cls",
    "classes/CaseEscalationService.cls", "classes/CaseTriggerHandler.cls",
    "classes/EscalationNotifier.cls", "classes/LegacyCaseMerge.cls", "triggers/CaseTrigger.trigger",
    "lwc/caseAccountSummary/caseAccountSummary.js", "lwc/caseEscalationPanel/caseEscalationPanel.js",
    "flows/Case_Escalate_Premium.flow-meta.xml", "flexipages/Case_Agent_Console.flexipage-meta.xml",
    "objects/Account/fields/Service_Level__c.field-meta.xml",
    "objects/Case/fields/Escalation_Level__c.field-meta.xml",
    "objects/Case/fields/Escalation_Reason__c.field-meta.xml",
    "objects/Entitlement/fields/Premium_SLA_Hours__c.field-meta.xml",
    "objects/Case/validationRules/Escalation_Needs_Level.validationRule-meta.xml",
    "objects/Case/recordTypes/Premium_Support.recordType-meta.xml",
    "objects/Case/businessProcesses/Premium_Support_Process.businessProcess-meta.xml",
    "permissionsets/Sales_Rep.permissionset-meta.xml", "permissionsets/Service_Agent.permissionset-meta.xml",
    "permissionsets/Team_Lead.permissionset-meta.xml", "queues/Escalation_Agents.queue-meta.xml",
]

_TEMP_DIRS = []


def tmpdir():
    d = tempfile.mkdtemp(prefix="filler-test-")
    _TEMP_DIRS.append(d)
    return d


def run_cli(*args):
    return subprocess.run([sys.executable, GEN, *args], capture_output=True, text=True, cwd=REPO)


def load_gen():
    spec = importlib.util.spec_from_file_location("generate_filler", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def digests(root):
    out = {}
    for dp, _, files in os.walk(root):
        for f in files:
            p = os.path.join(dp, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root).replace(os.sep, "/")] = hashlib.sha256(fh.read()).hexdigest()
    return out


def generated(seed=2026):
    """{relative path under the default package dir: text}"""
    files = load_gen().generate(seed)
    prefix = DEFAULT + "/"
    return {p[len(prefix):]: b.decode("utf-8") for p, b in files.items()}


def word_re(name):
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])")


def case_two_runs_identical():
    a, b = tmpdir(), tmpdir()
    assert run_cli("--seed", "2026", "--out", a).returncode == 0
    assert run_cli("--seed", "2026", "--out", b).returncode == 0
    da, db = digests(a), digests(b)
    assert da and da == db
    assert len(da) >= 200, "expected hundreds of files"


def case_seed_changes_output():
    assert load_gen().generate(2026) != load_gen().generate(7)


def case_check_matches_committed():
    r = run_cli("--seed", "2026", "--out", "demo/org", "--check")
    assert r.returncode == 0, r.stdout + r.stderr


def case_check_reports_drift_and_writes_nothing():
    d = tmpdir()
    assert run_cli("--seed", "2026", "--out", d).returncode == 0
    files = sorted(digests(d))
    victim = os.path.join(d, files[0])
    other = os.path.join(d, files[1])
    with open(victim, "ab") as fh:
        fh.write(b"drift\n")
    os.remove(other)
    before = digests(d)
    r = run_cli("--seed", "2026", "--out", d, "--check")
    assert r.returncode == 1
    assert files[0] in r.stdout + r.stderr and files[1] in r.stdout + r.stderr
    assert digests(d) == before, "--check must write nothing"


def case_isolated_from_core():
    files = generated()
    pats = [(n, word_re(n)) for n in CORE_NAMES]
    for path, text in files.items():
        for n, p in pats:
            assert not p.search(path) and not p.search(text), f"{path} mentions core name {n}"
        # Case and Entitlement are off limits entirely.
        assert not re.search(r"\b(Case|Entitlement)\b", text), f"{path} mentions Case/Entitlement"
        assert not path.startswith(("objects/Case/", "objects/Entitlement/")), path


def case_core_list_is_current():
    for f in CORE_FILES:
        assert os.path.exists(os.path.join(REPO, "demo/org", DEFAULT, f)), f
    base = os.path.join(REPO, "demo/org", DEFAULT)
    stems = set()
    for dp, _, files in os.walk(base):
        for f in files:
            stems.add(f.split(".")[0])
    gen_paths = set(generated())
    for dp, _, files in os.walk(base):
        for f in files:
            rel = os.path.relpath(os.path.join(dp, f), base).replace(os.sep, "/")
            if rel not in gen_paths:  # a core file: its name must be in CORE_NAMES
                # sfdx-project.json is the package manifest, not metadata
                assert f.split(".")[0] in CORE_NAMES or f == "sfdx-project.json", f"core file not in list: {rel}"


def case_no_name_collisions_with_core_or_each_other():
    files = generated()
    shorts = {}
    for path in files:
        m = re.match(r"objects/(\w+)/fields/(\w+)\.field-meta\.xml$", path)
        if m:
            assert m.group(1) in ("Account", "Contact", "Lead", "Opportunity"), path
            assert m.group(2) not in shorts, f"field name reused: {m.group(2)}"
            shorts[m.group(2)] = m.group(1)
    assert len(shorts) >= 40
    assert not set(shorts) & set(CORE_NAMES)


def case_refuses_overwrite():
    d = tmpdir()
    assert run_cli("--seed", "2026", "--out", d).returncode == 0
    again = run_cli("--seed", "2026", "--out", d)
    assert again.returncode == 0, "identical content must be skipped silently"
    files = sorted(digests(d))
    victim = files[3]
    with open(os.path.join(d, victim), "wb") as fh:
        fh.write(b"hand edited\n")
    r = run_cli("--seed", "2026", "--out", d)
    assert r.returncode == 2, r.returncode
    assert victim in r.stdout + r.stderr
    with open(os.path.join(d, victim), "rb") as fh:
        assert fh.read() == b"hand edited\n", "must not overwrite"


def case_flow_kinds():
    kinds = {}
    for path, text in generated().items():
        if path.startswith("flows/"):
            el = ET.fromstring(text)
            ptype = el.find("m:processType", NS).text
            kinds.setdefault(ptype, []).append(path)
            assert el.find("m:status", NS).text == "Active"
    assert len(kinds.get("AutoLaunchedFlow", [])) >= 10
    assert len(kinds.get("Flow", [])) >= 5
    for p in kinds["AutoLaunchedFlow"]:
        t = generated()[p]
        assert "<triggerType>RecordBeforeSave</triggerType>" in t
    assert any(p.endswith("Lead_Qualification_Screen.flow-meta.xml") for p in kinds["Flow"])


def case_apex_follows_rules():
    files = generated()
    classes = {p: t for p, t in files.items() if p.startswith("classes/") and p.endswith(".cls")}
    assert len(classes) >= 40
    for p, t in classes.items():
        name = os.path.basename(p)[:-4]
        assert re.search(r"\bwith sharing\b", t), p
        assert "without sharing" not in t, p
        assert "System.debug" not in t, p
        assert "SeeAllData" not in t and "System.assert(true" not in t, p
        assert f"{p}-meta.xml" in files, p
        if name.endswith("_Test"):
            assert "@IsTest" in t and len(re.findall(r"Assert\.\w+\(", t)) >= 4, p
        else:
            assert f"classes/{name}_Test.cls" in files, p
            assert "WITH USER_MODE" in t and "AccessLevel.USER_MODE" in t, p
            assert "@AuraEnabled(cacheable=true)" in t, p
        # no SOQL or DML inside a for/while body: track brace depth of loops
        depth, loop_depths = 0, []
        for line in t.splitlines():
            s = line.strip()
            if re.match(r"(for|while)\b.*\{\s*$", s):
                loop_depths.append(depth)
            in_loop = bool(loop_depths)
            if in_loop and not re.match(r"(for|while)\b", s):
                assert not re.search(r"\[\s*SELECT\b|\binsert\b|\bupdate\b|\bdelete\b|Database\.(insert|update|delete)", s), \
                    f"{p}: SOQL/DML in loop: {s}"
            depth += s.count("{") - s.count("}")
            while loop_depths and depth <= loop_depths[-1]:
                loop_depths.pop()
    metas = [t for p, t in files.items() if p.startswith("classes/") and p.endswith("-meta.xml")]
    old = {p: t for p, t in files.items() if p.startswith("classes/") and p.endswith("-meta.xml")
           and "<apiVersion>62.0</apiVersion>" not in t}
    assert sorted(re.search(r"<apiVersion>(.*?)<", t).group(1) for t in old.values()) == ["48.0", "52.0"], old
    assert all(not p.endswith("_Test.cls-meta.xml") for p in old), old
    assert len(metas) > len(old)


def case_api_version_is_a_parameter():
    gen = load_gen()
    assert gen.API_VERSION == "62.0"
    assert "<apiVersion>55.0</apiVersion>" in gen.apex_meta("55.0")


def case_lwc_apex_imports_resolve():
    files = generated()
    n = 0
    for p, t in files.items():
        m = re.match(r"lwc/(\w+)/\1\.js$", p)
        if not m:
            continue
        n += 1
        imp = re.search(r"@salesforce/apex/(\w+)\.(\w+)", t)
        assert imp, p
        cls = files[f"classes/{imp.group(1)}.cls"]
        assert re.search(r"@AuraEnabled\(cacheable=true\)\s+public static \w+ " + imp.group(2) + r"\(", cls), p
        assert f"lwc/{m.group(1)}/{m.group(1)}.html" in files
        assert f"lwc/{m.group(1)}/{m.group(1)}.js-meta.xml" in files
    assert n >= 20


def case_permission_sets_scoped():
    files = generated()
    sets = {p: t for p, t in files.items() if p.startswith("permissionsets/")}
    assert len(sets) == 4
    for p, t in sets.items():
        el = ET.fromstring(t)
        objs = [o.find("m:object", NS).text for o in el.findall("m:objectPermissions", NS)]
        assert len(objs) == 1 and objs[0] in ("Account", "Contact", "Lead", "Opportunity"), p
        for fp in el.findall("m:fieldPermissions", NS):
            f = fp.find("m:field", NS).text
            assert f.startswith(objs[0] + "."), (p, f)
            assert f.split(".")[1] in {m.group(1) for m in
                                       (re.match(r"objects/\w+/fields/(\w+)\.field-meta\.xml", q) for q in files) if m}


def rules_by_field(files):
    """{(object, field): [(rule name, lower, upper)]} read from the generated rule files and formulas."""
    out = {}
    for p, t in files.items():
        m = re.match(r"objects/(\w+)/validationRules/(\w+)\.validationRule-meta\.xml$", p)
        if not m:
            continue
        el = ET.fromstring(t)
        field = el.find("m:errorDisplayField", NS).text
        formula = el.find("m:errorConditionFormula", NS).text
        lo = hi = None
        if "DATE(" not in formula:
            if re.search(rf"{field} < 0", formula):
                lo = 0
            if re.search(rf"{field} > 100", formula):
                hi = 100
            assert lo is not None, f"unrecognised rule formula in {p}"
        out.setdefault((m.group(1), field), []).append((m.group(2), lo, hi))
    return out


def case_test_values_satisfy_validation_rules():
    files = generated()
    rules = rules_by_field(files)
    pairs = 0
    for p, t in files.items():
        m = re.match(r"classes/(\w+)_Test\.cls$", p)
        if not m:
            continue
        pairs += 1
        svc = files[f"classes/{m.group(1)}.cls"]
        obj = re.search(r"new (\w+)\(.*?(\w+__c) = value\)", t).group(1, 2)
        high = int(re.search(r"HIGH_THRESHOLD = (\d+);", svc).group(1))
        med = int(re.search(r"MEDIUM_THRESHOLD = (\d+);", svc).group(1))
        for value in (high, med, med - 1):  # every value sampleRecord is called with
            for name, lo, hi in rules.get(obj, []):
                assert lo is None or value >= lo, f"{p}: {value} violates {name}"
                assert hi is None or value <= hi, f"{p}: {value} violates {name}"
    assert pairs >= 40


def case_rules_are_plausible():
    files = generated()
    ftypes = {}
    for p, t in files.items():
        m = re.match(r"objects/(\w+)/fields/(\w+)\.field-meta\.xml$", p)
        if m:
            ftypes[(m.group(1), m.group(2))] = ET.fromstring(t).find("m:type", NS).text
    count = 0
    for (obj, field), rs in rules_by_field(files).items():
        for name, lo, hi in rs:
            count += 1
            if hi is not None:
                assert ftypes[(obj, field)] == "Percent" or field.endswith("Score__c"), name
            if hi is None and lo is not None:
                assert field not in ("Forecast_Adjustment__c",), name
                assert ftypes[(obj, field)] in ("Number", "Currency"), name
    assert count >= 12


def case_stamp_fields_are_status_like():
    files = generated()
    for p, t in files.items():
        if re.match(r"classes/\w+(?<!_Test)\.cls$", p):
            m = re.search(r"changed\.add\(new \w+\(Id = row\.Id, (\w+) = band\)\)", t)
            assert m and re.search(r"(Band|Tier|Priority|Status)", m.group(1)), (p, m and m.group(1))
        if p.startswith("flows/") and "AutoLaunchedFlow" in t:
            m = re.search(r"<assignToReference>\$Record\.(\w+)</assignToReference>", t)
            assert m and re.search(r"Status(__c|_Label__c)$", m.group(1)), p


def case_files_are_wellformed_lf_utf8():
    for path, text in generated().items():
        assert "\r" not in text, path
        assert text.endswith("\n"), path
        if path.endswith(".xml"):
            ET.fromstring(text)
        text.encode("utf-8")


def main():
    failures = 0
    for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("case_") and callable(f)):
        try:
            fn()
            print(f"[PASS] {name}")
        except Exception as exc:
            failures += 1
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
    print(f"{'PASS' if not failures else 'FAIL'}: {failures} failing case(s)")
    return 1 if failures else 0


atexit.register(lambda: [shutil.rmtree(d, ignore_errors=True) for d in _TEMP_DIRS])


if __name__ == "__main__":
    sys.exit(main())
