#!/usr/bin/env python3
"""Seeded generator for the demo org's Sales/Service filler metadata.

Adds realistic Account, Contact, Lead and Opportunity build-up under <out>/force-app/main/default/ so
the demo org has hundreds of files. The filler is isolated from the hand-written story core: it never
references a core API name and never touches Case or Entitlement, so the answer keys stay exact.

Run: python3 tools/demo/generate_filler.py --seed 2026 --out demo/org [--check]

Writes only files that do not exist. A target that exists with different content is never touched:
the run exits 2 naming it. Identical content is skipped silently. --check writes nothing and exits 1
if any file is missing or differs.
"""
import argparse
import os
import random
import re
import sys
from xml.sax.saxutils import escape

DEFAULT_SEED = 2026
API_VERSION = "62.0"  # default; apex_class / apex_meta take a per-class version
# Deliberate signs of age: service topics whose service class (not its test) is pinned to an old API
# version. Chosen by topic name, so the choice never depends on the random draw.
LEGACY_API_VERSIONS = {"RenewalOutlook": "48.0", "ContractTerm": "52.0"}
BASE = "force-app/main/default"
MD = "http://soap.sforce.com/2006/04/metadata"
HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n'
OBJECTS = ["Account", "Contact", "Lead", "Opportunity"]

# Filler field pools, in a fixed order. (api name, type, picklist values). Every name is unique
# across objects and none collides with a core field.
FIELDS = {
    "Account": [
        ("Customer_Segment__c", "Picklist", ["SMB", "Mid-Market", "Enterprise"]),
        ("Partner_Tier__c", "Picklist", ["None", "Silver", "Gold"]),
        ("Health_Score__c", "Number", None),
        ("Seat_Count__c", "Number", None),
        ("Expansion_Potential__c", "Currency", None),
        ("Churn_Risk_Pct__c", "Percent", None),
        ("Health_Band__c", "Text", None),
        ("Account_Planning_Band__c", "Text", None),
        ("Account_Review_Status__c", "Text", None),
        ("Onboarding_Notes__c", "Text", None),
        ("Billing_Region_Code__c", "Text", None),
        ("Account_Plan_Summary__c", "Text", None),
        ("Last_Review_Date__c", "Date", None),
        ("Renewal_Date__c", "Date", None),
        ("Strategic_Account__c", "Checkbox", None),
    ],
    "Contact": [
        ("Preferred_Channel__c", "Picklist", ["Email", "Phone", "Chat"]),
        ("Influence_Level__c", "Picklist", ["Low", "Medium", "High"]),
        ("Engagement_Score__c", "Number", None),
        ("Meeting_Cadence_Days__c", "Number", None),
        ("Event_Spend__c", "Currency", None),
        ("Response_Rate_Pct__c", "Percent", None),
        ("Engagement_Band__c", "Text", None),
        ("Outreach_Priority__c", "Text", None),
        ("Contact_Review_Status__c", "Text", None),
        ("Contact_Notes__c", "Text", None),
        ("Role_Summary__c", "Text", None),
        ("Time_Zone_Label__c", "Text", None),
        ("Last_Touch_Date__c", "Date", None),
        ("Newsletter_Opt_In__c", "Checkbox", None),
        ("Decision_Maker__c", "Checkbox", None),
    ],
    "Lead": [
        ("Nurture_Stage__c", "Picklist", ["New", "Engaged", "Warm", "Hot"]),
        ("Routing_Region__c", "Picklist", ["North", "South", "East", "West"]),
        ("Lead_Fit_Score__c", "Number", None),
        ("Intent_Score__c", "Number", None),
        ("Budget_Estimate__c", "Currency", None),
        ("Conversion_Likelihood_Pct__c", "Percent", None),
        ("Lead_Tier_Label__c", "Text", None),
        ("Follow_Up_Priority__c", "Text", None),
        ("Lead_Review_Status__c", "Text", None),
        ("Campaign_Source_Detail__c", "Text", None),
        ("Qualification_Notes__c", "Text", None),
        ("Referral_Code__c", "Text", None),
        ("Follow_Up_Date__c", "Date", None),
        ("Trial_Start_Date__c", "Date", None),
        ("Marketing_Qualified__c", "Checkbox", None),
    ],
    "Opportunity": [
        ("Discount_Approval_Status__c", "Picklist", ["Not Required", "Pending", "Approved", "Rejected"]),
        ("Procurement_Stage__c", "Picklist", ["Not Started", "In Review", "Cleared"]),
        ("Deal_Risk_Score__c", "Number", None),
        ("Contract_Term_Months__c", "Number", None),
        ("Quote_Total__c", "Currency", None),
        ("Forecast_Adjustment__c", "Currency", None),
        ("Discount_Pct__c", "Percent", None),
        ("Risk_Band__c", "Text", None),
        ("Review_Status_Label__c", "Text", None),
        ("Opportunity_Review_Status__c", "Text", None),
        ("Competitor_Notes__c", "Text", None),
        ("Next_Step_Detail__c", "Text", None),
        ("Pricing_Exception_Reason__c", "Text", None),
        ("Legal_Review_Date__c", "Date", None),
        ("Executive_Sponsor_Engaged__c", "Checkbox", None),
    ],
}
NUMERIC = ("Number", "Currency", "Percent")

