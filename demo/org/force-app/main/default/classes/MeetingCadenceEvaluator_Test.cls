@IsTest
private with sharing class MeetingCadenceEvaluator_Test {

    private static Contact sampleRecord(Decimal value) {
        Contact record = new Contact(LastName = 'Sample Contact', Meeting_Cadence_Days__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(MeetingCadenceEvaluator.BAND_HIGH, MeetingCadenceEvaluator.bandFor(MeetingCadenceEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(MeetingCadenceEvaluator.BAND_MEDIUM, MeetingCadenceEvaluator.bandFor(MeetingCadenceEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(MeetingCadenceEvaluator.BAND_LOW, MeetingCadenceEvaluator.bandFor(MeetingCadenceEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(MeetingCadenceEvaluator.BAND_NONE, MeetingCadenceEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Contact high = sampleRecord(MeetingCadenceEvaluator.HIGH_THRESHOLD);
        Contact low = sampleRecord(MeetingCadenceEvaluator.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = MeetingCadenceEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(MeetingCadenceEvaluator.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(MeetingCadenceEvaluator.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, MeetingCadenceEvaluator.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Contact record = sampleRecord(MeetingCadenceEvaluator.HIGH_THRESHOLD);
        Contact before = [SELECT Id, Meeting_Cadence_Days__c, Outreach_Priority__c FROM Contact WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Outreach_Priority__c);

        MeetingCadenceEvaluator.stampBands(new List<Contact>{ before });

        Contact after = [SELECT Id, Outreach_Priority__c FROM Contact WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(MeetingCadenceEvaluator.BAND_HIGH, after.Outreach_Priority__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Contact record = sampleRecord(MeetingCadenceEvaluator.MEDIUM_THRESHOLD);

        Assert.areEqual(MeetingCadenceEvaluator.BAND_MEDIUM, MeetingCadenceEvaluator.bandForRecord(record.Id));
        Assert.isNull(MeetingCadenceEvaluator.bandForRecord(null));
    }
}
