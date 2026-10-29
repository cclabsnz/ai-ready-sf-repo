@IsTest
private with sharing class StageAgingService_Test {

    private static Opportunity sampleRecord(Decimal value) {
        Opportunity record = new Opportunity(Name = 'Sample Opportunity', StageName = 'Prospecting', CloseDate = Date.today().addDays(30), Quote_Total__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(StageAgingService.BAND_HIGH, StageAgingService.bandFor(StageAgingService.HIGH_THRESHOLD));
        Assert.areEqual(StageAgingService.BAND_MEDIUM, StageAgingService.bandFor(StageAgingService.MEDIUM_THRESHOLD));
        Assert.areEqual(StageAgingService.BAND_LOW, StageAgingService.bandFor(StageAgingService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(StageAgingService.BAND_NONE, StageAgingService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Opportunity high = sampleRecord(StageAgingService.HIGH_THRESHOLD);
        Opportunity low = sampleRecord(StageAgingService.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = StageAgingService.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(StageAgingService.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(StageAgingService.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, StageAgingService.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Opportunity record = sampleRecord(StageAgingService.HIGH_THRESHOLD);
        Opportunity before = [SELECT Id, Quote_Total__c, Risk_Band__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Risk_Band__c);

        StageAgingService.stampBands(new List<Opportunity>{ before });

        Opportunity after = [SELECT Id, Risk_Band__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(StageAgingService.BAND_HIGH, after.Risk_Band__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Opportunity record = sampleRecord(StageAgingService.MEDIUM_THRESHOLD);

        Assert.areEqual(StageAgingService.BAND_MEDIUM, StageAgingService.bandForRecord(record.Id));
        Assert.isNull(StageAgingService.bandForRecord(null));
    }
}