# Service topics per object. Class name = topic + suffix; the topic also names the LWC.
# (topic, field the band is computed from, text field the band is stamped into) per object.
SERVICES = {
    "Account": [
        ("AccountPlanning", "Health_Score__c", "Account_Planning_Band__c"),
        ("SegmentAssignment", "Seat_Count__c", "Account_Planning_Band__c"),
        ("RenewalOutlook", "Health_Score__c", "Health_Band__c"),
        ("ChurnWatch", "Churn_Risk_Pct__c", "Health_Band__c"),
        ("ExpansionTarget", "Expansion_Potential__c", "Account_Planning_Band__c"),
        ("SeatUsage", "Seat_Count__c", "Health_Band__c"),
        ("OnboardingProgress", "Health_Score__c", "Health_Band__c"),
        ("PartnerTiering", "Expansion_Potential__c", "Account_Planning_Band__c"),
        ("RegionalCoverage", "Seat_Count__c", "Account_Planning_Band__c"),
        ("ReviewCadence", "Health_Score__c", "Health_Band__c"),
    ],
    "Contact": [
        ("ContactEngagement", "Engagement_Score__c", "Engagement_Band__c"),
        ("ChannelPreference", "Event_Spend__c", "Outreach_Priority__c"),
        ("InfluenceMapping", "Engagement_Score__c", "Engagement_Band__c"),
        ("MeetingCadence", "Meeting_Cadence_Days__c", "Outreach_Priority__c"),
        ("OptInHygiene", "Response_Rate_Pct__c", "Outreach_Priority__c"),
        ("DecisionMaker", "Engagement_Score__c", "Engagement_Band__c"),
        ("EventFollowUp", "Event_Spend__c", "Outreach_Priority__c"),
        ("ResponseTracking", "Response_Rate_Pct__c", "Engagement_Band__c"),
    ],
    "Lead": [
        ("LeadScoring", "Lead_Fit_Score__c", "Lead_Tier_Label__c"),
        ("LeadRouting", "Intent_Score__c", "Follow_Up_Priority__c"),
        ("NurtureCadence", "Intent_Score__c", "Follow_Up_Priority__c"),
        ("TrialFollowUp", "Intent_Score__c", "Follow_Up_Priority__c"),
        ("IntentSignal", "Intent_Score__c", "Lead_Tier_Label__c"),
        ("CampaignAttribution", "Budget_Estimate__c", "Lead_Tier_Label__c"),
        ("FitAssessment", "Lead_Fit_Score__c", "Lead_Tier_Label__c"),
        ("ConversionForecast", "Conversion_Likelihood_Pct__c", "Lead_Tier_Label__c"),
        ("ReferralTracking", "Budget_Estimate__c", "Follow_Up_Priority__c"),
        ("QualificationReview", "Lead_Fit_Score__c", "Follow_Up_Priority__c"),
    ],
    "Opportunity": [
        ("QuoteApproval", "Quote_Total__c", "Review_Status_Label__c"),
        ("DiscountGuard", "Discount_Pct__c", "Review_Status_Label__c"),
        ("PipelineHealth", "Deal_Risk_Score__c", "Risk_Band__c"),
        ("DealRisk", "Deal_Risk_Score__c", "Risk_Band__c"),
        ("ContractTerm", "Contract_Term_Months__c", "Review_Status_Label__c"),
        ("ForecastAdjust", "Forecast_Adjustment__c", "Risk_Band__c"),
        ("PricingException", "Discount_Pct__c", "Review_Status_Label__c"),
        ("ProcurementTrack", "Quote_Total__c", "Review_Status_Label__c"),
        ("SponsorEngagement", "Deal_Risk_Score__c", "Risk_Band__c"),
        ("CompetitorWatch", "Deal_Risk_Score__c", "Risk_Band__c"),
        ("LegalReview", "Contract_Term_Months__c", "Review_Status_Label__c"),
        ("StageAging", "Quote_Total__c", "Risk_Band__c"),
    ],
}
# The text field record-triggered flows stamp a review status into. Never a service stamp field
# (SERVICES): a before-save flow firing in a service test would overwrite the band the test asserts.
FLOW_STATUS_FIELD = {
    "Account": "Account_Review_Status__c", "Contact": "Contact_Review_Status__c",
    "Lead": "Lead_Review_Status__c", "Opportunity": "Opportunity_Review_Status__c",
}
# Number and Currency fields that can never be negative; Forecast_Adjustment__c can, so it has no rule.
NON_NEGATIVE = {"Seat_Count__c", "Meeting_Cadence_Days__c", "Event_Spend__c", "Budget_Estimate__c",
                "Expansion_Potential__c", "Quote_Total__c", "Contract_Term_Months__c"}


