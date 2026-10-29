@IsTest
private with sharing class RenewalOutlookService_Test {

    private static Account sampleRecord(Decimal value) {
        Account record = new Account(Name = 'Sample Account', Health_Score__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(RenewalOutlookService.BAND_HIGH, RenewalOutlookService.bandFor(RenewalOutlookService.HIGH_THRESHOLD));
        Assert.areEqual(RenewalOutlookService.BAND_MEDIUM, RenewalOutlookService.bandFor(RenewalOutlookService.MEDIUM_THRESHOLD));
        Assert.areEqual(RenewalOutlookService.BAND_LOW, RenewalOutlookService.bandFor(RenewalOutlookService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(RenewalOutlookService.BAND_NONE, RenewalOutlookService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Account high = sampleRecord(RenewalOutlookService.HIGH_THRESHOLD);
        Account low = sampleRecord(RenewalOutlookService.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = RenewalOutlookService.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(RenewalOutlookService.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(RenewalOutlookService.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, RenewalOutlookService.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Account record = sampleRecord(RenewalOutlookService.HIGH_THRESHOLD);
        Account before = [SELECT Id, Health_Score__c, Health_Band__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Health_Band__c);

        RenewalOutlookService.stampBands(new List<Account>{ before });

        Account after = [SELECT Id, Health_Band__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(RenewalOutlookService.BAND_HIGH, after.Health_Band__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Account record = sampleRecord(RenewalOutlookService.MEDIUM_THRESHOLD);

        Assert.areEqual(RenewalOutlookService.BAND_MEDIUM, RenewalOutlookService.bandForRecord(record.Id));
        Assert.isNull(RenewalOutlookService.bandForRecord(null));
    }
}
