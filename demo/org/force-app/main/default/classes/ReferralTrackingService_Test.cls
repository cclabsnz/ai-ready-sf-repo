@IsTest
private with sharing class ReferralTrackingService_Test {

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
        Lead record = new Lead(LastName = 'Sample Lead', Company = 'Sample Company', Budget_Estimate__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(ReferralTrackingService.BAND_HIGH, ReferralTrackingService.bandFor(ReferralTrackingService.HIGH_THRESHOLD));
        Assert.areEqual(ReferralTrackingService.BAND_MEDIUM, ReferralTrackingService.bandFor(ReferralTrackingService.MEDIUM_THRESHOLD));
        Assert.areEqual(ReferralTrackingService.BAND_LOW, ReferralTrackingService.bandFor(ReferralTrackingService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(ReferralTrackingService.BAND_NONE, ReferralTrackingService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        System.runAs(areaUser()) {
            Lead high = sampleRecord(ReferralTrackingService.HIGH_THRESHOLD);
            Lead low = sampleRecord(ReferralTrackingService.MEDIUM_THRESHOLD - 1);

            Map<Id, String> bands = ReferralTrackingService.bandsFor(new Set<Id>{ high.Id, low.Id });

            Assert.areEqual(2, bands.size());
            Assert.areEqual(ReferralTrackingService.BAND_HIGH, bands.get(high.Id));
            Assert.areEqual(ReferralTrackingService.BAND_LOW, bands.get(low.Id));
            Assert.areEqual(0, ReferralTrackingService.bandsFor(new Set<Id>()).size());
        }
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        System.runAs(areaUser()) {
            Lead record = sampleRecord(ReferralTrackingService.HIGH_THRESHOLD);
            Lead before = [SELECT Id, Budget_Estimate__c, Follow_Up_Priority__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
            Assert.isNull(before.Follow_Up_Priority__c);

            ReferralTrackingService.stampBands(new List<Lead>{ before });

            Lead after = [SELECT Id, Follow_Up_Priority__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
            Assert.areEqual(ReferralTrackingService.BAND_HIGH, after.Follow_Up_Priority__c);
        }
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        System.runAs(areaUser()) {
            Lead record = sampleRecord(ReferralTrackingService.MEDIUM_THRESHOLD);

            Assert.areEqual(ReferralTrackingService.BAND_MEDIUM, ReferralTrackingService.bandForRecord(record.Id));
            Assert.isNull(ReferralTrackingService.bandForRecord(null));
        }
    }
}
