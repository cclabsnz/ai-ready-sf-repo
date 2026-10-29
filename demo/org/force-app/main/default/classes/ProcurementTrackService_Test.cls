@IsTest
private with sharing class ProcurementTrackService_Test {

    private static Opportunity sampleRecord(Decimal value) {
        Opportunity record = new Opportunity(Name = 'Sample Opportunity', StageName = 'Prospecting', CloseDate = Date.today().addDays(30), Quote_Total__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(ProcurementTrackService.BAND_HIGH, ProcurementTrackService.bandFor(ProcurementTrackService.HIGH_THRESHOLD));
        Assert.areEqual(ProcurementTrackService.BAND_MEDIUM, ProcurementTrackService.bandFor(ProcurementTrackService.MEDIUM_THRESHOLD));
        Assert.areEqual(ProcurementTrackService.BAND_LOW, ProcurementTrackService.bandFor(ProcurementTrackService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(ProcurementTrackService.BAND_NONE, ProcurementTrackService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Opportunity high = sampleRecord(ProcurementTrackService.HIGH_THRESHOLD);
        Opportunity low = sampleRecord(ProcurementTrackService.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = ProcurementTrackService.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(ProcurementTrackService.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(ProcurementTrackService.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, ProcurementTrackService.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Opportunity record = sampleRecord(ProcurementTrackService.HIGH_THRESHOLD);
        Opportunity before = [SELECT Id, Quote_Total__c, Review_Status_Label__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Review_Status_Label__c);

        ProcurementTrackService.stampBands(new List<Opportunity>{ before });

        Opportunity after = [SELECT Id, Review_Status_Label__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(ProcurementTrackService.BAND_HIGH, after.Review_Status_Label__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Opportunity record = sampleRecord(ProcurementTrackService.MEDIUM_THRESHOLD);

        Assert.areEqual(ProcurementTrackService.BAND_MEDIUM, ProcurementTrackService.bandForRecord(record.Id));
        Assert.isNull(ProcurementTrackService.bandForRecord(null));
    }
}
