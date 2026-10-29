@IsTest
private with sharing class SegmentAssignmentEvaluator_Test {

    private static Account sampleRecord(Decimal value) {
        Account record = new Account(Name = 'Sample Account', Seat_Count__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(SegmentAssignmentEvaluator.BAND_HIGH, SegmentAssignmentEvaluator.bandFor(SegmentAssignmentEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(SegmentAssignmentEvaluator.BAND_MEDIUM, SegmentAssignmentEvaluator.bandFor(SegmentAssignmentEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(SegmentAssignmentEvaluator.BAND_LOW, SegmentAssignmentEvaluator.bandFor(SegmentAssignmentEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(SegmentAssignmentEvaluator.BAND_NONE, SegmentAssignmentEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Account high = sampleRecord(SegmentAssignmentEvaluator.HIGH_THRESHOLD);
        Account low = sampleRecord(SegmentAssignmentEvaluator.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = SegmentAssignmentEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(SegmentAssignmentEvaluator.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(SegmentAssignmentEvaluator.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, SegmentAssignmentEvaluator.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Account record = sampleRecord(SegmentAssignmentEvaluator.HIGH_THRESHOLD);
        Account before = [SELECT Id, Seat_Count__c, Account_Tier_Label__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Account_Tier_Label__c);

        SegmentAssignmentEvaluator.stampBands(new List<Account>{ before });

        Account after = [SELECT Id, Account_Tier_Label__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(SegmentAssignmentEvaluator.BAND_HIGH, after.Account_Tier_Label__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Account record = sampleRecord(SegmentAssignmentEvaluator.MEDIUM_THRESHOLD);

        Assert.areEqual(SegmentAssignmentEvaluator.BAND_MEDIUM, SegmentAssignmentEvaluator.bandForRecord(record.Id));
        Assert.isNull(SegmentAssignmentEvaluator.bandForRecord(null));
    }
}
