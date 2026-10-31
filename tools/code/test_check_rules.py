#!/usr/bin/env python3
"""Tests for check_rules.py. Temp trees go under one temp dir; the checkout is only read.

Run: python3 tools/code/test_check_rules.py
"""
import atexit
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CHECK = os.path.join(HERE, "check_rules.py")
ONBOARD = os.path.join(REPO, "tools", "onboard", "onboard.py")
BASELINE = os.path.join(HERE, "baseline.json")
DEMO_ORG = os.path.join(REPO, "demo", "org")
RULES_MD = os.path.join(REPO, "framework", "rules", "10-apex.md")
LEGACY = ("LegacyCaseMerge", "RenewalOutlookService", "ContractTermService")
BANNED = ("we recommend", "should", "approve", "block")

TMP = tempfile.mkdtemp(prefix="check_rules_")
atexit.register(shutil.rmtree, TMP, True)
_MOD = []


def cr():
    """check_rules, loaded by path on first use, so a missing module fails each case, not the run."""
    if not _MOD:
        spec = importlib.util.spec_from_file_location("check_rules", CHECK)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MOD.append(mod)
    return _MOD[0]


def rules_of(src, path="force-app/main/default/classes/X.cls"):
    return [(f["rule"], f["line"]) for f in cr().check_file(path, src)]


def only(src, rule):
    return [line for r, line in rules_of(src) if r == rule]


def wrap(body, head="public with sharing class X {"):
    return head + "\n" + body + "\n}\n"


def new_repo(files):
    """A temp repo: {relative path: text}, with .ai-framework.json pointing at org/."""
    root = tempfile.mkdtemp(dir=TMP)
    with open(os.path.join(root, ".ai-framework.json"), "w", encoding="utf-8") as fh:
        json.dump({"startingPoint": "existing", "sourceRoot": "org"}, fh)
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    return root


def cls_path(name):
    return "org/force-app/main/default/classes/%s.cls" % name


def run(args, cwd=REPO):
    p = subprocess.run([sys.executable, CHECK] + args, capture_output=True, text=True, cwd=cwd)
    return p.returncode, p.stdout, p.stderr


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


# ---- rules: one positive and one negative each -------------------------------------------------

def case_sharing_missing_flagged():
    assert only("public class X {\n}\n", "apex-sharing") == [1]
    assert only("@IsTest\nprivate class X_Test {\n}\n", "apex-sharing") == [2]


def case_sharing_declared_ok():
    for head in ("public with sharing class X {", "public inherited sharing class X {",
                 "global WITH SHARING virtual class X {"):
        assert only(head + "\n}\n", "apex-sharing") == [], head
    assert only(wrap("Type t = X.class;"), "apex-sharing") == []  # X.class is not a declaration


def case_inner_class_needs_sharing():
    src = wrap("    public class Inner {\n    }\n    private with sharing class Ok {\n    }")
    assert only(src, "apex-sharing") == [2], rules_of(src)


def case_without_sharing_needs_comment():
    assert only("public without sharing class X {\n}\n", "apex-sharing") == [1]
    far = "// reason, too far up\n\n\n\npublic without sharing class X {\n}\n"
    assert only(far, "apex-sharing") == [5]
    near = "// Why without sharing: the job must see every record.\n\npublic without sharing class X {\n}\n"
    assert only(near, "apex-sharing") == []
    block = "/*\n * Runs as the integration user.\n */\npublic without sharing class X {\n}\n"
    assert only(block, "apex-sharing") == []
    string_only = "String s = 'x';\npublic without sharing class X {\n}\n"
    assert only(string_only, "apex-sharing") == [2]
    after_string = ("@SuppressWarnings('PMD.ApexSharingViolations') // the batch must see every record\n"
                    "public without sharing class X {\n}\n")
    assert only(after_string, "apex-sharing") == []


def case_soql_without_user_mode_flagged():
    src = wrap("    List<Account> a = [SELECT Id FROM Account];")
    assert only(src, "apex-user-mode") == [2]
    low = wrap("    List<Account> a = [\n        select Id\n        from Account\n    ];")
    assert only(low, "apex-user-mode") == [2]


def case_soql_with_user_mode_ok():
    src = wrap("    List<Account> a = [\n        SELECT Id FROM Account\n        WITH USER_MODE\n    ];")
    assert only(src, "apex-user-mode") == []
    sub = wrap("    List<Account> a = [SELECT Id, (SELECT Id FROM Contacts) FROM Account "
               "WHERE Id IN :ids[0] WITH USER_MODE];")
    assert only(sub, "apex-user-mode") == []


