@IsTest
private with sharing class ContactEngagementService_Test {

    private static Contact sampleRecord(Decimal value) {
        Contact record = new Contact(LastName = 'Sample Contact', Engagement_Score__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(ContactEngagementService.BAND_HIGH, ContactEngagementService.bandFor(ContactEngagementService.HIGH_THRESHOLD));
        Assert.areEqual(ContactEngagementService.BAND_MEDIUM, ContactEngagementService.bandFor(ContactEngagementService.MEDIUM_THRESHOLD));
        Assert.areEqual(ContactEngagementService.BAND_LOW, ContactEngagementService.bandFor(ContactEngagementService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(ContactEngagementService.BAND_NONE, ContactEngagementService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Contact high = sampleRecord(ContactEngagementService.HIGH_THRESHOLD);
        Contact low = sampleRecord(ContactEngagementService.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = ContactEngagementService.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(ContactEngagementService.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(ContactEngagementService.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, ContactEngagementService.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Contact record = sampleRecord(ContactEngagementService.HIGH_THRESHOLD);
        Contact before = [SELECT Id, Engagement_Score__c, Engagement_Band__c FROM Contact WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Engagement_Band__c);

        ContactEngagementService.stampBands(new List<Contact>{ before });

        Contact after = [SELECT Id, Engagement_Band__c FROM Contact WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(ContactEngagementService.BAND_HIGH, after.Engagement_Band__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Contact record = sampleRecord(ContactEngagementService.MEDIUM_THRESHOLD);

        Assert.areEqual(ContactEngagementService.BAND_MEDIUM, ContactEngagementService.bandForRecord(record.Id));
        Assert.isNull(ContactEngagementService.bandForRecord(null));
    }
}
