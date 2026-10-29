@IsTest
private with sharing class PipelineHealthEvaluator_Test {

    private static Opportunity sampleRecord(Decimal value) {
        Opportunity record = new Opportunity(Name = 'Sample Opportunity', StageName = 'Prospecting', CloseDate = Date.today().addDays(30), Deal_Risk_Score__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(PipelineHealthEvaluator.BAND_HIGH, PipelineHealthEvaluator.bandFor(PipelineHealthEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(PipelineHealthEvaluator.BAND_MEDIUM, PipelineHealthEvaluator.bandFor(PipelineHealthEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(PipelineHealthEvaluator.BAND_LOW, PipelineHealthEvaluator.bandFor(PipelineHealthEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(PipelineHealthEvaluator.BAND_NONE, PipelineHealthEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Opportunity high = sampleRecord(PipelineHealthEvaluator.HIGH_THRESHOLD);
        Opportunity low = sampleRecord(PipelineHealthEvaluator.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = PipelineHealthEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(PipelineHealthEvaluator.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(PipelineHealthEvaluator.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, PipelineHealthEvaluator.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Opportunity record = sampleRecord(PipelineHealthEvaluator.HIGH_THRESHOLD);
        Opportunity before = [SELECT Id, Deal_Risk_Score__c, Risk_Band__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Risk_Band__c);

        PipelineHealthEvaluator.stampBands(new List<Opportunity>{ before });

        Opportunity after = [SELECT Id, Risk_Band__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(PipelineHealthEvaluator.BAND_HIGH, after.Risk_Band__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Opportunity record = sampleRecord(PipelineHealthEvaluator.MEDIUM_THRESHOLD);

        Assert.areEqual(PipelineHealthEvaluator.BAND_MEDIUM, PipelineHealthEvaluator.bandForRecord(record.Id));
        Assert.isNull(PipelineHealthEvaluator.bandForRecord(null));
    }
}