def case_system_mode_needs_comment():
    bare = wrap("    List<Account> a = [SELECT Id FROM Account WITH SYSTEM_MODE];")
    assert only(bare, "apex-user-mode") == [2]
    noted = wrap("    // System mode: the count feeds a public total, never a record.\n"
                 "    List<Account> a = [SELECT Id FROM Account WITH SYSTEM_MODE];")
    assert only(noted, "apex-user-mode") == []


def case_test_class_exempt_from_user_mode():
    src = ("@IsTest\nprivate with sharing class X_Test {\n"
           "    static void setup() {\n"
           "        Profile p = [SELECT Id FROM Profile LIMIT 1];\n"
           "        insert new Account(Name = 'Sample');\n"
           "        Database.update(rows, false);\n"
           "        List<Account> a = [SELECT Id FROM Account WITH SECURITY_ENFORCED];\n"
           "        for (Id i : ids) {\n            update rows;\n        }\n"
           "        System.debug('x');\n"
           "    }\n}\n")
    found = rules_of(src)
    assert "apex-user-mode" not in [r for r, _ in found], found
    assert ("apex-no-soql-dml-in-loop", 9) in found and ("apex-no-system-debug", 11) in found, found
    # The exemption ends with the test class; a plain class after it is still checked.
    after = src + "public with sharing class Y {\n    void f() { update rows; }\n}\n"
    assert only(after, "apex-user-mode") == [15], rules_of(after)
    assert only(wrap("    insert acc;"), "apex-user-mode") == [2]


def case_security_enforced_flagged():
    src = wrap("    List<Account> a = [SELECT Id FROM Account WITH SECURITY_ENFORCED];")
    assert only(src, "apex-user-mode") == [2]


def case_dml_without_user_mode_flagged():
    for stmt in ("insert acc;", "update rows;", "delete rows;", "upsert rows;",
                 "Database.update(rows, false);", "Database.insert(\n        rows,\n        false);"):
        src = wrap("    " + stmt)
        assert only(src, "apex-user-mode") == [2], stmt
    nested = wrap("    if (ok) update rows;")
    assert only(nested, "apex-user-mode") == [2]


def case_dml_user_mode_ok():
    for stmt in ("insert as user acc;", "Database.update(rows, AccessLevel.USER_MODE);",
                 "Database.insert(\n        rows,\n        AccessLevel.USER_MODE);",
                 "Integer update = 1;"):
        src = wrap("    " + stmt)
        assert only(src, "apex-user-mode") == [], stmt


def case_trigger_header_not_dml():
    src = ("trigger CaseTrigger on Case (before update, after update) {\n"
           "    CaseTriggerHandler.handle(Trigger.operationType, Trigger.new, Trigger.oldMap);\n}\n")
    found = cr().check_file("force-app/main/default/triggers/CaseTrigger.trigger", src)
    assert found == [], found
    for_update = wrap("    List<Account> a = [SELECT Id FROM Account WITH USER_MODE FOR UPDATE];")
    assert rules_of(for_update) == [], rules_of(for_update)
    switch = wrap("    switch on op {\n        when BEFORE_UPDATE {\n            run();\n        }\n    }")
    assert rules_of(switch) == [], rules_of(switch)


def case_soql_in_for_loop_flagged():
    src = wrap("    for (Id i : ids) {\n"
               "        Account a = [SELECT Id FROM Account WHERE Id = :i WITH USER_MODE];\n    }")
    assert only(src, "apex-no-soql-dml-in-loop") == [3], rules_of(src)
    dml = wrap("    while (more) {\n        Database.update(rows, AccessLevel.USER_MODE);\n    }")
    assert only(dml, "apex-no-soql-dml-in-loop") == [3], rules_of(dml)
    nested = wrap("    for (Id i : ids) {\n        if (i != null) {\n"
                  "            insert as user new Task(WhatId = i);\n        }\n    }")
    assert only(nested, "apex-no-soql-dml-in-loop") == [4], rules_of(nested)
    do_loop = wrap("    do {\n        update as user rows;\n    } while (more);")
    assert only(do_loop, "apex-no-soql-dml-in-loop") == [3], rules_of(do_loop)


