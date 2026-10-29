@IsTest
private with sharing class PricingExceptionService_Test {

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
        Opportunity record = new Opportunity(Name = 'Sample Opportunity', StageName = 'Prospecting', CloseDate = Date.today().addDays(30), Discount_Pct__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(PricingExceptionService.BAND_HIGH, PricingExceptionService.bandFor(PricingExceptionService.HIGH_THRESHOLD));
        Assert.areEqual(PricingExceptionService.BAND_MEDIUM, PricingExceptionService.bandFor(PricingExceptionService.MEDIUM_THRESHOLD));
        Assert.areEqual(PricingExceptionService.BAND_LOW, PricingExceptionService.bandFor(PricingExceptionService.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(PricingExceptionService.BAND_NONE, PricingExceptionService.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        System.runAs(areaUser()) {
            Opportunity high = sampleRecord(PricingExceptionService.HIGH_THRESHOLD);
            Opportunity low = sampleRecord(PricingExceptionService.MEDIUM_THRESHOLD - 1);

            Map<Id, String> bands = PricingExceptionService.bandsFor(new Set<Id>{ high.Id, low.Id });

            Assert.areEqual(2, bands.size());
            Assert.areEqual(PricingExceptionService.BAND_HIGH, bands.get(high.Id));
            Assert.areEqual(PricingExceptionService.BAND_LOW, bands.get(low.Id));
            Assert.areEqual(0, PricingExceptionService.bandsFor(new Set<Id>()).size());
        }
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        System.runAs(areaUser()) {
            Opportunity record = sampleRecord(PricingExceptionService.HIGH_THRESHOLD);
            Opportunity before = [SELECT Id, Discount_Pct__c, Review_Status_Label__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
            Assert.isNull(before.Review_Status_Label__c);

            PricingExceptionService.stampBands(new List<Opportunity>{ before });

            Opportunity after = [SELECT Id, Review_Status_Label__c FROM Opportunity WHERE Id = :record.Id WITH USER_MODE];
            Assert.areEqual(PricingExceptionService.BAND_HIGH, after.Review_Status_Label__c);
        }
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        System.runAs(areaUser()) {
            Opportunity record = sampleRecord(PricingExceptionService.MEDIUM_THRESHOLD);

            Assert.areEqual(PricingExceptionService.BAND_MEDIUM, PricingExceptionService.bandForRecord(record.Id));
            Assert.isNull(PricingExceptionService.bandForRecord(null));
        }
    }
}
