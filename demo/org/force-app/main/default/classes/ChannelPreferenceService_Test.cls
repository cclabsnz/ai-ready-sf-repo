@IsTest
private with sharing class ChannelPreferenceService_Test {

    private static Contact sampleRecord(Decimal value) {
        Contact record = new Contact(LastName = 'Sample Contact', Event_Spend__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(ChannelPreferenceService.BAND_HIGH, ChannelPreferenceService.bandFor(ChannelPreferenceService.HIGH_THRESHOLD));
        Assert.areEqual(ChannelPreferenceService.BAND_MEDIUM, ChannelPreferenceService.bandFor(ChannelPreferenceService.MEDIUM_THRESHOLD));
        Assert.areEqual(ChannelPreferenceService.BAND_LOW, ChannelPreferenceService.bandFor(ChannelPreferenceService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(ChannelPreferenceService.BAND_NONE, ChannelPreferenceService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Contact high = sampleRecord(ChannelPreferenceService.HIGH_THRESHOLD);
        Contact low = sampleRecord(ChannelPreferenceService.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = ChannelPreferenceService.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(ChannelPreferenceService.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(ChannelPreferenceService.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, ChannelPreferenceService.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Contact record = sampleRecord(ChannelPreferenceService.HIGH_THRESHOLD);
        Contact before = [SELECT Id, Event_Spend__c, Outreach_Priority__c FROM Contact WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Outreach_Priority__c);

        ChannelPreferenceService.stampBands(new List<Contact>{ before });

        Contact after = [SELECT Id, Outreach_Priority__c FROM Contact WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(ChannelPreferenceService.BAND_HIGH, after.Outreach_Priority__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Contact record = sampleRecord(ChannelPreferenceService.MEDIUM_THRESHOLD);

        Assert.areEqual(ChannelPreferenceService.BAND_MEDIUM, ChannelPreferenceService.bandForRecord(record.Id));
        Assert.isNull(ChannelPreferenceService.bandForRecord(null));
    }
}
