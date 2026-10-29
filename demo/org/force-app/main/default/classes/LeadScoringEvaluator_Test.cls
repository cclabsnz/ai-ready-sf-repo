@IsTest
private with sharing class LeadScoringEvaluator_Test {

    /**
     * A standard user holding the Lead_Management_Access permission set.
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
        PermissionSet ps = [SELECT Id FROM PermissionSet WHERE Name = 'Lead_Management_Access' LIMIT 1];
        // Setup objects in their own runAs block, so the record inserts that follow do not raise
        // MIXED_DML_OPERATION.
        System.runAs(new User(Id = UserInfo.getUserId())) {
            insert u;
            insert new PermissionSetAssignment(AssigneeId = u.Id, PermissionSetId = ps.Id);
        }
        return u;
    }

    private static Lead sampleRecord(Decimal value) {
        Lead record = new Lead(LastName = 'Sample Lead', Company = 'Sample Company', Lead_Fit_Score__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(LeadScoringEvaluator.BAND_HIGH, LeadScoringEvaluator.bandFor(LeadScoringEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(LeadScoringEvaluator.BAND_MEDIUM, LeadScoringEvaluator.bandFor(LeadScoringEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(LeadScoringEvaluator.BAND_LOW, LeadScoringEvaluator.bandFor(LeadScoringEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(LeadScoringEvaluator.BAND_NONE, LeadScoringEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        System.runAs(areaUser()) {
            Lead high = sampleRecord(LeadScoringEvaluator.HIGH_THRESHOLD);
            Lead low = sampleRecord(LeadScoringEvaluator.MEDIUM_THRESHOLD - 1);

            Map<Id, String> bands = LeadScoringEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

            Assert.areEqual(2, bands.size());
            Assert.areEqual(LeadScoringEvaluator.BAND_HIGH, bands.get(high.Id));
            Assert.areEqual(LeadScoringEvaluator.BAND_LOW, bands.get(low.Id));
            Assert.areEqual(0, LeadScoringEvaluator.bandsFor(new Set<Id>()).size());
        }
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        System.runAs(areaUser()) {
            Lead record = sampleRecord(LeadScoringEvaluator.HIGH_THRESHOLD);
            Lead before = [SELECT Id, Lead_Fit_Score__c, Lead_Tier_Label__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
            Assert.isNull(before.Lead_Tier_Label__c);

            LeadScoringEvaluator.stampBands(new List<Lead>{ before });

            Lead after = [SELECT Id, Lead_Tier_Label__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
            Assert.areEqual(LeadScoringEvaluator.BAND_HIGH, after.Lead_Tier_Label__c);
        }
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        System.runAs(areaUser()) {
            Lead record = sampleRecord(LeadScoringEvaluator.MEDIUM_THRESHOLD);

            Assert.areEqual(LeadScoringEvaluator.BAND_MEDIUM, LeadScoringEvaluator.bandForRecord(record.Id));
            Assert.isNull(LeadScoringEvaluator.bandForRecord(null));
        }
    }
}