def case_soql_outside_loop_ok():
    src = wrap("    for (Id i : ids) {\n        seen.add(i);\n    }\n"
               "    List<Account> a = [SELECT Id FROM Account WHERE Id IN :ids WITH USER_MODE];\n"
               "    Database.update(a, AccessLevel.USER_MODE);")
    assert only(src, "apex-no-soql-dml-in-loop") == [], rules_of(src)
    after_do = wrap("    do {\n        n++;\n    } while (n < 3);\n    update as user rows;")
    assert only(after_do, "apex-no-soql-dml-in-loop") == [], rules_of(after_do)


def case_soql_for_loop_header_ok():
    src = wrap("    for (Account a : [SELECT Id FROM Account WITH USER_MODE]) {\n        seen.add(a.Id);\n    }")
    assert only(src, "apex-no-soql-dml-in-loop") == [], rules_of(src)
    inner = wrap("    for (Id i : ids) {\n        for (Account a : [SELECT Id FROM Account WITH USER_MODE]) {\n"
                 "            seen.add(a.Id);\n        }\n    }")
    assert only(inner, "apex-no-soql-dml-in-loop") == [3], rules_of(inner)


def case_system_debug_flagged():
    assert only(wrap("    System.debug('x');"), "apex-no-system-debug") == [2]
    assert only(wrap("    system.DEBUG(LoggingLevel.INFO, 'x');"), "apex-no-system-debug") == [2]


def case_logger_call_ok():
    assert only(wrap("    Logger.debug('x');"), "apex-no-system-debug") == []


def case_seealldata_flagged():
    src = "@IsTest(SeeAllData=true)\nprivate with sharing class X_Test {\n}\n"
    assert only(src, "apex-no-seealldata") == [1]


def case_seealldata_false_ok():
    src = "@IsTest(SeeAllData=false)\nprivate with sharing class X_Test {\n}\n"
    assert only(src, "apex-no-seealldata") == []


def case_assert_true_flagged():
    assert only(wrap("    System.assert(true);"), "apex-no-assert-true") == [2]
    assert only(wrap("    System.assert( TRUE, 'ok');"), "apex-no-assert-true") == [2]


def case_assert_istrue_true_flagged():
    # The Assert class spelling of the same no-op assertion.
    assert only(wrap("    Assert.isTrue(true);"), "apex-no-assert-true") == [2]
    assert only(wrap("    Assert . IsTrue( true , 'always');"), "apex-no-assert-true") == [2]
    assert only(wrap("    Assert.isTrue(n > 0);\n    Assert.isTrue(trueish);\n    Assert.isFalse(true);"),
                "apex-no-assert-true") == []


def case_real_assert_ok():
    assert only(wrap("    System.assert(total > 0);\n    Assert.areEqual(2, n);"), "apex-no-assert-true") == []


def case_test_naming_flagged():
    src = "@IsTest\nprivate with sharing class XTests {\n}\n"
    assert only(src, "apex-test-naming") == [2]
    low = "@isTest private with sharing class Helper {\n}\n"
    assert only(low, "apex-test-naming") == [1]


def case_test_naming_ok():
    assert only("@IsTest\nprivate with sharing class X_Test {\n}\n", "apex-test-naming") == []
    assert only("public with sharing class XTests {\n}\n", "apex-test-naming") == []


def case_comments_and_strings_ignored():
    src = wrap("    // System.debug('x'); insert acc;\n"
               "    /* [SELECT Id FROM Account] update rows; System.assert(true);\n"
               "       public class Hidden {} */\n"
               "    String q = 'SELECT Id FROM Account WITH SECURITY_ENFORCED; System.debug(1)';\n"
               "    String r = 'for (x : y) { update rows; }';")
    assert rules_of(src) == [], rules_of(src)


def case_findings_shape_and_one_per_rule_line():
    src = wrap("    List<Account> a = [SELECT Id FROM Account WITH SECURITY_ENFORCED]; insert a;")
    found = cr().check_file("p.cls", src)
    assert [f["rule"] for f in found] == ["apex-user-mode"], found
    assert found[0] == {"rule": "apex-user-mode", "path": "p.cls", "line": 2,
                        "text": "List<Account> a = [SELECT Id FROM Account WITH SECURITY_ENFORCED]; insert a;"}


def case_rule_ids_named_in_rules_file():
    text = read(RULES_MD)
    assert cr().RULE_IDS == ("apex-sharing", "apex-user-mode", "apex-no-soql-dml-in-loop",
                             "apex-no-system-debug", "apex-no-seealldata", "apex-no-assert-true",
                             "apex-test-naming"), cr().RULE_IDS
    for rid in cr().RULE_IDS:
        assert "`%s`" % rid in text, rid


