@IsTest
private with sharing class CompetitorWatchEvaluator_Test {

    private static Opportunity sampleRecord(Decimal value) {
        Opportunity record = new Opportunity(Name = 'Sample Opportunity', StageName = 'Prospecting', CloseDate = Date.today().addDays(30), Deal_Risk_Score__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(CompetitorWatchEvaluator.BAND_HIGH, CompetitorWatchEvaluator.bandFor(CompetitorWatchEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(CompetitorWatchEvaluator.BAND_MEDIUM, CompetitorWatchEvaluator.bandFor(CompetitorWatchEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(CompetitorWatchEvaluator.BAND_LOW, CompetitorWatchEvaluator.bandFor(CompetitorWatchEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(CompetitorWatchEvaluator.BAND_NONE, CompetitorWatchEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Opportunity high = sampleRecord(CompetitorWatchEvaluator.HIGH_THRESHOLD);
        Opportunity low = sampleRecord(CompetitorWatchEvaluator.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = CompetitorWatchEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(CompetitorWatchEvaluator.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(CompetitorWatchEvaluator.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, CompetitorWatchEvaluator.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Opportunity record = sampleRecord(CompetitorWatchEvaluator.HIGH_THRESHOLD);
        Opportunity before = [SELECT Id, Deal_Risk_Score__c, Risk_Band__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Risk_Band__c);

        CompetitorWatchEvaluator.stampBands(new List<Opportunity>{ before });

        Opportunity after = [SELECT Id, Risk_Band__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(CompetitorWatchEvaluator.BAND_HIGH, after.Risk_Band__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Opportunity record = sampleRecord(CompetitorWatchEvaluator.MEDIUM_THRESHOLD);

        Assert.areEqual(CompetitorWatchEvaluator.BAND_MEDIUM, CompetitorWatchEvaluator.bandForRecord(record.Id));
        Assert.isNull(CompetitorWatchEvaluator.bandForRecord(null));
    }
}