def rule_kind(name, ftype):
    """The validation rule a field gets, if any: 'range' (0-100, Percent and scores), 'nonneg', 'date'."""
    if ftype == "Date":
        return "date"
    if ftype == "Percent" or (ftype == "Number" and name.endswith("_Score__c")):
        return "range"
    if name in NON_NEGATIVE:
        return "nonneg"
    return None


SUFFIXES = ["Service", "Service", "Evaluator"]
LWC_SUFFIXES = ["Badge", "Panel", "Card"]
LWC_COUNT = 28

FLOW_BASES = {
    "Account": ["Segment_Default", "Churn_Flag", "Plan_Review_Stamp", "Seat_Flag", "Renewal_Stamp", "Coverage_Check"],
    "Contact": ["Engagement_Flag", "Channel_Default", "Cadence_Stamp", "Response_Flag", "Influence_Check", "Opt_In_Stamp"],
    "Lead": ["Score_Stamp", "Nurture_Default", "Intent_Flag", "Fit_Review", "Follow_Up_Flag", "Region_Default"],
    "Opportunity": ["Stage_Guard", "Discount_Flag", "Risk_Stamp", "Term_Default", "Sponsor_Check", "Pricing_Review"],
}
FLOW_STAMPS = ["Needs review", "Flagged", "Default applied", "Pending check"]
SCREEN_FLOWS = [
    ("Lead", "Lead_Qualification_Screen"), ("Lead", "Lead_Nurture_Screen"),
    ("Account", "Account_Plan_Screen"), ("Account", "Account_Review_Screen"),
    ("Opportunity", "Opportunity_Discount_Request_Screen"), ("Opportunity", "Opportunity_Handoff_Screen"),
    ("Contact", "Contact_Preference_Screen"), ("Contact", "Contact_Update_Screen"),
]
RULES_PER_OBJECT = 5

PERMSETS = {
    "Account": "Account_Planning_Access",
    "Contact": "Contact_Engagement_Access",
    "Lead": "Lead_Management_Access",
    "Opportunity": "Opportunity_Pipeline_Access",
}

# Minimum fields to insert one record of each object in a test.
REQUIRED_INIT = {
    "Account": "Name = 'Sample Account'",
    "Contact": "LastName = 'Sample Contact'",
    "Lead": "LastName = 'Sample Lead', Company = 'Sample Company'",
    "Opportunity": "Name = 'Sample Opportunity', StageName = 'Prospecting', CloseDate = Date.today().addDays(30)",
}


def words(name):
    """'QuoteApproval' -> 'quote approval'; 'Discount_Pct__c' -> 'discount pct'."""
    if name.endswith("__c"):
        name = name[:-3]
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).replace("_", " ").lower()


def label(name):
    return " ".join(w.capitalize() if w.islower() else w for w in words(name).split())


def fill(template, **kw):
    for k, v in kw.items():
        template = template.replace("@@" + k + "@@", str(v))
    return template


def lower_first(s):
    return s[:1].lower() + s[1:]


# ---------------------------------------------------------------- fields

def field_xml(obj, name, ftype, values):
    lab = label(name)
    out = [HEAD, f'<CustomField xmlns="{MD}">\n',
           f"    <fullName>{name}</fullName>\n"]
    if ftype == "Checkbox":
        out.append("    <defaultValue>false</defaultValue>\n")
    out.append(f"    <description>{escape(lab)} on {obj} records, kept for pipeline and engagement reporting.</description>\n")
    out.append("    <externalId>false</externalId>\n")
    out.append(f"    <label>{escape(lab)}</label>\n")
    if ftype == "Text":
        out.append("    <length>80</length>\n")
    if ftype in NUMERIC:
        out.append(f"    <precision>{5 if ftype == 'Percent' else 18}</precision>\n")
    if ftype != "Checkbox":
        out.append("    <required>false</required>\n")
    if ftype in NUMERIC:
        out.append("    <scale>2</scale>\n")
    out.append("    <trackHistory>false</trackHistory>\n")
    out.append("    <trackTrending>false</trackTrending>\n")
    out.append(f"    <type>{ftype}</type>\n")
    if ftype == "Picklist":
        out.append("    <valueSet>\n        <restricted>true</restricted>\n        <valueSetDefinition>\n"
                   "            <sorted>false</sorted>\n")
        for i, v in enumerate(values):
            out.append("            <value>\n"
                       f"                <fullName>{escape(v)}</fullName>\n"
                       f"                <default>{'true' if i == 0 else 'false'}</default>\n"
                       f"                <label>{escape(v)}</label>\n"
                       "            </value>\n")
        out.append("        </valueSetDefinition>\n    </valueSet>\n")
    out.append("</CustomField>\n")
    return "".join(out)


