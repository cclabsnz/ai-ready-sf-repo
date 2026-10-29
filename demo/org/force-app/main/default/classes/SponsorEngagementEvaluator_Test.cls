@IsTest
private with sharing class SponsorEngagementEvaluator_Test {

    private static Opportunity sampleRecord(Decimal value) {
        Opportunity record = new Opportunity(Name = 'Sample Opportunity', StageName = 'Prospecting', CloseDate = Date.today().addDays(30), Deal_Risk_Score__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(SponsorEngagementEvaluator.BAND_HIGH, SponsorEngagementEvaluator.bandFor(SponsorEngagementEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(SponsorEngagementEvaluator.BAND_MEDIUM, SponsorEngagementEvaluator.bandFor(SponsorEngagementEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(SponsorEngagementEvaluator.BAND_LOW, SponsorEngagementEvaluator.bandFor(SponsorEngagementEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(SponsorEngagementEvaluator.BAND_NONE, SponsorEngagementEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Opportunity high = sampleRecord(SponsorEngagementEvaluator.HIGH_THRESHOLD);
        Opportunity low = sampleRecord(SponsorEngagementEvaluator.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = SponsorEngagementEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(SponsorEngagementEvaluator.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(SponsorEngagementEvaluator.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, SponsorEngagementEvaluator.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Opportunity record = sampleRecord(SponsorEngagementEvaluator.HIGH_THRESHOLD);
        Opportunity before = [SELECT Id, Deal_Risk_Score__c, Risk_Band__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Risk_Band__c);

        SponsorEngagementEvaluator.stampBands(new List<Opportunity>{ before });

        Opportunity after = [SELECT Id, Risk_Band__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(SponsorEngagementEvaluator.BAND_HIGH, after.Risk_Band__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Opportunity record = sampleRecord(SponsorEngagementEvaluator.MEDIUM_THRESHOLD);

        Assert.areEqual(SponsorEngagementEvaluator.BAND_MEDIUM, SponsorEngagementEvaluator.bandForRecord(record.Id));
        Assert.isNull(SponsorEngagementEvaluator.bandForRecord(null));
    }
}
