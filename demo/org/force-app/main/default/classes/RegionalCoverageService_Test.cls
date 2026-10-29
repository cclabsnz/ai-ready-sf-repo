@IsTest
private with sharing class RegionalCoverageService_Test {

    private static Account sampleRecord(Decimal value) {
        Account record = new Account(Name = 'Sample Account', Seat_Count__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(RegionalCoverageService.BAND_HIGH, RegionalCoverageService.bandFor(RegionalCoverageService.HIGH_THRESHOLD));
        Assert.areEqual(RegionalCoverageService.BAND_MEDIUM, RegionalCoverageService.bandFor(RegionalCoverageService.MEDIUM_THRESHOLD));
        Assert.areEqual(RegionalCoverageService.BAND_LOW, RegionalCoverageService.bandFor(RegionalCoverageService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(RegionalCoverageService.BAND_NONE, RegionalCoverageService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Account high = sampleRecord(RegionalCoverageService.HIGH_THRESHOLD);
        Account low = sampleRecord(RegionalCoverageService.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = RegionalCoverageService.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(RegionalCoverageService.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(RegionalCoverageService.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, RegionalCoverageService.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Account record = sampleRecord(RegionalCoverageService.HIGH_THRESHOLD);
        Account before = [SELECT Id, Seat_Count__c, Account_Tier_Label__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Account_Tier_Label__c);

        RegionalCoverageService.stampBands(new List<Account>{ before });

        Account after = [SELECT Id, Account_Tier_Label__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(RegionalCoverageService.BAND_HIGH, after.Account_Tier_Label__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Account record = sampleRecord(RegionalCoverageService.MEDIUM_THRESHOLD);

        Assert.areEqual(RegionalCoverageService.BAND_MEDIUM, RegionalCoverageService.bandForRecord(record.Id));
        Assert.isNull(RegionalCoverageService.bandForRecord(null));
    }
}
