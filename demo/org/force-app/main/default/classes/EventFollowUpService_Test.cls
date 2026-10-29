@IsTest
private with sharing class EventFollowUpService_Test {

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
        Contact record = new Contact(LastName = 'Sample Contact', Event_Spend__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(EventFollowUpService.BAND_HIGH, EventFollowUpService.bandFor(EventFollowUpService.HIGH_THRESHOLD));
        Assert.areEqual(EventFollowUpService.BAND_MEDIUM, EventFollowUpService.bandFor(EventFollowUpService.MEDIUM_THRESHOLD));
        Assert.areEqual(EventFollowUpService.BAND_LOW, EventFollowUpService.bandFor(EventFollowUpService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(EventFollowUpService.BAND_NONE, EventFollowUpService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        System.runAs(areaUser()) {
            Contact high = sampleRecord(EventFollowUpService.HIGH_THRESHOLD);
            Contact low = sampleRecord(EventFollowUpService.MEDIUM_THRESHOLD - 1);

            Map<Id, String> bands = EventFollowUpService.bandsFor(new Set<Id>{ high.Id, low.Id });

            Assert.areEqual(2, bands.size());
            Assert.areEqual(EventFollowUpService.BAND_HIGH, bands.get(high.Id));
            Assert.areEqual(EventFollowUpService.BAND_LOW, bands.get(low.Id));
            Assert.areEqual(0, EventFollowUpService.bandsFor(new Set<Id>()).size());
        }
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        System.runAs(areaUser()) {
            Contact record = sampleRecord(EventFollowUpService.HIGH_THRESHOLD);
            Contact before = [SELECT Id, Event_Spend__c, Outreach_Priority__c FROM Contact WHERE Id = :record.Id WITH USER_MODE];
            Assert.isNull(before.Outreach_Priority__c);

            EventFollowUpService.stampBands(new List<Contact>{ before });

            Contact after = [SELECT Id, Outreach_Priority__c FROM Contact WHERE Id = :record.Id WITH USER_MODE];
            Assert.areEqual(EventFollowUpService.BAND_HIGH, after.Outreach_Priority__c);
        }
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        System.runAs(areaUser()) {
            Contact record = sampleRecord(EventFollowUpService.MEDIUM_THRESHOLD);

            Assert.areEqual(EventFollowUpService.BAND_MEDIUM, EventFollowUpService.bandForRecord(record.Id));
            Assert.isNull(EventFollowUpService.bandForRecord(null));
        }
    }
}
