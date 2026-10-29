@IsTest
private with sharing class FitAssessmentEvaluator_Test {

    private static Lead sampleRecord(Decimal value) {
        Lead record = new Lead(LastName = 'Sample Lead', Company = 'Sample Company', Lead_Fit_Score__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(FitAssessmentEvaluator.BAND_HIGH, FitAssessmentEvaluator.bandFor(FitAssessmentEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(FitAssessmentEvaluator.BAND_MEDIUM, FitAssessmentEvaluator.bandFor(FitAssessmentEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(FitAssessmentEvaluator.BAND_LOW, FitAssessmentEvaluator.bandFor(FitAssessmentEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(FitAssessmentEvaluator.BAND_NONE, FitAssessmentEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Lead high = sampleRecord(FitAssessmentEvaluator.HIGH_THRESHOLD);
        Lead low = sampleRecord(FitAssessmentEvaluator.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = FitAssessmentEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(FitAssessmentEvaluator.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(FitAssessmentEvaluator.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, FitAssessmentEvaluator.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Lead record = sampleRecord(FitAssessmentEvaluator.HIGH_THRESHOLD);
        Lead before = [SELECT Id, Lead_Fit_Score__c, Lead_Tier_Label__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Lead_Tier_Label__c);

        FitAssessmentEvaluator.stampBands(new List<Lead>{ before });

        Lead after = [SELECT Id, Lead_Tier_Label__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(FitAssessmentEvaluator.BAND_HIGH, after.Lead_Tier_Label__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Lead record = sampleRecord(FitAssessmentEvaluator.MEDIUM_THRESHOLD);

        Assert.areEqual(FitAssessmentEvaluator.BAND_MEDIUM, FitAssessmentEvaluator.bandForRecord(record.Id));
        Assert.isNull(FitAssessmentEvaluator.bandForRecord(null));
    }
}