# ---- baseline ----------------------------------------------------------------------------------

LEGACY_SRC = ("public with sharing class Old {\n"
              "    void a() {\n        update rows;\n    }\n"
              "    void b() {\n        update rows;\n    }\n}\n")


def case_baseline_survives_line_move():
    root = new_repo({cls_path("Old"): LEGACY_SRC})
    code, out, err = run(["--root", root, "--write-baseline"])
    assert code == 0, err
    moved = LEGACY_SRC.replace("{\n", "{\n    // a new comment line\n\n", 1)
    write(os.path.join(root, cls_path("Old")), moved)
    code, out, err = run(["--root", root])
    data = json.loads(out)
    assert code == 0 and data["new"] == [] and len(data["baselined"]) == 2, out
    assert [f["line"] for f in data["baselined"]] == [5, 8], data["baselined"]


def case_baseline_breaks_on_edit():
    root = new_repo({cls_path("Old"): LEGACY_SRC})
    assert run(["--root", root, "--write-baseline"])[0] == 0
    edited = LEGACY_SRC.replace("update rows;", "update moreRows;", 1)
    write(os.path.join(root, cls_path("Old")), edited)
    code, out, err = run(["--root", root])
    data = json.loads(out)
    assert code == 1, (code, out, err)
    assert [(f["rule"], f["line"]) for f in data["new"]] == [("apex-user-mode", 3)], data["new"]
    # A third identical line is a new occurrence (#2), so it is new too.
    grown = LEGACY_SRC.replace("    }\n}\n", "    }\n    void c() {\n        update rows;\n    }\n}\n")
    write(os.path.join(root, cls_path("Old")), grown)
    code, out, _ = run(["--root", root])
    assert code == 1 and [f["line"] for f in json.loads(out)["new"]] == [9], out


def case_compare_baseline_detects_growth():
    root = new_repo({cls_path("Old"): LEGACY_SRC})
    assert run(["--root", root, "--write-baseline"])[0] == 0
    base = os.path.join(root, "base.json")
    shutil.copy(os.path.join(root, "tools", "code", "baseline.json"), base)
    code, out, err = run(["--root", root, "--compare-baseline", base])
    assert code == 0 and json.loads(out)["added"] == [], (code, out, err)
    # A relative path resolves against --root (the cwd here is the checkout, which has no base.json).
    code, out, err = run(["--root", root, "--compare-baseline", "base.json"])
    assert code == 0 and json.loads(out)["added"] == [], (code, out, err)
    write(os.path.join(root, cls_path("New")), "public class New {\n}\n")
    assert run(["--root", root, "--write-baseline"])[0] == 0
    code, out, err = run(["--root", root, "--compare-baseline", base])
    data = json.loads(out)
    assert code == 1, (code, out, err)
    assert [(e["rule"], e["path"]) for e in data["added"]] == [("apex-sharing", cls_path("New"))], data
    # Shrinking is fine: the base holds more than the current baseline.
    os.remove(os.path.join(root, cls_path("New")))
    os.remove(os.path.join(root, cls_path("Old")))
    assert run(["--root", root, "--write-baseline"])[0] == 0
    assert run(["--root", root, "--compare-baseline", base])[0] == 0
    code, _, err = run(["--root", root, "--compare-baseline", os.path.join(root, "absent.json")])
    assert code == 2 and "Traceback" not in err, err
    write(os.path.join(root, "bad.json"), '{"version": 1, "entries": "x"}')
    code, _, err = run(["--root", root, "--compare-baseline", os.path.join(root, "bad.json")])
    assert code == 2 and "Traceback" not in err, err


def case_write_baseline_deterministic():
    root = new_repo({cls_path("Old"): LEGACY_SRC, cls_path("New"): "public class New {\n}\n"})
    path = os.path.join(root, "tools", "code", "baseline.json")
    assert run(["--root", root, "--write-baseline"])[0] == 0
    with open(path, "rb") as fh:
        first = fh.read()
    assert run(["--root", root, "--write-baseline"])[0] == 0
    with open(path, "rb") as fh:
        second = fh.read()
    assert first == second and first.endswith(b"\n") and b"\r" not in first
    data = json.loads(first)
    assert data["version"] == 1 and sorted(data) == ["entries", "version"], data
    assert data["entries"], data
    keys = [(e["path"], e["rule"], e["hash"]) for e in data["entries"]]
    assert keys == sorted(keys) and len(set(keys)) == len(keys), keys
    for e in data["entries"]:
        assert sorted(e) == ["hash", "path", "rule"], e