# ---------------------------------------------------------------- apex

def apex_meta(api_version=API_VERSION):
    return (HEAD + f'<ApexClass xmlns="{MD}">\n'
            f"    <apiVersion>{api_version}</apiVersion>\n"
            "    <status>Active</status>\n</ApexClass>\n")


SERVICE_TEMPLATE = """/**
 * Bands @@OBJ@@ records by @@NUMWORDS@@ for @@TOPICWORDS@@.
 *
 * Records at or above HIGH_THRESHOLD are High, at or above MEDIUM_THRESHOLD are Medium, anything
 * lower is Low and a blank value is None. stampBands writes the band to @@TXT@@, and
 * bandForRecord feeds @@LWCREF@@.
 */
public with sharing class @@CLS@@ {

    public static final Decimal HIGH_THRESHOLD = @@HIGH@@;
    public static final Decimal MEDIUM_THRESHOLD = @@MED@@;
    public static final String BAND_HIGH = 'High';
    public static final String BAND_MEDIUM = 'Medium';
    public static final String BAND_LOW = 'Low';
    public static final String BAND_NONE = 'None';

    /** The band for a value. Pure, so the rule is testable without records. */
    public static String bandFor(Decimal value) {
        if (value == null) {
            return BAND_NONE;
        }
        if (value >= HIGH_THRESHOLD) {
            return BAND_HIGH;
        }
        if (value >= MEDIUM_THRESHOLD) {
            return BAND_MEDIUM;
        }
        return BAND_LOW;
    }

    /** Bands for the given records, read in one query whatever the batch size. */
    public static Map<Id, String> bandsFor(Set<Id> recordIds) {
        Map<Id, String> bands = new Map<Id, String>();
        if (recordIds == null || recordIds.isEmpty()) {
            return bands;
        }
        List<@@OBJ@@> rows = [
            SELECT Id, @@NUM@@
            FROM @@OBJ@@
            WHERE Id IN :recordIds
            WITH USER_MODE
        ];
        for (@@OBJ@@ row : rows) {
            bands.put(row.Id, bandFor(row.@@NUM@@));
        }
        return bands;
    }

    /** Writes the band to @@TXT@@ on the records whose stored band differs. */
    public static void stampBands(List<@@OBJ@@> rows) {
        List<@@OBJ@@> changed = new List<@@OBJ@@>();
        for (@@OBJ@@ row : rows) {
            String band = bandFor(row.@@NUM@@);
            if (row.@@TXT@@ != band) {
                changed.add(new @@OBJ@@(Id = row.Id, @@TXT@@ = band));
            }
        }
        if (!changed.isEmpty()) {
            Database.update(changed, AccessLevel.USER_MODE);
        }
    }

    /**
     * The band of one record for @@LWCREF@@. Null when the record is not visible.
     * cacheable=true: the client may show a stale band until the record page refreshes.
     */
    @AuraEnabled(cacheable=true)
    public static String bandForRecord(Id recordId) {
        List<@@OBJ@@> rows = [
            SELECT Id, @@NUM@@
            FROM @@OBJ@@
            WHERE Id = :recordId
            WITH USER_MODE
            LIMIT 1
        ];
        return rows.isEmpty() ? null : bandFor(rows[0].@@NUM@@);
    }
}
"""

