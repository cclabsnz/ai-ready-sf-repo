@IsTest
private with sharing class ResponseTrackingEvaluator_Test {

    /**
     * A standard user holding the Contact_Engagement_Access permission set.
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
        PermissionSet ps = [SELECT Id FROM PermissionSet WHERE Name = 'Contact_Engagement_Access' LIMIT 1];
        // Setup objects in their own runAs block, so the record inserts that follow do not raise
        // MIXED_DML_OPERATION.
        System.runAs(new User(Id = UserInfo.getUserId())) {
            insert u;
            insert new PermissionSetAssignment(AssigneeId = u.Id, PermissionSetId = ps.Id);
        }
        return u;
    }

    private static Contact sampleRecord(Decimal value) {
        Contact record = new Contact(LastName = 'Sample Contact', Response_Rate_Pct__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(ResponseTrackingEvaluator.BAND_HIGH, ResponseTrackingEvaluator.bandFor(ResponseTrackingEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(ResponseTrackingEvaluator.BAND_MEDIUM, ResponseTrackingEvaluator.bandFor(ResponseTrackingEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(ResponseTrackingEvaluator.BAND_LOW, ResponseTrackingEvaluator.bandFor(ResponseTrackingEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(ResponseTrackingEvaluator.BAND_NONE, ResponseTrackingEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        System.runAs(areaUser()) {
            Contact high = sampleRecord(ResponseTrackingEvaluator.HIGH_THRESHOLD);
            Contact low = sampleRecord(ResponseTrackingEvaluator.MEDIUM_THRESHOLD - 1);

            Map<Id, String> bands = ResponseTrackingEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

            Assert.areEqual(2, bands.size());
            Assert.areEqual(ResponseTrackingEvaluator.BAND_HIGH, bands.get(high.Id));
            Assert.areEqual(ResponseTrackingEvaluator.BAND_LOW, bands.get(low.Id));
            Assert.areEqual(0, ResponseTrackingEvaluator.bandsFor(new Set<Id>()).size());
        }
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        System.runAs(areaUser()) {
            Contact record = sampleRecord(ResponseTrackingEvaluator.HIGH_THRESHOLD);
            Contact before = [SELECT Id, Response_Rate_Pct__c, Engagement_Band__c FROM Contact WHERE Id = :record.Id WITH USER_MODE];
            Assert.isNull(before.Engagement_Band__c);

            ResponseTrackingEvaluator.stampBands(new List<Contact>{ before });

            Contact after = [SELECT Id, Engagement_Band__c FROM Contact WHERE Id = :record.Id WITH USER_MODE];
            Assert.areEqual(ResponseTrackingEvaluator.BAND_HIGH, after.Engagement_Band__c);
        }
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        System.runAs(areaUser()) {
            Contact record = sampleRecord(ResponseTrackingEvaluator.MEDIUM_THRESHOLD);

            Assert.areEqual(ResponseTrackingEvaluator.BAND_MEDIUM, ResponseTrackingEvaluator.bandForRecord(record.Id));
            Assert.isNull(ResponseTrackingEvaluator.bandForRecord(null));
        }
    }
}
