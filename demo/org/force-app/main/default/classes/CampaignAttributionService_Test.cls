@IsTest
private with sharing class CampaignAttributionService_Test {

    private static Lead sampleRecord(Decimal value) {
        Lead record = new Lead(LastName = 'Sample Lead', Company = 'Sample Company', Budget_Estimate__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(CampaignAttributionService.BAND_HIGH, CampaignAttributionService.bandFor(CampaignAttributionService.HIGH_THRESHOLD));
        Assert.areEqual(CampaignAttributionService.BAND_MEDIUM, CampaignAttributionService.bandFor(CampaignAttributionService.MEDIUM_THRESHOLD));
        Assert.areEqual(CampaignAttributionService.BAND_LOW, CampaignAttributionService.bandFor(CampaignAttributionService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(CampaignAttributionService.BAND_NONE, CampaignAttributionService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Lead high = sampleRecord(CampaignAttributionService.HIGH_THRESHOLD);
        Lead low = sampleRecord(CampaignAttributionService.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = CampaignAttributionService.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(CampaignAttributionService.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(CampaignAttributionService.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, CampaignAttributionService.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Lead record = sampleRecord(CampaignAttributionService.HIGH_THRESHOLD);
        Lead before = [SELECT Id, Budget_Estimate__c, Lead_Tier_Label__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Lead_Tier_Label__c);

        CampaignAttributionService.stampBands(new List<Lead>{ before });

        Lead after = [SELECT Id, Lead_Tier_Label__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(CampaignAttributionService.BAND_HIGH, after.Lead_Tier_Label__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Lead record = sampleRecord(CampaignAttributionService.MEDIUM_THRESHOLD);

        Assert.areEqual(CampaignAttributionService.BAND_MEDIUM, CampaignAttributionService.bandForRecord(record.Id));
        Assert.isNull(CampaignAttributionService.bandForRecord(null));
    }
}
