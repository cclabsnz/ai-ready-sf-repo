@IsTest
private with sharing class LeadRoutingEvaluator_Test {

    private static Lead sampleRecord(Decimal value) {
        Lead record = new Lead(LastName = 'Sample Lead', Company = 'Sample Company', Intent_Score__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(LeadRoutingEvaluator.BAND_HIGH, LeadRoutingEvaluator.bandFor(LeadRoutingEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(LeadRoutingEvaluator.BAND_MEDIUM, LeadRoutingEvaluator.bandFor(LeadRoutingEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(LeadRoutingEvaluator.BAND_LOW, LeadRoutingEvaluator.bandFor(LeadRoutingEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(LeadRoutingEvaluator.BAND_NONE, LeadRoutingEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Lead high = sampleRecord(LeadRoutingEvaluator.HIGH_THRESHOLD);
        Lead low = sampleRecord(LeadRoutingEvaluator.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = LeadRoutingEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(LeadRoutingEvaluator.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(LeadRoutingEvaluator.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, LeadRoutingEvaluator.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Lead record = sampleRecord(LeadRoutingEvaluator.HIGH_THRESHOLD);
        Lead before = [SELECT Id, Intent_Score__c, Follow_Up_Priority__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Follow_Up_Priority__c);

        LeadRoutingEvaluator.stampBands(new List<Lead>{ before });

        Lead after = [SELECT Id, Follow_Up_Priority__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(LeadRoutingEvaluator.BAND_HIGH, after.Follow_Up_Priority__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Lead record = sampleRecord(LeadRoutingEvaluator.MEDIUM_THRESHOLD);

        Assert.areEqual(LeadRoutingEvaluator.BAND_MEDIUM, LeadRoutingEvaluator.bandForRecord(record.Id));
        Assert.isNull(LeadRoutingEvaluator.bandForRecord(null));
    }
}