TEST_TEMPLATE = """@IsTest
private with sharing class @@CLS@@_Test {

    /**
     * A standard user holding the @@PERMSET@@ permission set.
     * Fields deployed through the Metadata API grant field access to nobody, so the record work
     * below runs as this user.
     */
    private static User areaUser() {
        Profile p = [SELECT Id FROM Profile WHERE Name = 'Standard User' LIMIT 1];
        String unique = String.valueOf(Datetime.now().getTime()) + String.valueOf(Crypto.getRandomInteger()).replace('-', '');
        User u = new User(
            ProfileId = p.Id,
            LastName = 'Sample Planner',
            Alias = 'smplusr',
            Email = 'sample.planner@example.com',
            Username = 'sample.planner.' + unique + '@example.com',
            TimeZoneSidKey = 'Pacific/Auckland',
            LocaleSidKey = 'en_NZ',
            EmailEncodingKey = 'UTF-8',
            LanguageLocaleKey = 'en_US'
        );
        PermissionSet ps = [SELECT Id FROM PermissionSet WHERE Name = '@@PERMSET@@' LIMIT 1];
        // Setup objects in their own runAs block, so the record inserts that follow do not raise
        // MIXED_DML_OPERATION.
        System.runAs(new User(Id = UserInfo.getUserId())) {
            insert u;
            insert new PermissionSetAssignment(AssigneeId = u.Id, PermissionSetId = ps.Id);
        }
        return u;
    }

    private static @@OBJ@@ sampleRecord(Decimal value) {
        @@OBJ@@ record = new @@OBJ@@(@@REQ@@, @@NUM@@ = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(@@CLS@@.BAND_HIGH, @@CLS@@.bandFor(@@CLS@@.HIGH_THRESHOLD));
        Assert.areEqual(@@CLS@@.BAND_MEDIUM, @@CLS@@.bandFor(@@CLS@@.MEDIUM_THRESHOLD));
        Assert.areEqual(@@CLS@@.BAND_LOW, @@CLS@@.bandFor(@@CLS@@.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(@@CLS@@.BAND_NONE, @@CLS@@.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        System.runAs(areaUser()) {
            @@OBJ@@ high = sampleRecord(@@CLS@@.HIGH_THRESHOLD);
            @@OBJ@@ low = sampleRecord(@@CLS@@.MEDIUM_THRESHOLD - 1);

            Map<Id, String> bands = @@CLS@@.bandsFor(new Set<Id>{ high.Id, low.Id });

            Assert.areEqual(2, bands.size());
            Assert.areEqual(@@CLS@@.BAND_HIGH, bands.get(high.Id));
            Assert.areEqual(@@CLS@@.BAND_LOW, bands.get(low.Id));
            Assert.areEqual(0, @@CLS@@.bandsFor(new Set<Id>()).size());
        }
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        System.runAs(areaUser()) {
            @@OBJ@@ record = sampleRecord(@@CLS@@.HIGH_THRESHOLD);
            @@OBJ@@ before = [SELECT Id, @@NUM@@, @@TXT@@ FROM @@OBJ@@ WHERE Id = :record.Id WITH USER_MODE];
            Assert.isNull(before.@@TXT@@);

            @@CLS@@.stampBands(new List<@@OBJ@@>{ before });

            @@OBJ@@ after = [SELECT Id, @@TXT@@ FROM @@OBJ@@ WHERE Id = :record.Id WITH USER_MODE];
            Assert.areEqual(@@CLS@@.BAND_HIGH, after.@@TXT@@);
        }
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        System.runAs(areaUser()) {
            @@OBJ@@ record = sampleRecord(@@CLS@@.MEDIUM_THRESHOLD);

            Assert.areEqual(@@CLS@@.BAND_MEDIUM, @@CLS@@.bandForRecord(record.Id));
            Assert.isNull(@@CLS@@.bandForRecord(null));
        }
    }
}
"""

LEGACY_HEADER = """// Deliberate sign of age for the demo inventory: pinned to API @@VER@@, with no user-mode enforcement.
// Plain SOQL and DML, as code written before user mode existed would be; the rule baseline (WS8)
// records it as debt. Kept as is.
"""
LEGACY_TEST_HEADER = """// Plain SOQL and DML, matching @@CLS@@, the deliberately aged class it tests.
"""


def legacy_variant(body):
    """The same Apex with plain SOQL and DML: no WITH USER_MODE, no AccessLevel.USER_MODE."""
    body = re.sub(r"\n[ \t]+WITH USER_MODE\n", "\n", body)
    body = body.replace(" WITH USER_MODE]", "]")
    body = re.sub(r"Database\.(insert|update)\((\w+), AccessLevel\.USER_MODE\);", r"\1 \2;", body)
    assert "USER_MODE" not in body
    return body


def apex_class(files, name, body, api_version=API_VERSION):
    files[f"{BASE}/classes/{name}.cls"] = body
    files[f"{BASE}/classes/{name}.cls-meta.xml"] = apex_meta(api_version)


# ---------------------------------------------------------------- lwc

LWC_JS = """import { LightningElement, api, wire } from 'lwc';
import getBand from '@salesforce/apex/@@CLS@@.bandForRecord';

export default class @@PASCAL@@ extends LightningElement {
    @api recordId;

    band;
    error;

    @wire(getBand, { recordId: '$recordId' })
    wiredBand({ data, error }) {
        this.band = data;
        this.error = error;
    }

    get hasBand() {
        return !!this.band;
    }
}
"""

LWC_HTML = """<template>
    <lightning-card title="@@TITLE@@" icon-name="standard:@@ICON@@">
        <div class="slds-p-horizontal_small">
            <template lwc:if={hasBand}>
                <p class="slds-text-heading_small">{band}</p>
            </template>
            <template lwc:else>
                <p class="slds-text-color_weak">No band available.</p>
            </template>
        </div>
    </lightning-card>
</template>
"""

