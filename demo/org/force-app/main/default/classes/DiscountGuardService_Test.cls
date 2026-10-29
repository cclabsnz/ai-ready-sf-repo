@IsTest
private with sharing class DiscountGuardService_Test {

    private static Opportunity sampleRecord(Decimal value) {
        Opportunity record = new Opportunity(Name = 'Sample Opportunity', StageName = 'Prospecting', CloseDate = Date.today().addDays(30), Discount_Pct__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(DiscountGuardService.BAND_HIGH, DiscountGuardService.bandFor(DiscountGuardService.HIGH_THRESHOLD));
        Assert.areEqual(DiscountGuardService.BAND_MEDIUM, DiscountGuardService.bandFor(DiscountGuardService.MEDIUM_THRESHOLD));
        Assert.areEqual(DiscountGuardService.BAND_LOW, DiscountGuardService.bandFor(DiscountGuardService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(DiscountGuardService.BAND_NONE, DiscountGuardService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Opportunity high = sampleRecord(DiscountGuardService.HIGH_THRESHOLD);
        Opportunity low = sampleRecord(DiscountGuardService.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = DiscountGuardService.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(DiscountGuardService.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(DiscountGuardService.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, DiscountGuardService.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Opportunity record = sampleRecord(DiscountGuardService.HIGH_THRESHOLD);
        Opportunity before = [SELECT Id, Discount_Pct__c, Review_Status_Label__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Review_Status_Label__c);

        DiscountGuardService.stampBands(new List<Opportunity>{ before });

        Opportunity after = [SELECT Id, Review_Status_Label__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(DiscountGuardService.BAND_HIGH, after.Review_Status_Label__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Opportunity record = sampleRecord(DiscountGuardService.MEDIUM_THRESHOLD);

        Assert.areEqual(DiscountGuardService.BAND_MEDIUM, DiscountGuardService.bandForRecord(record.Id));
        Assert.isNull(DiscountGuardService.bandForRecord(null));
    }
}
