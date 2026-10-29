@IsTest
private with sharing class ReferralTrackingService_Test {

    private static Lead sampleRecord(Decimal value) {
        Lead record = new Lead(LastName = 'Sample Lead', Company = 'Sample Company', Budget_Estimate__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(ReferralTrackingService.BAND_HIGH, ReferralTrackingService.bandFor(ReferralTrackingService.HIGH_THRESHOLD));
        Assert.areEqual(ReferralTrackingService.BAND_MEDIUM, ReferralTrackingService.bandFor(ReferralTrackingService.MEDIUM_THRESHOLD));
        Assert.areEqual(ReferralTrackingService.BAND_LOW, ReferralTrackingService.bandFor(ReferralTrackingService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(ReferralTrackingService.BAND_NONE, ReferralTrackingService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Lead high = sampleRecord(ReferralTrackingService.HIGH_THRESHOLD);
        Lead low = sampleRecord(ReferralTrackingService.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = ReferralTrackingService.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(ReferralTrackingService.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(ReferralTrackingService.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, ReferralTrackingService.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Lead record = sampleRecord(ReferralTrackingService.HIGH_THRESHOLD);
        Lead before = [SELECT Id, Budget_Estimate__c, Follow_Up_Priority__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Follow_Up_Priority__c);

        ReferralTrackingService.stampBands(new List<Lead>{ before });

        Lead after = [SELECT Id, Follow_Up_Priority__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(ReferralTrackingService.BAND_HIGH, after.Follow_Up_Priority__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Lead record = sampleRecord(ReferralTrackingService.MEDIUM_THRESHOLD);

        Assert.areEqual(ReferralTrackingService.BAND_MEDIUM, ReferralTrackingService.bandForRecord(record.Id));
        Assert.isNull(ReferralTrackingService.bandForRecord(null));
    }
}
