#!/usr/bin/env python3
"""Parser tests for build_index.py. Each case builds its own temp tree; fixtures/ is not touched.

Run: python3 tools/index/test_parsers.py
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


def case_apex_field_ref_ignores_comment_and_string():
    idx = build_tree({
        f"{BASE}/Account/fields/Service_Level__c.field-meta.xml": FIELD_XML("Picklist"),
        f"{CLS}/Quiet.cls":
            "public with sharing class Quiet {\n"
            "    // reads Service_Level__c later\n"
            "    /* Service_Level__c */\n"
            "    String s = 'Service_Level__c';\n}\n",
        f"{CLS}/Loud.cls":
            "public with sharing class Loud {\n"
            "    // Service_Level__c in a comment first\n"
            "    String q = 'x'; Object v = [SELECT Service_Level__c FROM Account LIMIT 1];\n}\n",
    })
    assert not [e for e in idx["edges"] if e["from"] == "Quiet" and e["kind"] == "apexFieldRef"], idx["edges"]
    refs = [e for e in idx["edges"] if e["from"] == "Loud" and e["kind"] == "apexFieldRef"]
    assert len(refs) == 1 and refs[0]["to"] == "Account.Service_Level__c", refs
    assert refs[0]["evidence"].endswith("Loud.cls:3"), refs


def case_fixtures_risk_rating_consumers():
    fixtures = os.path.join(REPO, "fixtures")
    out = query_root(fixtures, "consumers", "Account.Risk_Rating__c")
    assert out["count"] == 5, out


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


def case_is_test_read_from_code_not_comments():
    idx = build_tree({
        f"{CLS}/Svc.cls": "// covered by the @IsTest class below\n"
                          "public with sharing class Svc {\n    String s = '@isTest';\n}\n",
        f"{CLS}/Svc_Test.cls": "@isTest\nprivate with sharing class Svc_Test {\n}\n",
        f"{CLS}/Upper_Test.cls": "@ISTEST\nprivate with sharing class Upper_Test {\n}\n",
    })
    assert idx["nodes"]["Svc"]["isTest"] is False, idx["nodes"]["Svc"]
    assert idx["nodes"]["Svc_Test"]["isTest"] is True
    assert idx["nodes"]["Upper_Test"]["isTest"] is True


FLOWS = "force-app/main/default/flows"
FLEXI = "force-app/main/default/flexipages"
PERMS = "force-app/main/default/permissionsets"


def FLOW_XML(actions, obj="Case"):
    acts = "".join(f'    <actionCalls>\n        <name>a{i}</name>\n        <actionName>{n}</actionName>\n'
                   f'        <actionType>{t}</actionType>\n    </actionCalls>\n'
                   for i, (n, t) in enumerate(actions))
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<Flow xmlns="{MD}">\n'
            f'{acts}'
            f'    <start>\n        <object>{obj}</object>\n    </start>\n'
            f'</Flow>\n')


def FLEXI_XML(components, fields, sobject="Case"):
    items = "".join(f'    <componentName>{c}</componentName>\n' for c in components)
    fi = "".join(f'    <fieldItem>{f}</fieldItem>\n' for f in fields)
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<FlexiPage xmlns="{MD}">\n'
            f'{items}{fi}'
            f'    <sobjectType>{sobject}</sobjectType>\n'
            f'</FlexiPage>\n')


def PERM_XML(fields, objects):
    fp = "".join(f'    <fieldPermissions>\n        <editable>{str(e).lower()}</editable>\n'
                 f'        <field>{f}</field>\n    </fieldPermissions>\n' for f, e in fields)
    op = "".join(f'    <objectPermissions>\n        <allowEdit>{str(e).lower()}</allowEdit>\n'
                 f'        <object>{o}</object>\n    </objectPermissions>\n' for o, e in objects)
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<PermissionSet xmlns="{MD}">\n{fp}{op}</PermissionSet>\n')


def _flow_tree(extra=None):
    files = {
        f"{FLOWS}/Case_Escalate_Premium.flow-meta.xml":
            FLOW_XML([("EscalationNotifier", "apex"), ("Notify_Owner", "emailAlert"),
                      ("Post_It", "chatterPost")]),
        f"{CLS}/EscalationNotifier.cls": "public with sharing class EscalationNotifier {}\n",
        f"{BASE}/Case/fields/Escalation_Level__c.field-meta.xml": FIELD_XML("Picklist"),
        f"{FLEXI}/Case_Agent_Console.flexipage-meta.xml":
            FLEXI_XML(["c:caseEscalationPanel", "force:highlightsPanel", "flexipage:richText",
                       "other:thing"],
                      ["Record.Escalation_Level__c", "Record.Ghost__c", "Record.Status"]),
        f"{PERMS}/Service_Agent.permissionset-meta.xml":
            PERM_XML([("Case.Escalation_Level__c", True), ("Case.Escalation_Level__c", False),
                      ("Case.Other__c", True)], [("Case", True), ("Account", False)]),
    }
    files.update(extra or {})
    return build_tree(files)


def case_flow_apex_action_and_trigger_object():
    idx = _flow_tree()
    e = edge(idx, "Case_Escalate_Premium", "EscalationNotifier", "flowApexAction")
    assert e and e["evidence"].endswith("Case_Escalate_Premium.flow-meta.xml:5"), e
    e = edge(idx, "Case_Escalate_Premium", "Case", "flowTriggerObject")
    assert e and e["evidence"].endswith(".flow-meta.xml:19"), e
    assert edge(idx, "Case_Escalate_Premium", "Case", "flowRef")  # existing edge stays


def case_flow_non_apex_actions_make_no_edge():
    idx = _flow_tree()
    acts = [e for e in idx["edges"] if e["kind"] == "flowApexAction"]
    assert [e["to"] for e in acts] == ["EscalationNotifier"], acts


def case_flexipage_edges():
    idx = _flow_tree()
    assert idx["nodes"]["Case_Agent_Console"]["type"] == "FlexiPage"
    assert edge(idx, "Case_Agent_Console", "caseEscalationPanel", "flexipageComponent")["evidence"].endswith(":3")
    assert edge(idx, "Case_Agent_Console", "Case", "flexipageObject")
    assert edge(idx, "Case_Agent_Console", "Case.Escalation_Level__c", "flexipageField")["evidence"].endswith(":7")


def case_non_c_namespace_component_ignored():
    idx = _flow_tree()
    comps = [e["to"] for e in idx["edges"] if e["from"] == "Case_Agent_Console" and e["kind"] == "flexipageComponent"]
    assert comps == ["caseEscalationPanel"], comps
    assert not [e for e in idx["edges"] if e["from"] == "Case_Agent_Console"
                and e["to"] in ("highlightsPanel", "force:highlightsPanel", "richText", "thing")]


def case_flexipage_field_only_when_field_exists():
    idx = _flow_tree()
    fields = [e["to"] for e in idx["edges"] if e["kind"] == "flexipageField"]
    assert fields == ["Case.Escalation_Level__c"], fields


def case_malformed_flexipage_marks_node():
    idx = _flow_tree({f"{FLEXI}/Bad.flexipage-meta.xml": "<FlexiPage>"})
    assert idx["nodes"]["Bad"]["parseError"] is True
    assert edge(idx, "Case_Agent_Console", "Case", "flexipageObject")


def case_permission_set_object_and_field_evidence():
    idx = _flow_tree()
    assert edge(idx, "Service_Agent", "Case", "objectPermission")["allowEdit"] is True
    assert edge(idx, "Service_Agent", "Account", "objectPermission")["allowEdit"] is False
    assert edge(idx, "Service_Agent", "Case", "objectPermission")["evidence"].endswith(".permissionset-meta.xml:17")
    assert edge(idx, "Service_Agent", "Case.Escalation_Level__c", "fieldPermission")["evidence"]


def case_permission_set_repeated_field_distinct_evidence():
    idx = _flow_tree()
    fps = [e for e in idx["edges"] if e["kind"] == "fieldPermission" and e["to"] == "Case.Escalation_Level__c"]
    lines = sorted(int(e["evidence"].rsplit(":", 1)[1]) for e in fps)
    assert lines == [5, 9], fps
    other = edge(idx, "Service_Agent", "Case.Other__c", "fieldPermission")
    assert other["evidence"].endswith(":13"), other


def _class_access_perm(entries):
    body = "".join(f'    <classAccesses>\n        <apexClass>{c}</apexClass>\n'
                   f'        <enabled>{str(en).lower()}</enabled>\n    </classAccesses>\n' for c, en in entries)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<PermissionSet xmlns="{MD}">\n{body}</PermissionSet>\n'


def case_permission_set_class_access_enabled_only():
    idx = build_tree({
        f"{CLS}/EscalationNotifier.cls": "public with sharing class EscalationNotifier {}\n",
        f"{CLS}/Other.cls": "public with sharing class Other {}\n",
        f"{PERMS}/Agent.permissionset-meta.xml":
            _class_access_perm([("EscalationNotifier", True), ("Other", False)]),
    })
    e = edge(idx, "Agent", "EscalationNotifier", "classAccess")
    assert e and e["evidence"].endswith("Agent.permissionset-meta.xml:4"), e
    assert not edge(idx, "Agent", "Other", "classAccess")


def case_permission_set_repeated_class_distinct_evidence():
    idx = build_tree({
        f"{CLS}/EscalationNotifier.cls": "public with sharing class EscalationNotifier {}\n",
        f"{PERMS}/Agent.permissionset-meta.xml":
            _class_access_perm([("EscalationNotifier", True), ("EscalationNotifier", True)]),
    })
    lines = sorted(int(e["evidence"].rsplit(":", 1)[1]) for e in idx["edges"] if e["kind"] == "classAccess")
    assert lines == [4, 8], lines


def case_index_version():
    assert build_index.INDEX_VERSION == "0.5.0"


def _picklist_xml(value_set):
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<CustomField xmlns="{MD}">\n'
            f'    <type>Picklist</type>\n'
            f'{value_set}'
            f'</CustomField>\n')


def case_picklist_values_parsed():
    xml = _picklist_xml(
        '    <valueSet>\n'
        '        <valueSetDefinition>\n'
        '            <value>\n'
        '                <fullName>Alpha</fullName>\n'
        '                <default>true</default>\n'
        '            </value>\n'
        '            <value>\n'
        '                <fullName>Beta</fullName>\n'
        '                <isActive>false</isActive>\n'
        '            </value>\n'
        '        </valueSetDefinition>\n'
        '    </valueSet>\n')
    idx = build_tree({f"{BASE}/Thing__c/fields/Pick__c.field-meta.xml": xml})
    node = idx["nodes"]["Thing__c.Pick__c"]
    assert node["picklistValues"] == [{"value": "Alpha", "active": True, "line": 7},
                                      {"value": "Beta", "active": False, "line": 11}], node
    assert "globalValueSet" not in node


def case_picklist_value_line_escaped_and_scoped():
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           f'<CustomField xmlns="{MD}">\n'
           '    <fullName>P__c</fullName>\n'
           '    <type>Picklist</type>\n'
           '    <valueSet>\n'
           '        <valueSetDefinition>\n'
           '            <value><fullName>A &amp; B</fullName></value>\n'
           '            <value><fullName>P__c</fullName><isActive>false</isActive></value>\n'
           '            <value><fullName>C</fullName></value>\n'
           '        </valueSetDefinition>\n'
           '    </valueSet>\n'
           '</CustomField>\n')
    node = build_tree({f"{BASE}/T__c/fields/P__c.field-meta.xml": xml})["nodes"]["T__c.P__c"]
    got = [(v["value"], v["line"], v["active"]) for v in node["picklistValues"]]
    assert got == [("A & B", 7, True), ("P__c", 8, False), ("C", 9, True)], got


def case_formula_flag_recorded():
    xml = (f'<CustomField xmlns="{MD}">\n    <formula>1 + 1</formula>\n    <type>Number</type>\n</CustomField>\n')
    node = build_tree({f"{BASE}/T__c/fields/F__c.field-meta.xml": xml})["nodes"]["T__c.F__c"]
    assert node.get("formula") is True


def case_global_value_set_recorded():
    xml = _picklist_xml('    <valueSet>\n        <valueSetName>Shared_Set</valueSetName>\n    </valueSet>\n')
    idx = build_tree({f"{BASE}/Thing__c/fields/Pick__c.field-meta.xml": xml})
    node = idx["nodes"]["Thing__c.Pick__c"]
    assert node["globalValueSet"] == "Shared_Set"
    assert "picklistValues" not in node


_TEMP_DIRS = []


def index_dir(files=None, root=None):
    """Build an index with the real CLI into a fresh temp dir and return that dir.

    Pass `files` (a temp tree is written, indexed, then removed) or `root` (an existing tree).
    """
    out = tempfile.mkdtemp()
    _TEMP_DIRS.append(out)
    tree = None
    try:
        if files is not None:
            tree = tempfile.mkdtemp()
            for rel_path, content in files.items():
                full = os.path.join(tree, rel_path)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w", encoding="utf-8") as fh:
                    fh.write(content)
            root = tree
        if root is None:
            raise ValueError("index_dir needs files or root")
        subprocess.run([sys.executable, os.path.join(HERE, "build_index.py"),
                        "--root", root, "--out", os.path.abspath(out)],
                       check=True, capture_output=True, text=True)
    finally:
        if tree:
            shutil.rmtree(tree, ignore_errors=True)
    return out


def _run_query(index, args):
    r = subprocess.run([sys.executable, os.path.join(HERE, "query.py"), *args, "--index", index],
                       check=True, capture_output=True, text=True)
    return json.loads(r.stdout)


def query(files, *args):
    return _run_query(index_dir(files=files), args)


def query_root(root, *args):
    return _run_query(index_dir(root=root), args)


def _hops_tree():
    # field <- CaseEscalationService <- caseEscalationPanel (lwc) <- Case_Agent_Console (page)
    return {
        f"{BASE}/Account/fields/Service_Level__c.field-meta.xml": FIELD_XML("Picklist"),
        f"{CLS}/CaseEscalationService.cls":
            "public with sharing class CaseEscalationService {\n"
            "    @AuraEnabled public static String level(Id i) { return Account.Service_Level__c; }\n}\n",
        f"{LWC}/caseEscalationPanel/caseEscalationPanel.js":
            "import level from '@salesforce/apex/CaseEscalationService.level';\n",
        f"{FLEXI}/Case_Agent_Console.flexipage-meta.xml": FLEXI_XML(["c:caseEscalationPanel"], []),
    }


def case_hops_three_reaches_page():
    out = query(_hops_tree(), "consumers", "Account.Service_Level__c", "--hops", "3")
    assert out["hops"] == 3, out
    assert any(c["api"] == "Case_Agent_Console" and c["hop"] == 3 for c in out["consumers"]), out
    two = query(_hops_tree(), "consumers", "Account.Service_Level__c")
    assert two["hops"] == 2 and not any(c["api"] == "Case_Agent_Console" for c in two["consumers"]), two


def case_hops_clamped():
    files = _hops_tree()
    idx = index_dir(files=files)
    assert _run_query(idx, ["consumers", "Account.Service_Level__c", "--hops", "9"])["hops"] == 3
    assert _run_query(idx, ["consumers", "Account.Service_Level__c", "--hops", "0"])["hops"] == 1
    assert _run_query(idx, ["consumers", "Account.Service_Level__c", "--hops", "-4"])["hops"] == 1


def case_cycle_terminates_without_duplicates():
    out = query({
        f"{CLS}/A.cls": "public with sharing class A {\n    B b;\n}\n",
        f"{CLS}/B.cls": "public with sharing class B {\n    A a;\n}\n",
    }, "consumers", "A", "--hops", "3")
    apis = [c["api"] for c in out["consumers"]]
    assert apis == ["B"], out


def case_query_root_runs_against_real_tree():
    fixtures = os.path.join(os.path.dirname(os.path.dirname(HERE)), "fixtures")
    out = query_root(fixtures, "exists", "Account.Risk_Rating__c")
    assert out["exists"] is True, out


REPO = os.path.dirname(os.path.dirname(HERE))
_qspec = importlib.util.spec_from_file_location("query_py", os.path.join(HERE, "query.py"))
query_py = importlib.util.module_from_spec(_qspec)
_qspec.loader.exec_module(query_py)


def build_root(rel_root):
    """Run build() in-process on a real directory under the repo root (no temp copy)."""
    nodes, edges = build_index.build(os.path.realpath(os.path.join(REPO, rel_root)), [])
    return {"nodes": nodes, "edges": edges}


def consumers_of(idx, api, hops):
    return query_py.consumers(idx, api, hops)


def case_demo_core_chain():
    idx = build_root("demo/org")
    c = {x["api"]: x["hop"] for x in consumers_of(idx, "Account.Service_Level__c", 3)}
    assert c["CaseEscalationService"] == 1
    assert c["CaseTriggerHandler"] == 2 and c["EscalationNotifier"] == 2 and c["caseEscalationPanel"] == 2
    assert c["CaseTrigger"] == 3 and c["Case_Escalate_Premium"] == 3 and c["Case_Agent_Console"] == 3
    assert all(n.get("parseError") is not True for n in idx["nodes"].values())


def case_sharing_read_from_code_not_comments():
    idx = index_dir(files={
        f"{CLS}/A.cls": "// without sharing was the old way\npublic with sharing class A {\n}\n",
        f"{CLS}/B.cls": "/* with sharing */\npublic class B {\n}\n",
        f"{CLS}/C.cls": "public with sharing class C {\n    String s = 'without sharing';\n}\n",
        f"{CLS}/D.cls": "public without sharing class D {\n}\n",
    })
    with open(os.path.join(idx, "metadata.json")) as fh:
        nodes = json.load(fh)["nodes"]
    assert nodes["A"]["sharing"] == "with sharing", nodes["A"]
    assert nodes["B"]["sharing"] == "inherited/unspecified", nodes["B"]
    assert nodes["C"]["sharing"] == "with sharing", nodes["C"]
    assert nodes["D"]["sharing"] == "without sharing", nodes["D"]


def case_demo_signs_of_age():
    idx = build_root("demo/org")
    assert idx["nodes"]["LegacyCaseMerge"]["sharing"] == "without sharing"
    assert idx["nodes"]["LegacyCaseMerge"]["apiVersion"] == "45.0"
    low = query_root("demo/org", "below-api-floor", "58")
    assert {"LegacyCaseMerge"} <= {i["api"] for i in low["items"]} and len(low["items"]) >= 3
    assert sorted(i["apiVersion"] for i in low["items"]) == ["45.0", "48.0", "52.0"], low
    # Each aged class is labelled, and uses plain SOQL and DML: user mode needs a newer API.
    for item in low["items"]:
        with open(os.path.join(REPO, item["path"]), encoding="utf-8") as fh:
            src = fh.read()
        assert src.startswith("// Deliberate sign of age"), item["api"]
        assert "USER_MODE" not in src, item["api"]
    # The legacy class is the only one that is not `with sharing`, and it touches no core component.
    classes = {k: v for k, v in idx["nodes"].items() if v["type"] == "ApexClass"}
    others = {k: v["sharing"] for k, v in classes.items() if k != "LegacyCaseMerge"}
    assert set(others.values()) == {"with sharing"}, {k: s for k, s in others.items() if s != "with sharing"}
    assert not [e for e in idx["edges"] if e["from"] == "LegacyCaseMerge" and e["to"].split(".")[0] in
                {"Case", "CaseEscalationService", "CaseTriggerHandler", "EscalationNotifier",
                 "CaseAssignmentService", "CaseAccountSummaryController"}]


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


atexit.register(lambda: [shutil.rmtree(d, ignore_errors=True) for d in _TEMP_DIRS])


if __name__ == "__main__":
    sys.exit(main())
