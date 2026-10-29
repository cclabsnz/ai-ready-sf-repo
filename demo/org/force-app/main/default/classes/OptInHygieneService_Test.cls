@IsTest
private with sharing class OptInHygieneService_Test {

    private static Contact sampleRecord(Decimal value) {
        Contact record = new Contact(LastName = 'Sample Contact', Response_Rate_Pct__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(OptInHygieneService.BAND_HIGH, OptInHygieneService.bandFor(OptInHygieneService.HIGH_THRESHOLD));
        Assert.areEqual(OptInHygieneService.BAND_MEDIUM, OptInHygieneService.bandFor(OptInHygieneService.MEDIUM_THRESHOLD));
        Assert.areEqual(OptInHygieneService.BAND_LOW, OptInHygieneService.bandFor(OptInHygieneService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(OptInHygieneService.BAND_NONE, OptInHygieneService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Contact high = sampleRecord(OptInHygieneService.HIGH_THRESHOLD);
        Contact low = sampleRecord(OptInHygieneService.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = OptInHygieneService.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(OptInHygieneService.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(OptInHygieneService.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, OptInHygieneService.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Contact record = sampleRecord(OptInHygieneService.HIGH_THRESHOLD);
        Contact before = [SELECT Id, Response_Rate_Pct__c, Outreach_Priority__c FROM Contact WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Outreach_Priority__c);

        OptInHygieneService.stampBands(new List<Contact>{ before });

        Contact after = [SELECT Id, Outreach_Priority__c FROM Contact WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(OptInHygieneService.BAND_HIGH, after.Outreach_Priority__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Contact record = sampleRecord(OptInHygieneService.MEDIUM_THRESHOLD);

        Assert.areEqual(OptInHygieneService.BAND_MEDIUM, OptInHygieneService.bandForRecord(record.Id));
        Assert.isNull(OptInHygieneService.bandForRecord(null));
    }
}
