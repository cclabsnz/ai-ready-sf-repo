@IsTest
private with sharing class NurtureCadenceService_Test {

    private static Lead sampleRecord(Decimal value) {
        Lead record = new Lead(LastName = 'Sample Lead', Company = 'Sample Company', Intent_Score__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(NurtureCadenceService.BAND_HIGH, NurtureCadenceService.bandFor(NurtureCadenceService.HIGH_THRESHOLD));
        Assert.areEqual(NurtureCadenceService.BAND_MEDIUM, NurtureCadenceService.bandFor(NurtureCadenceService.MEDIUM_THRESHOLD));
        Assert.areEqual(NurtureCadenceService.BAND_LOW, NurtureCadenceService.bandFor(NurtureCadenceService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(NurtureCadenceService.BAND_NONE, NurtureCadenceService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Lead high = sampleRecord(NurtureCadenceService.HIGH_THRESHOLD);
        Lead low = sampleRecord(NurtureCadenceService.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = NurtureCadenceService.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(NurtureCadenceService.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(NurtureCadenceService.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, NurtureCadenceService.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Lead record = sampleRecord(NurtureCadenceService.HIGH_THRESHOLD);
        Lead before = [SELECT Id, Intent_Score__c, Follow_Up_Priority__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Follow_Up_Priority__c);

        NurtureCadenceService.stampBands(new List<Lead>{ before });

        Lead after = [SELECT Id, Follow_Up_Priority__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(NurtureCadenceService.BAND_HIGH, after.Follow_Up_Priority__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Lead record = sampleRecord(NurtureCadenceService.MEDIUM_THRESHOLD);

        Assert.areEqual(NurtureCadenceService.BAND_MEDIUM, NurtureCadenceService.bandForRecord(record.Id));
        Assert.isNull(NurtureCadenceService.bandForRecord(null));
    }
}
