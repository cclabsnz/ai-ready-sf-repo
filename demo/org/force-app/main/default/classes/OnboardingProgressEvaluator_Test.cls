@IsTest
private with sharing class OnboardingProgressEvaluator_Test {

    private static Account sampleRecord(Decimal value) {
        Account record = new Account(Name = 'Sample Account', Health_Score__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(OnboardingProgressEvaluator.BAND_HIGH, OnboardingProgressEvaluator.bandFor(OnboardingProgressEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(OnboardingProgressEvaluator.BAND_MEDIUM, OnboardingProgressEvaluator.bandFor(OnboardingProgressEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(OnboardingProgressEvaluator.BAND_LOW, OnboardingProgressEvaluator.bandFor(OnboardingProgressEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(OnboardingProgressEvaluator.BAND_NONE, OnboardingProgressEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Account high = sampleRecord(OnboardingProgressEvaluator.HIGH_THRESHOLD);
        Account low = sampleRecord(OnboardingProgressEvaluator.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = OnboardingProgressEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(OnboardingProgressEvaluator.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(OnboardingProgressEvaluator.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, OnboardingProgressEvaluator.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Account record = sampleRecord(OnboardingProgressEvaluator.HIGH_THRESHOLD);
        Account before = [SELECT Id, Health_Score__c, Health_Band__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Health_Band__c);

        OnboardingProgressEvaluator.stampBands(new List<Account>{ before });

        Account after = [SELECT Id, Health_Band__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(OnboardingProgressEvaluator.BAND_HIGH, after.Health_Band__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Account record = sampleRecord(OnboardingProgressEvaluator.MEDIUM_THRESHOLD);

        Assert.areEqual(OnboardingProgressEvaluator.BAND_MEDIUM, OnboardingProgressEvaluator.bandForRecord(record.Id));
        Assert.isNull(OnboardingProgressEvaluator.bandForRecord(null));
    }
}
