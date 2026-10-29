@IsTest
private with sharing class ReviewCadenceEvaluator_Test {

    /**
     * A standard user holding the Account_Planning_Access permission set.
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
        PermissionSet ps = [SELECT Id FROM PermissionSet WHERE Name = 'Account_Planning_Access' LIMIT 1];
        // Setup objects in their own runAs block, so the record inserts that follow do not raise
        // MIXED_DML_OPERATION.
        System.runAs(new User(Id = UserInfo.getUserId())) {
            insert u;
            insert new PermissionSetAssignment(AssigneeId = u.Id, PermissionSetId = ps.Id);
        }
        return u;
    }

    private static Account sampleRecord(Decimal value) {
        Account record = new Account(Name = 'Sample Account', Health_Score__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(ReviewCadenceEvaluator.BAND_HIGH, ReviewCadenceEvaluator.bandFor(ReviewCadenceEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(ReviewCadenceEvaluator.BAND_MEDIUM, ReviewCadenceEvaluator.bandFor(ReviewCadenceEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(ReviewCadenceEvaluator.BAND_LOW, ReviewCadenceEvaluator.bandFor(ReviewCadenceEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(ReviewCadenceEvaluator.BAND_NONE, ReviewCadenceEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        System.runAs(areaUser()) {
            Account high = sampleRecord(ReviewCadenceEvaluator.HIGH_THRESHOLD);
            Account low = sampleRecord(ReviewCadenceEvaluator.MEDIUM_THRESHOLD - 1);

            Map<Id, String> bands = ReviewCadenceEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

            Assert.areEqual(2, bands.size());
            Assert.areEqual(ReviewCadenceEvaluator.BAND_HIGH, bands.get(high.Id));
            Assert.areEqual(ReviewCadenceEvaluator.BAND_LOW, bands.get(low.Id));
            Assert.areEqual(0, ReviewCadenceEvaluator.bandsFor(new Set<Id>()).size());
        }
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        System.runAs(areaUser()) {
            Account record = sampleRecord(ReviewCadenceEvaluator.HIGH_THRESHOLD);
            Account before = [SELECT Id, Health_Score__c, Health_Band__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
            Assert.isNull(before.Health_Band__c);

            ReviewCadenceEvaluator.stampBands(new List<Account>{ before });

            Account after = [SELECT Id, Health_Band__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
            Assert.areEqual(ReviewCadenceEvaluator.BAND_HIGH, after.Health_Band__c);
        }
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        System.runAs(areaUser()) {
            Account record = sampleRecord(ReviewCadenceEvaluator.MEDIUM_THRESHOLD);

            Assert.areEqual(ReviewCadenceEvaluator.BAND_MEDIUM, ReviewCadenceEvaluator.bandForRecord(record.Id));
            Assert.isNull(ReviewCadenceEvaluator.bandForRecord(null));
        }
    }
}
