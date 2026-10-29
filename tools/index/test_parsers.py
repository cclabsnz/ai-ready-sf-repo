#!/usr/bin/env python3
"""Parser tests for build_index.py. Each case builds its own temp tree; fixtures/ is not touched.

Run: python3 tools/index/test_parsers.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("build_index", os.path.join(HERE, "build_index.py"))
build_index = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_index)

MD = "http://soap.sforce.com/2006/04/metadata"
BASE = "force-app/main/default/objects"


def FIELD_XML(ftype):
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<CustomField xmlns="{MD}">\n'
            f'    <type>{ftype}</type>\n'
            f'</CustomField>\n')


def VR_XML(formula, active="true"):
    # The formula sits on line 4.
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<ValidationRule xmlns="{MD}">\n'
            f'    <active>{active}</active>\n'
            f'    <errorConditionFormula>{formula}</errorConditionFormula>\n'
            f'    <errorMessage>Synthetic message</errorMessage>\n'
            f'</ValidationRule>\n')


def RT_XML(picklists):
    body = "".join(f'    <picklistValues>\n        <picklist>{p}</picklist>\n    </picklistValues>\n'
                   for p in picklists)
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<RecordType xmlns="{MD}">\n'
            f'    <active>true</active>\n'
            f'{body}'
            f'</RecordType>\n')


def build_tree(files):
    root = tempfile.mkdtemp()
    try:
        for rel_path, content in files.items():
            full = os.path.join(root, rel_path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(content)
        nodes, edges = build_index.build(root, [])
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return {"nodes": nodes, "edges": edges}


def edge(idx, frm, to, kind):
    for e in idx["edges"]:
        if e["from"] == frm and e["to"] == to and e["kind"] == kind:
            return e
    return None


def case_validation_rule_edges():
    idx = build_tree({
        f"{BASE}/Case/fields/Escalation_Level__c.field-meta.xml": FIELD_XML("Picklist"),
        f"{BASE}/Account/fields/Service_Level__c.field-meta.xml": FIELD_XML("Picklist"),
        f"{BASE}/Case/validationRules/Escalation_Needs_Level.validationRule-meta.xml":
            VR_XML("AND(IsEscalated, ISBLANK(TEXT(Escalation_Level__c)), "
                   "ISPICKVAL(Account.Service_Level__c, 'Premium'))"),
    })
    node = idx["nodes"]["Case.Escalation_Needs_Level"]
    assert node["type"] == "ValidationRule"
    assert node["active"] is True
    assert edge(idx, "Case.Escalation_Needs_Level", "Case", "validationRuleOf")
    e = edge(idx, "Case.Escalation_Needs_Level", "Case.Escalation_Level__c", "validationFieldRef")
    assert e["evidence"].endswith(":4"), e
    assert edge(idx, "Case.Escalation_Needs_Level", "Account.Service_Level__c", "validationFieldRef")


def case_validation_rule_ignores_missing_fields():
    idx = build_tree({
        f"{BASE}/Case/fields/Real__c.field-meta.xml": FIELD_XML("Text"),
        f"{BASE}/Case/validationRules/R.validationRule-meta.xml":
            VR_XML("OR(ISBLANK(Real__c), ISBLANK(Ghost__c), ISBLANK(Other.Ghost__c))", active="false"),
    })
    assert idx["nodes"]["Case.R"]["active"] is False
    assert edge(idx, "Case.R", "Case.Real__c", "validationFieldRef")
    assert not [e for e in idx["edges"] if e["kind"] == "validationFieldRef" and "Ghost" in e["to"]]


def case_record_type_edges():
    idx = build_tree({
        f"{BASE}/Case/fields/Escalation_Level__c.field-meta.xml": FIELD_XML("Picklist"),
        f"{BASE}/Case/recordTypes/Premium_Support.recordType-meta.xml": RT_XML(["Escalation_Level__c"]),
    })
    assert idx["nodes"]["Case.Premium_Support"]["type"] == "RecordType"
    assert edge(idx, "Case.Premium_Support", "Case", "recordTypeOf")
    e = edge(idx, "Case.Premium_Support", "Case.Escalation_Level__c", "recordTypePicklist")
    assert e and e["evidence"].endswith(":5"), e


def case_malformed_xml_marks_node_and_continues():
    idx = build_tree({
        f"{BASE}/Case/fields/Escalation_Level__c.field-meta.xml": FIELD_XML("Picklist"),
        f"{BASE}/Case/validationRules/Broken_Rule.validationRule-meta.xml": "<ValidationRule><active>",
        f"{BASE}/Case/recordTypes/Broken_RT.recordType-meta.xml": "not xml at all",
        f"{BASE}/Case/fields/Broken_Field__c.field-meta.xml": "",
    })
    assert idx["nodes"]["Case.Broken_Rule"]["parseError"] is True
    assert idx["nodes"]["Case.Broken_RT"]["parseError"] is True
    assert idx["nodes"]["Case.Broken_Field__c"]["parseError"] is True
    assert "Case.Escalation_Level__c" in idx["nodes"]
    assert not idx["nodes"]["Case.Escalation_Level__c"].get("parseError")


def _case_rule_tree(formula, extra=None):
    files = {
        f"{BASE}/Case/fields/Escalation_Level__c.field-meta.xml": FIELD_XML("Picklist"),
        f"{BASE}/Account/fields/Service_Level__c.field-meta.xml": FIELD_XML("Picklist"),
        f"{BASE}/Case/validationRules/R.validationRule-meta.xml": VR_XML(formula),
    }
    files.update(extra or {})
    return build_tree(files)


def _field_refs(idx):
    return [e for e in idx["edges"] if e["kind"] == "validationFieldRef"]


def case_formula_literals_and_comments_make_no_edges():
    for formula in ("ISPICKVAL(Status, 'Escalation_Level__c')",
                    'ISPICKVAL(Status, "Escalation_Level__c")',
                    "ISPICKVAL(Status, 'it\\'s Escalation_Level__c')",
                    "IsEscalated /* old: Escalation_Level__c */",
                    "IsEscalated /* a\nEscalation_Level__c */"):
        idx = _case_rule_tree(formula)
        assert not _field_refs(idx), (formula, _field_refs(idx))
    # a real token after a literal and a comment is still found, on the right line
    idx = _case_rule_tree("AND('x__c', /* y__c */\nISBLANK(Escalation_Level__c))")
    e = edge(idx, "Case.R", "Case.Escalation_Level__c", "validationFieldRef")
    assert e and e["evidence"].endswith(":5"), e


def case_formula_non_object_qualifier_makes_no_edge():
    idx = _case_rule_tree("ISBLANK(Account__r.Service_Level__c)")
    assert not _field_refs(idx), _field_refs(idx)


def case_formula_substring_makes_no_edge():
    idx = _case_rule_tree("ISBLANK(Foo_Escalation_Level__c)")
    assert not _field_refs(idx), _field_refs(idx)


def case_formula_multiline_evidence_line():
    idx = _case_rule_tree("AND(\n  IsEscalated,\n  ISBLANK(TEXT(Escalation_Level__c)))")
    e = edge(idx, "Case.R", "Case.Escalation_Level__c", "validationFieldRef")
    assert e and e["evidence"].endswith(":6"), e


def case_object_edge_evidence_lines():
    idx = build_tree({
        f"{BASE}/Case/validationRules/R.validationRule-meta.xml": VR_XML("TRUE"),
        f"{BASE}/Case/recordTypes/T.recordType-meta.xml": RT_XML([]),
    })
    assert edge(idx, "Case.R", "Case", "validationRuleOf")["evidence"].endswith("R.validationRule-meta.xml:2")
    assert edge(idx, "Case.T", "Case", "recordTypeOf")["evidence"].endswith("T.recordType-meta.xml:2")


def case_record_type_picklist_without_field_makes_no_edge():
    idx = build_tree({
        f"{BASE}/Case/recordTypes/T.recordType-meta.xml": RT_XML(["Status"]),
    })
    assert not [e for e in idx["edges"] if e["kind"] == "recordTypePicklist"]


def case_malformed_flow_and_permset_mark_node_and_continue():
    idx = build_tree({
        "force-app/main/default/flows/Bad_Flow.flow-meta.xml": "<Flow><status>",
        "force-app/main/default/permissionsets/Bad_Perms.permissionset-meta.xml": "<<<",
        f"{BASE}/Case/fields/Escalation_Level__c.field-meta.xml": FIELD_XML("Picklist"),
    })
    assert idx["nodes"]["Bad_Flow"]["parseError"] is True
    assert idx["nodes"]["Bad_Perms"]["parseError"] is True
    assert "Case.Escalation_Level__c" in idx["nodes"]


def case_line_of():
    f = build_index.line_of
    assert f("a\nb\nc", "c") == 3
    assert f("x\nx\nx", "x", 2) == 2
    assert f("a\nb", "zzz") == 1


CLS = "force-app/main/default/classes"
TRG = "force-app/main/default/triggers"
LWC = "force-app/main/default/lwc"


def _apex_tree(extra=None):
    files = {
        f"{TRG}/CaseTrigger.trigger":
            "trigger CaseTrigger on Case (before insert) {\n    CaseTriggerHandler.run(Trigger.new);\n}\n",
        f"{CLS}/CaseTriggerHandler.cls":
            "public with sharing class CaseTriggerHandler {\n"
            "    public static void run(List<Case> cs) {\n"
            "        CaseEscalationService.escalate(cs);\n"
            "    }\n}\n",
        f"{CLS}/CaseEscalationService.cls":
            "public with sharing class CaseEscalationService {\n"
            "    public static void escalate(List<Case> cs) {}\n"
            "    @AuraEnabled(cacheable=true)\n"
            "    public static String getEscalationState(Id caseId) { return null; }\n"
            "    public static String notExposed() { return null; }\n"
            "}\n",
        f"{CLS}/EscalationNotifier.cls":
            "public with sharing class EscalationNotifier {\n"
            "    @InvocableMethod(label='Notify')\n"
            "    public static void notify(List<Id> ids) {}\n}\n",
        f"{LWC}/caseEscalationPanel/caseEscalationPanel.js":
            "import getState from '@salesforce/apex/CaseEscalationService.getEscalationState';\n"
            "import nope from '@salesforce/apex/CaseEscalationService.notExposed';\n"
            "import ghost from '@salesforce/apex/MissingClass.whatever';\n",
    }
    files.update(extra or {})
    return build_tree(files)


def case_trigger_on_object():
    idx = _apex_tree()
    assert edge(idx, "CaseTrigger", "Case", "triggerOn")["evidence"].endswith("CaseTrigger.trigger:1")
    assert idx["nodes"]["Case"] == {"type": "CustomObject", "path": None, "namespace": None}


def case_trigger_on_keeps_real_object_node():
    idx = _apex_tree({f"{BASE}/Case/Case.object-meta.xml": "<CustomObject/>"})
    assert idx["nodes"]["Case"]["path"].endswith("Case.object-meta.xml")
    assert edge(idx, "CaseTrigger", "Case", "triggerOn")


def case_trigger_on_ignores_comment_and_evidence_line():
    idx = build_tree({f"{TRG}/T.trigger":
                      "// trigger Fake on Ghost (before insert)\n/* a\n b */\ntrigger T on Account (after update) {}\n"})
    assert edge(idx, "T", "Account", "triggerOn")["evidence"].endswith("T.trigger:4")
    assert not edge(idx, "T", "Ghost", "triggerOn")


def case_class_to_class():
    idx = _apex_tree()
    assert edge(idx, "CaseTrigger", "CaseTriggerHandler", "apexClassRef")["evidence"].endswith("CaseTrigger.trigger:2")
    assert edge(idx, "CaseTriggerHandler", "CaseEscalationService", "apexClassRef")["evidence"].endswith(
        "CaseTriggerHandler.cls:3")
    assert not edge(idx, "CaseEscalationService", "CaseTriggerHandler", "apexClassRef")


def case_class_ref_ignores_comment_string_substring_self():
    idx = _apex_tree({
        f"{CLS}/Quiet.cls":
            "public with sharing class Quiet {\n"
            "    // CaseEscalationService\n"
            "    /* CaseTriggerHandler\n       EscalationNotifier */\n"
            "    String s = 'CaseEscalationService';\n"
            "    String t = 'it\\'s CaseTriggerHandler';\n"
            "    Object o = MyCaseEscalationService.x + CaseEscalationService_Test.y + CaseEscalationServiceX.z;\n"
            "    Quiet q;\n}\n",
    })
    refs = [e for e in idx["edges"] if e["kind"] == "apexClassRef" and e["from"] == "Quiet"]
    assert not refs, refs


def case_class_ref_real_token_after_comment_and_string_one_edge_first_line():
    idx = _apex_tree({
        f"{CLS}/Loud.cls":
            "public with sharing class Loud {\n"
            "    String s = 'x'; /* a\n b */ // c\n"
            "    void m() {\n        CaseEscalationService.escalate(null);\n        CaseEscalationService.escalate(null);\n    }\n}\n",
    })
    refs = [e for e in idx["edges"] if e["kind"] == "apexClassRef" and e["from"] == "Loud"]
    assert len(refs) == 1 and refs[0]["to"] == "CaseEscalationService", refs
    assert refs[0]["evidence"].endswith("Loud.cls:5"), refs


def case_class_ref_url_in_string_does_not_hide_code():
    idx = _apex_tree({
        f"{CLS}/Url.cls":
            "public with sharing class Url {\n    String u = 'http://x'; CaseEscalationService s;\n}\n",
    })
    assert edge(idx, "Url", "CaseEscalationService", "apexClassRef")["evidence"].endswith("Url.cls:2")


def case_invocable_and_aura_enabled():
    idx = _apex_tree()
    assert idx["nodes"]["EscalationNotifier"]["invocable"] is True
    assert idx["nodes"]["CaseEscalationService"]["invocable"] is False
    assert idx["nodes"]["CaseEscalationService"]["auraEnabledMethods"] == ["getEscalationState"]
    assert idx["nodes"]["EscalationNotifier"]["auraEnabledMethods"] == []
    e = edge(idx, "caseEscalationPanel", "CaseEscalationService", "lwcApexImport")
    assert e["method"] == "getEscalationState" and e["auraEnabled"] is True, e


def case_lwc_import_non_aura_and_unknown_class():
    idx = _apex_tree()
    lwc = [e for e in idx["edges"] if e["kind"] == "lwcApexImport"]
    by_method = {e["method"]: e for e in lwc}
    assert by_method["notExposed"]["auraEnabled"] is False
    assert by_method["notExposed"]["to"] == "CaseEscalationService"  # still the class, hop depth unchanged
    assert by_method["whatever"]["to"] == "MissingClass" and by_method["whatever"]["auraEnabled"] is None


def case_aura_enabled_forms():
    idx = build_tree({
        f"{CLS}/A.cls":
            "public with sharing class A {\n"
            "    @AuraEnabled public String n;\n"
            "    public static W build() { return null; }\n"
            "    @AuraEnabled(cacheable=true) public static String getX() { return null; }\n"
            "    @AuraEnabled\n    @TestVisible\n    public static Foo.Bar getY() { return null; }\n"
            "    @AuraEnabled public static String[] getZ() { return null; }\n"
            "    @AuraEnabled(cacheable=true)\n    global static List<Map<String,Object>> getW() { return null; }\n"
            "    @AuraEnabled public static Database.QueryLocator getQ() { return null; }\n}\n",
    })
    assert idx["nodes"]["A"]["auraEnabledMethods"] == ["getQ", "getW", "getX", "getY", "getZ"], idx["nodes"]["A"]


def case_trigger_header_forms():
    idx = build_tree({
        f"{TRG}/T1.trigger": "trigger T1 on Case(before insert) {}\n",
        f"{TRG}/T2.trigger": "trigger T2\n  on\n  Case\n  (before insert) {}\n",
        f"{CLS}/Eof.cls": "public with sharing class Eof {}\n// CaseTriggerHandler",
        f"{CLS}/CaseTriggerHandler.cls": "public with sharing class CaseTriggerHandler {}\n",
    })
    assert edge(idx, "T1", "Case", "triggerOn")
    assert edge(idx, "T2", "Case", "triggerOn")["evidence"].endswith("T2.trigger:1")
    assert not edge(idx, "Eof", "CaseTriggerHandler", "apexClassRef")


def case_commented_out_annotations_do_not_count():
    idx = build_tree({
        f"{CLS}/C.cls":
            "public with sharing class C {\n"
            "    // @InvocableMethod\n"
            "    /* @AuraEnabled\n    public static String old() {} */\n"
            "    public static String live() { return 'x'; }\n}\n",
    })
    assert idx["nodes"]["C"]["invocable"] is False
    assert idx["nodes"]["C"]["auraEnabledMethods"] == []


def case_index_version():
    assert build_index.INDEX_VERSION == "0.3.0"


def main():
    failures = 0
    for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("case_") and callable(f)):
        try:
            fn()
            print(f"[PASS] {name}")
        except Exception as exc:  # AssertionError, KeyError, AttributeError, ...
            failures += 1
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
    print(f"{'PASS' if not failures else 'FAIL'}: {failures} failing case(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