LWC_META = (HEAD + f'<LightningComponentBundle xmlns="{MD}">\n'
            "    <apiVersion>" + API_VERSION + "</apiVersion>\n"
            "    <isExposed>true</isExposed>\n"
            "    <masterLabel>@@TITLE@@</masterLabel>\n"
            "    <description>@@DESC@@</description>\n"
            "    <targets>\n        <target>lightning__RecordPage</target>\n    </targets>\n"
            "    <targetConfigs>\n"
            '        <targetConfig targets="lightning__RecordPage">\n'
            "            <objects>\n                <object>@@OBJ@@</object>\n            </objects>\n"
            "        </targetConfig>\n    </targetConfigs>\n"
            "</LightningComponentBundle>\n")

ICONS = {"Account": "account", "Contact": "contact", "Lead": "lead", "Opportunity": "opportunity"}


# ---------------------------------------------------------------- flows

FLOW_META_VALUES = """    <processMetadataValues>
        <name>BuilderType</name>
        <value>
            <stringValue>LightningFlowBuilder</stringValue>
        </value>
    </processMetadataValues>
    <processMetadataValues>
        <name>CanvasMode</name>
        <value>
            <stringValue>AUTO_LAYOUT_CANVAS</stringValue>
        </value>
    </processMetadataValues>
    <processMetadataValues>
        <name>OriginBuilderType</name>
        <value>
            <stringValue>LightningFlowBuilder</stringValue>
        </value>
    </processMetadataValues>
"""

RECORD_FLOW = (HEAD + f'<Flow xmlns="{MD}">\n'
               "    <apiVersion>" + API_VERSION + """</apiVersion>
    <assignments>
        <name>Stamp_Value</name>
        <label>Stamp Value</label>
        <locationX>176</locationX>
        <locationY>287</locationY>
        <assignmentItems>
            <assignToReference>$Record.@@TXT@@</assignToReference>
            <operator>Assign</operator>
            <value>
                <stringValue>@@STAMP@@</stringValue>
            </value>
        </assignmentItems>
    </assignments>
    <description>@@DESC@@</description>
    <environments>Default</environments>
    <interviewLabel>@@LABEL@@ {!$Flow.CurrentDateTime}</interviewLabel>
    <label>@@LABEL@@</label>
""" + FLOW_META_VALUES + """    <processType>AutoLaunchedFlow</processType>
    <start>
        <locationX>50</locationX>
        <locationY>0</locationY>
        <connector>
            <targetReference>Stamp_Value</targetReference>
        </connector>
        <filterLogic>and</filterLogic>
        <filters>
            <field>@@NUM@@</field>
            <operator>GreaterThan</operator>
            <value>
                <numberValue>@@THRESHOLD@@</numberValue>
            </value>
        </filters>
        <object>@@OBJ@@</object>
        <recordTriggerType>CreateAndUpdate</recordTriggerType>
        <triggerType>RecordBeforeSave</triggerType>
    </start>
    <status>Active</status>
</Flow>
""")

SCREEN_FLOW = (HEAD + f'<Flow xmlns="{MD}">\n'
               "    <apiVersion>" + API_VERSION + """</apiVersion>
    <description>@@DESC@@</description>
    <environments>Default</environments>
    <interviewLabel>@@LABEL@@ {!$Flow.CurrentDateTime}</interviewLabel>
    <label>@@LABEL@@</label>
""" + FLOW_META_VALUES + """    <processType>Flow</processType>
    <recordLookups>
        <name>Get_Record</name>
        <label>Get Record</label>
        <locationX>176</locationX>
        <locationY>134</locationY>
        <assignNullValuesIfNoRecordsFound>false</assignNullValuesIfNoRecordsFound>
        <connector>
            <targetReference>Review_Screen</targetReference>
        </connector>
        <filterLogic>and</filterLogic>
        <filters>
            <field>Id</field>
            <operator>EqualTo</operator>
            <value>
                <elementReference>recordId</elementReference>
            </value>
        </filters>
        <getFirstRecordOnly>true</getFirstRecordOnly>
        <object>@@OBJ@@</object>
        <storeOutputAutomatically>true</storeOutputAutomatically>
    </recordLookups>
    <screens>
        <name>Review_Screen</name>
        <label>Review Screen</label>
        <locationX>176</locationX>
        <locationY>242</locationY>
        <allowBack>false</allowBack>
        <allowFinish>true</allowFinish>
        <allowPause>false</allowPause>
        <fields>
            <name>Intro_Text</name>
            <fieldText>&lt;p&gt;@@INTRO@@&lt;/p&gt;</fieldText>
            <fieldType>DisplayText</fieldType>
        </fields>
        <fields>
            <name>Notes_Input</name>
            <dataType>String</dataType>
            <fieldText>Notes</fieldText>
            <fieldType>InputField</fieldType>
            <isRequired>false</isRequired>
        </fields>
        <showFooter>true</showFooter>
        <showHeader>true</showHeader>
    </screens>
    <start>
        <locationX>50</locationX>
        <locationY>0</locationY>
        <connector>
            <targetReference>Get_Record</targetReference>
        </connector>
    </start>
    <status>Active</status>
    <variables>
        <name>recordId</name>
        <dataType>String</dataType>
        <isCollection>false</isCollection>
        <isInput>true</isInput>
        <isOutput>false</isOutput>
    </variables>
</Flow>
""")


