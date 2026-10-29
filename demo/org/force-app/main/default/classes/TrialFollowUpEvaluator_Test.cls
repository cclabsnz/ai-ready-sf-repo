@IsTest
private with sharing class TrialFollowUpEvaluator_Test {

    private static Lead sampleRecord(Decimal value) {
        Lead record = new Lead(LastName = 'Sample Lead', Company = 'Sample Company', Intent_Score__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(TrialFollowUpEvaluator.BAND_HIGH, TrialFollowUpEvaluator.bandFor(TrialFollowUpEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(TrialFollowUpEvaluator.BAND_MEDIUM, TrialFollowUpEvaluator.bandFor(TrialFollowUpEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(TrialFollowUpEvaluator.BAND_LOW, TrialFollowUpEvaluator.bandFor(TrialFollowUpEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(TrialFollowUpEvaluator.BAND_NONE, TrialFollowUpEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Lead high = sampleRecord(TrialFollowUpEvaluator.HIGH_THRESHOLD);
        Lead low = sampleRecord(TrialFollowUpEvaluator.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = TrialFollowUpEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(TrialFollowUpEvaluator.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(TrialFollowUpEvaluator.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, TrialFollowUpEvaluator.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Lead record = sampleRecord(TrialFollowUpEvaluator.HIGH_THRESHOLD);
        Lead before = [SELECT Id, Intent_Score__c, Follow_Up_Priority__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Follow_Up_Priority__c);

        TrialFollowUpEvaluator.stampBands(new List<Lead>{ before });

        Lead after = [SELECT Id, Follow_Up_Priority__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(TrialFollowUpEvaluator.BAND_HIGH, after.Follow_Up_Priority__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Lead record = sampleRecord(TrialFollowUpEvaluator.MEDIUM_THRESHOLD);

        Assert.areEqual(TrialFollowUpEvaluator.BAND_MEDIUM, TrialFollowUpEvaluator.bandForRecord(record.Id));
        Assert.isNull(TrialFollowUpEvaluator.bandForRecord(null));
    }
}