def case_write_baseline_refuses_symlink():
    root = new_repo({cls_path("Old"): LEGACY_SRC})
    target = tempfile.mkdtemp(dir=TMP)
    os.makedirs(os.path.join(root, "tools"))
    os.symlink(target, os.path.join(root, "tools", "code"))
    code, _, err = run(["--root", root, "--write-baseline"])
    assert code == 2 and "symlink" in err, err
    assert os.listdir(target) == []


def case_finding_key_occurrence_index():
    lines = ["a", "  update rows;", "b", "update rows;  "]
    f1 = {"rule": "apex-user-mode", "path": "p.cls", "line": 2}
    f2 = {"rule": "apex-user-mode", "path": "p.cls", "line": 4}
    k1 = cr().finding_key(f1, lines, [f1, f2])
    k2 = cr().finding_key(f2, lines, [f1, f2])
    assert k1["hash"].endswith("#0") and k2["hash"].endswith("#1"), (k1, k2)
    assert k1["hash"].split("#")[0] == k2["hash"].split("#")[0]
    assert sorted(k1) == ["hash", "path", "rule"]
    # Another rule's finding on identical text does not count toward n.
    other = {"rule": "apex-no-soql-dml-in-loop", "path": "p.cls", "line": 2}
    assert cr().finding_key(f2, lines, [other, f2])["hash"].endswith("#0")


def case_compliant_identical_line_does_not_shift_baseline():
    legacy = ("public with sharing class Q {\n    void a() {\n        List<Account> rows = [\n"
              "            SELECT Id FROM Account];\n    }\n}\n")
    root = new_repo({cls_path("Q"): legacy})
    assert run(["--root", root, "--write-baseline"])[0] == 0
    added = legacy.replace("{\n", "{\n    void b() {\n        List<Account> rows = [\n"
                           "            SELECT Id FROM Account WITH USER_MODE];\n    }\n", 1)
    write(os.path.join(root, cls_path("Q")), added)
    code, out, err = run(["--root", root])
    data = json.loads(out)
    assert code == 0 and data["new"] == [] and [f["line"] for f in data["baselined"]] == [7], (code, out, err)
    # finding_key without explicit findings computes them, with the same result.
    lines = added.split("\n")
    f = data["baselined"][0]
    assert cr().finding_key(f, lines)["hash"].endswith("#0")


def case_istest_method_in_non_test_class_keeps_user_mode():
    src = ("public with sharing class X {\n    @IsTest static void t() { }\n"
           "    void m() { insert x; }\n"
           "    List<Account> q() { return [SELECT Id FROM Account]; }\n}\n")
    assert only(src, "apex-user-mode") == [3, 4], rules_of(src)
    istest_field = ("public with sharing class X {\n    @TestVisible @IsTest static Integer k;\n"
                    "    class Inner {}\n    void m() { insert x; }\n}\n")
    assert only(istest_field, "apex-user-mode") == [4], rules_of(istest_field)


def case_build_index_apex_literals_contract():
    """check_rules reads build_index._APEX_LITERALS so comment detection and blank_apex agree."""
    bi = cr().build_index
    pat = getattr(bi, "_APEX_LITERALS", None)
    assert pat is not None and hasattr(pat, "finditer"), "build_index._APEX_LITERALS is gone"
    src = "a = 'x // y'; // note\n/* b\n c */ d"
    kinds = [m.group(0)[:2] for m in pat.finditer(src)]
    assert kinds == ["'x", "//", "/*"], kinds
    assert bi.blank_apex(src) == bi._blank(pat, src)


# ---- CLI ---------------------------------------------------------------------------------------

def case_cli_admitted_forms_from_repo():
    """The forms the guard patch admits in squad modes, run from the repo root."""
    base = os.path.join(TMP, "base_copy.json")
    shutil.copy(BASELINE, base)
    for args in ([], ["--from-config"], ["--compare-baseline", base],
                 ["--from-config", "--compare-baseline", base]):
        code, out, err = run(args)
        assert code == 0, (args, code, err, out[:400])
        data = json.loads(out)
        for key in ("findings", "new", "baselined", "notes"):
            assert key in data, (args, key)
        assert data["new"] == [], (args, data["new"])
        low = json.dumps(data["notes"]).lower()
        assert "narrow" in low and "miss" in low, data["notes"]
        assert not [w for w in BANNED if w in low], data["notes"]


