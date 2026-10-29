@IsTest
private with sharing class ForecastAdjustEvaluator_Test {

    /**
     * A standard user holding the Opportunity_Pipeline_Access permission set.
     * Fields deployed through the Metadata API grant field access to nobody, so the record work
     * below runs as this user.
     */
    private static User areaUser() {
        Profile p = [SELECT Id FROM Profile WHERE Name = 'Standard User' LIMIT 1];
        String unique = String.valueOf(Datetime.now().getTime()) + String.valueOf(Crypto.getRandomInteger()).replace('-', '');
        User u = new User(
            ProfileId = p.Id,
            LastName = 'Sample Planner',
            Alias = 'smplusr',
            Email = 'sample.planner@example.com',
            Username = 'sample.planner.' + unique + '@example.com',
            TimeZoneSidKey = 'Pacific/Auckland',
            LocaleSidKey = 'en_NZ',
            EmailEncodingKey = 'UTF-8',
            LanguageLocaleKey = 'en_US'
        );
        PermissionSet ps = [SELECT Id FROM PermissionSet WHERE Name = 'Opportunity_Pipeline_Access' LIMIT 1];
        // Setup objects in their own runAs block, so the record inserts that follow do not raise
        // MIXED_DML_OPERATION.
        System.runAs(new User(Id = UserInfo.getUserId())) {
            insert u;
            insert new PermissionSetAssignment(AssigneeId = u.Id, PermissionSetId = ps.Id);
        }
        return u;
    }

    private static Opportunity sampleRecord(Decimal value) {
        Opportunity record = new Opportunity(Name = 'Sample Opportunity', StageName = 'Prospecting', CloseDate = Date.today().addDays(30), Forecast_Adjustment__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(ForecastAdjustEvaluator.BAND_HIGH, ForecastAdjustEvaluator.bandFor(ForecastAdjustEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(ForecastAdjustEvaluator.BAND_MEDIUM, ForecastAdjustEvaluator.bandFor(ForecastAdjustEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(ForecastAdjustEvaluator.BAND_LOW, ForecastAdjustEvaluator.bandFor(ForecastAdjustEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(ForecastAdjustEvaluator.BAND_NONE, ForecastAdjustEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        System.runAs(areaUser()) {
            Opportunity high = sampleRecord(ForecastAdjustEvaluator.HIGH_THRESHOLD);
            Opportunity low = sampleRecord(ForecastAdjustEvaluator.MEDIUM_THRESHOLD - 1);

            Map<Id, String> bands = ForecastAdjustEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

            Assert.areEqual(2, bands.size());
            Assert.areEqual(ForecastAdjustEvaluator.BAND_HIGH, bands.get(high.Id));
            Assert.areEqual(ForecastAdjustEvaluator.BAND_LOW, bands.get(low.Id));
            Assert.areEqual(0, ForecastAdjustEvaluator.bandsFor(new Set<Id>()).size());
        }
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        System.runAs(areaUser()) {
            Opportunity record = sampleRecord(ForecastAdjustEvaluator.HIGH_THRESHOLD);
            Opportunity before = [SELECT Id, Forecast_Adjustment__c, Risk_Band__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
            Assert.isNull(before.Risk_Band__c);

            ForecastAdjustEvaluator.stampBands(new List<Opportunity>{ before });

            Opportunity after = [SELECT Id, Risk_Band__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
            Assert.areEqual(ForecastAdjustEvaluator.BAND_HIGH, after.Risk_Band__c);
        }
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        System.runAs(areaUser()) {
            Opportunity record = sampleRecord(ForecastAdjustEvaluator.MEDIUM_THRESHOLD);

            Assert.areEqual(ForecastAdjustEvaluator.BAND_MEDIUM, ForecastAdjustEvaluator.bandForRecord(record.Id));
            Assert.isNull(ForecastAdjustEvaluator.bandForRecord(null));
        }
    }
}
