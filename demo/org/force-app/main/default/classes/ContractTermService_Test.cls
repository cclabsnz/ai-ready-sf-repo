@IsTest
private with sharing class ContractTermService_Test {

    private static Opportunity sampleRecord(Decimal value) {
        Opportunity record = new Opportunity(Name = 'Sample Opportunity', StageName = 'Prospecting', CloseDate = Date.today().addDays(30), Contract_Term_Months__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(ContractTermService.BAND_HIGH, ContractTermService.bandFor(ContractTermService.HIGH_THRESHOLD));
        Assert.areEqual(ContractTermService.BAND_MEDIUM, ContractTermService.bandFor(ContractTermService.MEDIUM_THRESHOLD));
        Assert.areEqual(ContractTermService.BAND_LOW, ContractTermService.bandFor(ContractTermService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(ContractTermService.BAND_NONE, ContractTermService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Opportunity high = sampleRecord(ContractTermService.HIGH_THRESHOLD);
        Opportunity low = sampleRecord(ContractTermService.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = ContractTermService.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(ContractTermService.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(ContractTermService.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, ContractTermService.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Opportunity record = sampleRecord(ContractTermService.HIGH_THRESHOLD);
        Opportunity before = [SELECT Id, Contract_Term_Months__c, Review_Status_Label__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Review_Status_Label__c);

        ContractTermService.stampBands(new List<Opportunity>{ before });

        Opportunity after = [SELECT Id, Review_Status_Label__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(ContractTermService.BAND_HIGH, after.Review_Status_Label__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Opportunity record = sampleRecord(ContractTermService.MEDIUM_THRESHOLD);

        Assert.areEqual(ContractTermService.BAND_MEDIUM, ContractTermService.bandForRecord(record.Id));
        Assert.isNull(ContractTermService.bandForRecord(null));
    }
}
