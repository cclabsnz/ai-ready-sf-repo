@IsTest
private with sharing class DecisionMakerService_Test {

    private static Contact sampleRecord(Decimal value) {
        Contact record = new Contact(LastName = 'Sample Contact', Engagement_Score__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(DecisionMakerService.BAND_HIGH, DecisionMakerService.bandFor(DecisionMakerService.HIGH_THRESHOLD));
        Assert.areEqual(DecisionMakerService.BAND_MEDIUM, DecisionMakerService.bandFor(DecisionMakerService.MEDIUM_THRESHOLD));
        Assert.areEqual(DecisionMakerService.BAND_LOW, DecisionMakerService.bandFor(DecisionMakerService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(DecisionMakerService.BAND_NONE, DecisionMakerService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Contact high = sampleRecord(DecisionMakerService.HIGH_THRESHOLD);
        Contact low = sampleRecord(DecisionMakerService.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = DecisionMakerService.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(DecisionMakerService.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(DecisionMakerService.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, DecisionMakerService.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Contact record = sampleRecord(DecisionMakerService.HIGH_THRESHOLD);
        Contact before = [SELECT Id, Engagement_Score__c, Engagement_Band__c FROM Contact WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Engagement_Band__c);

        DecisionMakerService.stampBands(new List<Contact>{ before });

        Contact after = [SELECT Id, Engagement_Band__c FROM Contact WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(DecisionMakerService.BAND_HIGH, after.Engagement_Band__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Contact record = sampleRecord(DecisionMakerService.MEDIUM_THRESHOLD);

        Assert.areEqual(DecisionMakerService.BAND_MEDIUM, DecisionMakerService.bandForRecord(record.Id));
        Assert.isNull(DecisionMakerService.bandForRecord(null));
    }
}
