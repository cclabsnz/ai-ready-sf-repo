@IsTest
private with sharing class IntentSignalService_Test {

    private static Lead sampleRecord(Decimal value) {
        Lead record = new Lead(LastName = 'Sample Lead', Company = 'Sample Company', Intent_Score__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(IntentSignalService.BAND_HIGH, IntentSignalService.bandFor(IntentSignalService.HIGH_THRESHOLD));
        Assert.areEqual(IntentSignalService.BAND_MEDIUM, IntentSignalService.bandFor(IntentSignalService.MEDIUM_THRESHOLD));
        Assert.areEqual(IntentSignalService.BAND_LOW, IntentSignalService.bandFor(IntentSignalService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(IntentSignalService.BAND_NONE, IntentSignalService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Lead high = sampleRecord(IntentSignalService.HIGH_THRESHOLD);
        Lead low = sampleRecord(IntentSignalService.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = IntentSignalService.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(IntentSignalService.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(IntentSignalService.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, IntentSignalService.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Lead record = sampleRecord(IntentSignalService.HIGH_THRESHOLD);
        Lead before = [SELECT Id, Intent_Score__c, Lead_Tier_Label__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Lead_Tier_Label__c);

        IntentSignalService.stampBands(new List<Lead>{ before });

        Lead after = [SELECT Id, Lead_Tier_Label__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(IntentSignalService.BAND_HIGH, after.Lead_Tier_Label__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Lead record = sampleRecord(IntentSignalService.MEDIUM_THRESHOLD);

        Assert.areEqual(IntentSignalService.BAND_MEDIUM, IntentSignalService.bandForRecord(record.Id));
        Assert.isNull(IntentSignalService.bandForRecord(null));
    }
}