def case_cli_bare_equals_from_config():
    a = run([])
    b = run(["--from-config"])
    assert a[0] == b[0] == 0 and json.loads(a[1]) == json.loads(b[1]), (a, b)
    assert json.loads(a[1])["findings"], "the bare form scanned nothing"


def case_cli_from_config_excludes_root():
    for args in (["--from-config", "--root", "."], ["--from-config", "--source-root", "demo/org"]):
        code, _, err = run(args)
        assert code == 2 and "Traceback" not in err, (args, err)
    code, _, err = run(["--no-such-flag"])
    assert code == 2


def case_committed_baseline_is_fresh():
    """The committed baseline equals a fresh write of the demo, byte for byte."""
    root = new_repo({})
    with open(os.path.join(root, ".ai-framework.json"), "w", encoding="utf-8") as fh:
        json.dump({"startingPoint": "existing", "sourceRoot": "demo/org"}, fh)
    shutil.copytree(DEMO_ORG, os.path.join(root, "demo", "org"))
    assert run(["--root", root, "--write-baseline"])[0] == 0
    with open(os.path.join(root, "tools", "code", "baseline.json"), "rb") as fh:
        fresh = fh.read()
    with open(BASELINE, "rb") as fh:
        committed = fh.read()
    assert fresh == committed, "committed baseline differs from a fresh run"


def case_demo_org_baseline_matches_signs_of_age():
    """What the demo run shows. The legacy classes are the only non-test classes with user-mode
    findings; the only other non-test findings are inner classes without a sharing keyword; test
    classes carry no findings (user mode is exempt there). Nothing here edits the demo."""
    code, out, err = run(["--from-config"])
    assert code == 0, err
    findings = json.loads(out)["findings"]
    assert findings

    def name(f):
        return os.path.basename(f["path"]).rsplit(".", 1)[0]

    non_test = [f for f in findings if not name(f).endswith("_Test")]
    legacy = sorted((name(f), f["rule"], f["line"]) for f in non_test if f["rule"] == "apex-user-mode")
    assert legacy == sorted([
        ("ContractTermService", "apex-user-mode", 40), ("ContractTermService", "apex-user-mode", 61),
        ("ContractTermService", "apex-user-mode", 71),
        ("LegacyCaseMerge", "apex-user-mode", 51),
        ("RenewalOutlookService", "apex-user-mode", 40), ("RenewalOutlookService", "apex-user-mode", 61),
        ("RenewalOutlookService", "apex-user-mode", 71)]), legacy
    for f in non_test:
        if f["rule"] == "apex-user-mode":
            continue
        assert f["rule"] == "apex-sharing", f
        raw = read(os.path.join(REPO, f["path"])).split("\n")[f["line"] - 1]
        assert raw.startswith((" ", "\t")) and name(f) not in LEGACY, f  # an inner class
    tests = [f for f in findings if name(f).endswith("_Test")]
    assert tests == [], tests  # apex-user-mode does not apply in @IsTest classes; nothing else fires
    assert not [f for f in findings if name(f) == "LegacyCaseMerge" and f["rule"] == "apex-sharing"]


def case_onboard_existing_writes_baseline():
    root = tempfile.mkdtemp(dir=TMP)
    shutil.copytree(DEMO_ORG, os.path.join(root, "org"))
    p = subprocess.run([sys.executable, ONBOARD, "--starting-point", "existing", "--source-root", "org",
                        "--owner-role", "Platform lead", "--root", root], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    path = os.path.join(root, "tools", "code", "baseline.json")
    assert os.path.isfile(path), os.listdir(root)
    code, out, err = run(["--root", root, "--source-root", "org"])
    data = json.loads(out)
    assert code == 0 and data["new"] == [], (code, err, out[:400])
    assert data["findings"] and len(data["baselined"]) == len(data["findings"]), out[:400]
    write(path, '{"version": 1, "entries": []}\n')
    code, out, _ = run(["--root", root, "--source-root", "org"])
    assert code == 1 and len(json.loads(out)["new"]) == len(data["findings"]), code
    green = tempfile.mkdtemp(dir=TMP)
    p = subprocess.run([sys.executable, ONBOARD, "--starting-point", "greenfield", "--source-root", "app",
                        "--root", green], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert not os.path.exists(os.path.join(green, "tools")), os.listdir(green)


def main():
    failures = 0
    names = [n for n, fn in sorted(globals().items()) if n.startswith("case_") and callable(fn)]
    for name in names:
        try:
            globals()[name]()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {name}: {exc!r}"[:600])
    print(f"{len(names) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
