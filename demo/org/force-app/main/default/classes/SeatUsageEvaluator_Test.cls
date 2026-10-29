@IsTest
private with sharing class SeatUsageEvaluator_Test {

    private static Account sampleRecord(Decimal value) {
        Account record = new Account(Name = 'Sample Account', Seat_Count__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(SeatUsageEvaluator.BAND_HIGH, SeatUsageEvaluator.bandFor(SeatUsageEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(SeatUsageEvaluator.BAND_MEDIUM, SeatUsageEvaluator.bandFor(SeatUsageEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(SeatUsageEvaluator.BAND_LOW, SeatUsageEvaluator.bandFor(SeatUsageEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(SeatUsageEvaluator.BAND_NONE, SeatUsageEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Account high = sampleRecord(SeatUsageEvaluator.HIGH_THRESHOLD);
        Account low = sampleRecord(SeatUsageEvaluator.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = SeatUsageEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(SeatUsageEvaluator.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(SeatUsageEvaluator.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, SeatUsageEvaluator.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Account record = sampleRecord(SeatUsageEvaluator.HIGH_THRESHOLD);
        Account before = [SELECT Id, Seat_Count__c, Health_Band__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Health_Band__c);

        SeatUsageEvaluator.stampBands(new List<Account>{ before });

        Account after = [SELECT Id, Health_Band__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(SeatUsageEvaluator.BAND_HIGH, after.Health_Band__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Account record = sampleRecord(SeatUsageEvaluator.MEDIUM_THRESHOLD);

        Assert.areEqual(SeatUsageEvaluator.BAND_MEDIUM, SeatUsageEvaluator.bandForRecord(record.Id));
        Assert.isNull(SeatUsageEvaluator.bandForRecord(null));
    }
}
