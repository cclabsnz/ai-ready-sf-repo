@IsTest
private with sharing class ExpansionTargetEvaluator_Test {

    private static Account sampleRecord(Decimal value) {
        Account record = new Account(Name = 'Sample Account', Expansion_Potential__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(ExpansionTargetEvaluator.BAND_HIGH, ExpansionTargetEvaluator.bandFor(ExpansionTargetEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(ExpansionTargetEvaluator.BAND_MEDIUM, ExpansionTargetEvaluator.bandFor(ExpansionTargetEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(ExpansionTargetEvaluator.BAND_LOW, ExpansionTargetEvaluator.bandFor(ExpansionTargetEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(ExpansionTargetEvaluator.BAND_NONE, ExpansionTargetEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Account high = sampleRecord(ExpansionTargetEvaluator.HIGH_THRESHOLD);
        Account low = sampleRecord(ExpansionTargetEvaluator.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = ExpansionTargetEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(ExpansionTargetEvaluator.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(ExpansionTargetEvaluator.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, ExpansionTargetEvaluator.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Account record = sampleRecord(ExpansionTargetEvaluator.HIGH_THRESHOLD);
        Account before = [SELECT Id, Expansion_Potential__c, Account_Tier_Label__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Account_Tier_Label__c);

        ExpansionTargetEvaluator.stampBands(new List<Account>{ before });

        Account after = [SELECT Id, Account_Tier_Label__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(ExpansionTargetEvaluator.BAND_HIGH, after.Account_Tier_Label__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Account record = sampleRecord(ExpansionTargetEvaluator.MEDIUM_THRESHOLD);

        Assert.areEqual(ExpansionTargetEvaluator.BAND_MEDIUM, ExpansionTargetEvaluator.bandForRecord(record.Id));
        Assert.isNull(ExpansionTargetEvaluator.bandForRecord(null));
    }
}
