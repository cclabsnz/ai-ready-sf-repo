@IsTest
private with sharing class ChurnWatchEvaluator_Test {

    private static Account sampleRecord(Decimal value) {
        Account record = new Account(Name = 'Sample Account', Churn_Risk_Pct__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(ChurnWatchEvaluator.BAND_HIGH, ChurnWatchEvaluator.bandFor(ChurnWatchEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(ChurnWatchEvaluator.BAND_MEDIUM, ChurnWatchEvaluator.bandFor(ChurnWatchEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(ChurnWatchEvaluator.BAND_LOW, ChurnWatchEvaluator.bandFor(ChurnWatchEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(ChurnWatchEvaluator.BAND_NONE, ChurnWatchEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Account high = sampleRecord(ChurnWatchEvaluator.HIGH_THRESHOLD);
        Account low = sampleRecord(ChurnWatchEvaluator.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = ChurnWatchEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(ChurnWatchEvaluator.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(ChurnWatchEvaluator.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, ChurnWatchEvaluator.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Account record = sampleRecord(ChurnWatchEvaluator.HIGH_THRESHOLD);
        Account before = [SELECT Id, Churn_Risk_Pct__c, Health_Band__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Health_Band__c);

        ChurnWatchEvaluator.stampBands(new List<Account>{ before });

        Account after = [SELECT Id, Health_Band__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(ChurnWatchEvaluator.BAND_HIGH, after.Health_Band__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Account record = sampleRecord(ChurnWatchEvaluator.MEDIUM_THRESHOLD);

        Assert.areEqual(ChurnWatchEvaluator.BAND_MEDIUM, ChurnWatchEvaluator.bandForRecord(record.Id));
        Assert.isNull(ChurnWatchEvaluator.bandForRecord(null));
    }
}