# ---------------------------------------------------------------- validation rules, permission sets

def rule_xml(name, desc, formula, display_field, message):
    return (HEAD + f'<ValidationRule xmlns="{MD}">\n'
            f"    <fullName>{name}</fullName>\n"
            "    <active>true</active>\n"
            f"    <description>{escape(desc)}</description>\n"
            f"    <errorConditionFormula>{escape(formula)}</errorConditionFormula>\n"
            f"    <errorDisplayField>{display_field}</errorDisplayField>\n"
            f"    <errorMessage>{escape(message)}</errorMessage>\n"
            "</ValidationRule>\n")


def permset_xml(obj, lab, field_names):
    out = [HEAD, f'<PermissionSet xmlns="{MD}">\n',
           f"    <description>Day-to-day access to {obj} planning fields for the sales team.</description>\n"]
    for f in sorted(field_names):
        out.append("    <fieldPermissions>\n        <editable>true</editable>\n"
                   f"        <field>{obj}.{f}</field>\n        <readable>true</readable>\n"
                   "    </fieldPermissions>\n")
    out.append("    <hasActivationRequired>false</hasActivationRequired>\n")
    out.append(f"    <label>{escape(lab)}</label>\n")
    out.append("    <objectPermissions>\n        <allowCreate>true</allowCreate>\n"
               "        <allowDelete>false</allowDelete>\n        <allowEdit>true</allowEdit>\n"
               "        <allowRead>true</allowRead>\n        <modifyAllRecords>false</modifyAllRecords>\n"
               f"        <object>{obj}</object>\n        <viewAllRecords>false</viewAllRecords>\n"
               "    </objectPermissions>\n")
    out.append("</PermissionSet>\n")
    return "".join(out)


# ---------------------------------------------------------------- generate

