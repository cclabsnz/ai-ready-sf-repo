@IsTest
private with sharing class LegalReviewService_Test {

    private static Opportunity sampleRecord(Decimal value) {
        Opportunity record = new Opportunity(Name = 'Sample Opportunity', StageName = 'Prospecting', CloseDate = Date.today().addDays(30), Contract_Term_Months__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(LegalReviewService.BAND_HIGH, LegalReviewService.bandFor(LegalReviewService.HIGH_THRESHOLD));
        Assert.areEqual(LegalReviewService.BAND_MEDIUM, LegalReviewService.bandFor(LegalReviewService.MEDIUM_THRESHOLD));
        Assert.areEqual(LegalReviewService.BAND_LOW, LegalReviewService.bandFor(LegalReviewService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(LegalReviewService.BAND_NONE, LegalReviewService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Opportunity high = sampleRecord(LegalReviewService.HIGH_THRESHOLD);
        Opportunity low = sampleRecord(LegalReviewService.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = LegalReviewService.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(LegalReviewService.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(LegalReviewService.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, LegalReviewService.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Opportunity record = sampleRecord(LegalReviewService.HIGH_THRESHOLD);
        Opportunity before = [SELECT Id, Contract_Term_Months__c, Review_Status_Label__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Review_Status_Label__c);

        LegalReviewService.stampBands(new List<Opportunity>{ before });

        Opportunity after = [SELECT Id, Review_Status_Label__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(LegalReviewService.BAND_HIGH, after.Review_Status_Label__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Opportunity record = sampleRecord(LegalReviewService.MEDIUM_THRESHOLD);

        Assert.areEqual(LegalReviewService.BAND_MEDIUM, LegalReviewService.bandForRecord(record.Id));
        Assert.isNull(LegalReviewService.bandForRecord(null));
    }
}
