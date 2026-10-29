@IsTest
private with sharing class ConversionForecastEvaluator_Test {

    private static Lead sampleRecord(Decimal value) {
        Lead record = new Lead(LastName = 'Sample Lead', Company = 'Sample Company', Conversion_Likelihood_Pct__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(ConversionForecastEvaluator.BAND_HIGH, ConversionForecastEvaluator.bandFor(ConversionForecastEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(ConversionForecastEvaluator.BAND_MEDIUM, ConversionForecastEvaluator.bandFor(ConversionForecastEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(ConversionForecastEvaluator.BAND_LOW, ConversionForecastEvaluator.bandFor(ConversionForecastEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(ConversionForecastEvaluator.BAND_NONE, ConversionForecastEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        Lead high = sampleRecord(ConversionForecastEvaluator.HIGH_THRESHOLD);
        Lead low = sampleRecord(ConversionForecastEvaluator.MEDIUM_THRESHOLD - 1);

        Map<Id, String> bands = ConversionForecastEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

        Assert.areEqual(2, bands.size());
        Assert.areEqual(ConversionForecastEvaluator.BAND_HIGH, bands.get(high.Id));
        Assert.areEqual(ConversionForecastEvaluator.BAND_LOW, bands.get(low.Id));
        Assert.areEqual(0, ConversionForecastEvaluator.bandsFor(new Set<Id>()).size());
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        Lead record = sampleRecord(ConversionForecastEvaluator.HIGH_THRESHOLD);
        Lead before = [SELECT Id, Conversion_Likelihood_Pct__c, Lead_Tier_Label__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.isNull(before.Lead_Tier_Label__c);

        ConversionForecastEvaluator.stampBands(new List<Lead>{ before });

        Lead after = [SELECT Id, Lead_Tier_Label__c FROM Lead WHERE Id = :record.Id WITH USER_MODE];
        Assert.areEqual(ConversionForecastEvaluator.BAND_HIGH, after.Lead_Tier_Label__c);
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        Lead record = sampleRecord(ConversionForecastEvaluator.MEDIUM_THRESHOLD);

        Assert.areEqual(ConversionForecastEvaluator.BAND_MEDIUM, ConversionForecastEvaluator.bandForRecord(record.Id));
        Assert.isNull(ConversionForecastEvaluator.bandForRecord(null));
    }
}
