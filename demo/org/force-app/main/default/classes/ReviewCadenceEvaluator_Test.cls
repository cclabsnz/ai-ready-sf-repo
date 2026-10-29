@IsTest
private with sharing class ReviewCadenceEvaluator_Test {

    private static Account sampleRecord(Decimal value) {
        Account record = new Account(Name = 'Sample Account', Health_Score__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(ReviewCadenceEvaluator.BAND_HIGH, ReviewCadenceEvaluator.bandFor(ReviewCadenceEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(ReviewCadenceEvaluator.BAND_MEDIUM, ReviewCadenceEvaluator.bandFor(ReviewCadenceEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(ReviewCadenceEvaluator.BAND_LOW, ReviewCadenceEvaluator.bandFor(ReviewCadenceEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(ReviewCadenceEvaluator.BAND_NONE, ReviewCadenceEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Account high = sampleRecord(ReviewCadenceEvaluator.HIGH_THRESHOLD);
        Account low = sampleRecord(ReviewCadenceEvaluator.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = ReviewCadenceEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(ReviewCadenceEvaluator.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(ReviewCadenceEvaluator.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, ReviewCadenceEvaluator.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Account record = sampleRecord(ReviewCadenceEvaluator.HIGH_THRESHOLD);
        Account before = [SELECT Id, Health_Score__c, Health_Band__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Health_Band__c);

        ReviewCadenceEvaluator.stampBands(new List<Account>{ before });

        Account after = [SELECT Id, Health_Band__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(ReviewCadenceEvaluator.BAND_HIGH, after.Health_Band__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Account record = sampleRecord(ReviewCadenceEvaluator.MEDIUM_THRESHOLD);

        Assert.areEqual(ReviewCadenceEvaluator.BAND_MEDIUM, ReviewCadenceEvaluator.bandForRecord(record.Id));
        Assert.isNull(ReviewCadenceEvaluator.bandForRecord(null));
    }
}
