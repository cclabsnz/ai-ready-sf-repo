@IsTest
private with sharing class QualificationReviewService_Test {

    private static Lead sampleRecord(Decimal value) {
        Lead record = new Lead(LastName = 'Sample Lead', Company = 'Sample Company', Lead_Fit_Score__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(QualificationReviewService.BAND_HIGH, QualificationReviewService.bandFor(QualificationReviewService.HIGH_THRESHOLD));
        Assert.areEqual(QualificationReviewService.BAND_MEDIUM, QualificationReviewService.bandFor(QualificationReviewService.MEDIUM_THRESHOLD));
        Assert.areEqual(QualificationReviewService.BAND_LOW, QualificationReviewService.bandFor(QualificationReviewService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(QualificationReviewService.BAND_NONE, QualificationReviewService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Lead high = sampleRecord(QualificationReviewService.HIGH_THRESHOLD);
        Lead low = sampleRecord(QualificationReviewService.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = QualificationReviewService.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(QualificationReviewService.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(QualificationReviewService.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, QualificationReviewService.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Lead record = sampleRecord(QualificationReviewService.HIGH_THRESHOLD);
        Lead before = [SELECT Id, Lead_Fit_Score__c, Follow_Up_Priority__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Follow_Up_Priority__c);

        QualificationReviewService.stampBands(new List<Lead>{ before });

        Lead after = [SELECT Id, Follow_Up_Priority__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(QualificationReviewService.BAND_HIGH, after.Follow_Up_Priority__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Lead record = sampleRecord(QualificationReviewService.MEDIUM_THRESHOLD);

        Assert.areEqual(QualificationReviewService.BAND_MEDIUM, QualificationReviewService.bandForRecord(record.Id));
        Assert.isNull(QualificationReviewService.bandForRecord(null));
    }
}
