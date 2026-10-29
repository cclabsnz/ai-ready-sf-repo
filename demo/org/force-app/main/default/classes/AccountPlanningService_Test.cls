@IsTest
private with sharing class AccountPlanningService_Test {

    private static Account sampleRecord(Decimal value) {
        Account record = new Account(Name = 'Sample Account', Health_Score__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(AccountPlanningService.BAND_HIGH, AccountPlanningService.bandFor(AccountPlanningService.HIGH_THRESHOLD));
        Assert.areEqual(AccountPlanningService.BAND_MEDIUM, AccountPlanningService.bandFor(AccountPlanningService.MEDIUM_THRESHOLD));
        Assert.areEqual(AccountPlanningService.BAND_LOW, AccountPlanningService.bandFor(AccountPlanningService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(AccountPlanningService.BAND_NONE, AccountPlanningService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Account high = sampleRecord(AccountPlanningService.HIGH_THRESHOLD);
        Account low = sampleRecord(AccountPlanningService.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = AccountPlanningService.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(AccountPlanningService.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(AccountPlanningService.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, AccountPlanningService.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Account record = sampleRecord(AccountPlanningService.HIGH_THRESHOLD);
        Account before = [SELECT Id, Health_Score__c, Account_Tier_Label__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Account_Tier_Label__c);

        AccountPlanningService.stampBands(new List<Account>{ before });

        Account after = [SELECT Id, Account_Tier_Label__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(AccountPlanningService.BAND_HIGH, after.Account_Tier_Label__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Account record = sampleRecord(AccountPlanningService.MEDIUM_THRESHOLD);

        Assert.areEqual(AccountPlanningService.BAND_MEDIUM, AccountPlanningService.bandForRecord(record.Id));
        Assert.isNull(AccountPlanningService.bandForRecord(null));
    }
}
