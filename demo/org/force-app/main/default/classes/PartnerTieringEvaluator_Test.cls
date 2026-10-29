@IsTest
private with sharing class PartnerTieringEvaluator_Test {

    private static Account sampleRecord(Decimal value) {
        Account record = new Account(Name = 'Sample Account', Expansion_Potential__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(PartnerTieringEvaluator.BAND_HIGH, PartnerTieringEvaluator.bandFor(PartnerTieringEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(PartnerTieringEvaluator.BAND_MEDIUM, PartnerTieringEvaluator.bandFor(PartnerTieringEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(PartnerTieringEvaluator.BAND_LOW, PartnerTieringEvaluator.bandFor(PartnerTieringEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(PartnerTieringEvaluator.BAND_NONE, PartnerTieringEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Account high = sampleRecord(PartnerTieringEvaluator.HIGH_THRESHOLD);
        Account low = sampleRecord(PartnerTieringEvaluator.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = PartnerTieringEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(PartnerTieringEvaluator.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(PartnerTieringEvaluator.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, PartnerTieringEvaluator.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Account record = sampleRecord(PartnerTieringEvaluator.HIGH_THRESHOLD);
        Account before = [SELECT Id, Expansion_Potential__c, Account_Tier_Label__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Account_Tier_Label__c);

        PartnerTieringEvaluator.stampBands(new List<Account>{ before });

        Account after = [SELECT Id, Account_Tier_Label__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(PartnerTieringEvaluator.BAND_HIGH, after.Account_Tier_Label__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Account record = sampleRecord(PartnerTieringEvaluator.MEDIUM_THRESHOLD);

        Assert.areEqual(PartnerTieringEvaluator.BAND_MEDIUM, PartnerTieringEvaluator.bandForRecord(record.Id));
        Assert.isNull(PartnerTieringEvaluator.bandForRecord(null));
    }
}