def generate(seed):
    """Every filler file as {path relative to the out dir: bytes}, sorted by path."""
    rng = random.Random(seed)
    files = {}

    # Fields
    for obj in OBJECTS:
        for name, ftype, values in FIELDS[obj]:
            files[f"{BASE}/objects/{obj}/fields/{name}.field-meta.xml"] = field_xml(obj, name, ftype, values)

    def of_type(obj, kinds):
        return [n for n, t, _ in FIELDS[obj] if t in kinds]

    ftypes = {n: t for obj in OBJECTS for n, t, _ in FIELDS[obj]}

    # Apex services, tests and LWCs
    services = []
    for obj in OBJECTS:
        for topic, num, txt in SERVICES[obj]:
            # Test values are the thresholds: keep them inside the field's bounds (rule_kind), so a
            # generated test never trips a generated validation rule.
            bounded = rule_kind(num, ftypes[num]) == "range"
            high = rng.choice([60, 80, 90] if bounded else [100, 500, 1000, 5000, 25000])
            services.append({"obj": obj, "cls": topic + rng.choice(SUFFIXES), "topic": topic,
                             "num": num, "txt": txt, "high": high,
                             "api_version": LEGACY_API_VERSIONS.get(topic, API_VERSION)})
    lwc_for = {}
    picked = rng.sample(range(len(services)), LWC_COUNT)
    for i in sorted(picked):
        s = services[i]
        lwc_for[s["cls"]] = lower_first(s["topic"]) + rng.choice(LWC_SUFFIXES)
    for s in services:
        lwc = lwc_for.get(s["cls"])
        tokens = dict(CLS=s["cls"], OBJ=s["obj"], NUM=s["num"], TXT=s["txt"], HIGH=s["high"],
                      MED=s["high"] // 2, TOPICWORDS=words(s["topic"]), NUMWORDS=words(s["num"]),
                      LWCREF=f"the {lwc} component" if lwc else "the record page",
                      REQ=REQUIRED_INIT[s["obj"]], PERMSET=PERMSETS[s["obj"]], VER=s["api_version"])
        service, test = fill(SERVICE_TEMPLATE, **tokens), fill(TEST_TEMPLATE, **tokens)
        if s["topic"] in LEGACY_API_VERSIONS:
            # Deliberate sign of age: user mode needs a newer API than the class is pinned to.
            service = fill(LEGACY_HEADER, **tokens) + legacy_variant(service)
            test = fill(LEGACY_TEST_HEADER, **tokens) + legacy_variant(test)
        apex_class(files, s["cls"], service, s["api_version"])
        apex_class(files, s["cls"] + "_Test", test)
    for s in services:
        name = lwc_for.get(s["cls"])
        if not name:
            continue
        title = label(name[0].upper() + name[1:])
        tokens = dict(CLS=s["cls"], PASCAL=name[0].upper() + name[1:], TITLE=title,
                      ICON=ICONS[s["obj"]], OBJ=s["obj"],
                      DESC=f"Shows the {words(s['topic'])} band of the {s['obj']} on its record page.")
        files[f"{BASE}/lwc/{name}/{name}.js"] = fill(LWC_JS, **tokens)
        files[f"{BASE}/lwc/{name}/{name}.html"] = fill(LWC_HTML, **tokens)
        files[f"{BASE}/lwc/{name}/{name}.js-meta.xml"] = fill(LWC_META, **tokens)

    # Record-triggered (before save) flows
    for obj in OBJECTS:
        for base in FLOW_BASES[obj]:
            name = f"{obj}_{base}"
            num = rng.choice(of_type(obj, NUMERIC))
            txt = FLOW_STATUS_FIELD[obj]
            threshold = (rng.choice([10, 25, 50, 75]) if rule_kind(num, ftypes[num]) == "range"
                         else rng.choice([100, 250, 1000]))
            lab = name.replace("_", " ")
            files[f"{BASE}/flows/{name}.flow-meta.xml"] = fill(
                RECORD_FLOW, OBJ=obj, NUM=num, TXT=txt, THRESHOLD=f"{threshold}.0", LABEL=lab,
                STAMP=rng.choice(FLOW_STAMPS),
                DESC=f"Before save on {obj}: when {words(num)} is above {threshold}, stamps {words(txt)}.")

    # Screen flows
    for obj, name in SCREEN_FLOWS:
        lab = name.replace("_", " ")
        files[f"{BASE}/flows/{name}.flow-meta.xml"] = fill(
            SCREEN_FLOW, OBJ=obj, LABEL=lab,
            DESC=f"Screen flow that walks a user through the {obj} record before they confirm.",
            INTRO=f"Review the {obj.lower()} details, add notes and finish.")

    # Validation rules: only where the field has a natural bound (see rule_kind)
    for obj in OBJECTS:
        eligible = [n for n, t, _ in FIELDS[obj] if rule_kind(n, t)]
        for fname in rng.sample(eligible, min(len(eligible), RULES_PER_OBJECT)):
            base = fname[:-3]
            kind = rule_kind(fname, ftypes[fname])
            if kind == "date":
                rname, formula = f"{base}_Not_Ancient", f"AND(NOT(ISBLANK({fname})), {fname} < DATE(2000, 1, 1))"
                msg = f"{label(fname)} cannot be before the year 2000."
            elif kind == "range":
                rname, formula = f"{base}_In_Range", f"AND(NOT(ISBLANK({fname})), OR({fname} < 0, {fname} > 100))"
                msg = f"{label(fname)} must be between 0 and 100."
            else:
                rname, formula = f"{base}_Not_Negative", f"AND(NOT(ISBLANK({fname})), {fname} < 0)"
                msg = f"{label(fname)} cannot be negative."
            files[f"{BASE}/objects/{obj}/validationRules/{rname}.validationRule-meta.xml"] = rule_xml(
                rname, f"Keeps {words(fname)} on {obj} records within a sensible range.", formula, fname, msg)

    # One permission set per area
    for obj in OBJECTS:
        name = PERMSETS[obj]
        files[f"{BASE}/permissionsets/{name}.permissionset-meta.xml"] = permset_xml(
            obj, name.replace("_", " "), [n for n, _, _ in FIELDS[obj]])

    return {p: files[p].encode("utf-8") for p in sorted(files)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", required=True, help="org directory, e.g. demo/org")
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 if files are missing or differ")
    args = ap.parse_args(argv)

    files = generate(args.seed)
    missing, differing = [], []
    for rel, data in files.items():
        path = os.path.join(args.out, *rel.split("/"))
        if not os.path.exists(path):
            missing.append(rel)
            continue
        with open(path, "rb") as fh:
            if fh.read() != data:
                differing.append(rel)

    if args.check:
        for rel in differing:
            print(f"differs: {rel}")
        for rel in missing:
            print(f"missing: {rel}")
        return 1 if (differing or missing) else 0

    if differing:
        for rel in differing:
            print(f"refusing to overwrite {rel}: exists with different content", file=sys.stderr)
        return 2
    for rel in missing:
        path = os.path.join(args.out, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:  # binary: no \r\n translation on Windows
            fh.write(files[rel])
    print(f"wrote {len(missing)} file(s); {len(files) - len(missing)} already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
