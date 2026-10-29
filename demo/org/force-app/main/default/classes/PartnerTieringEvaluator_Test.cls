@IsTest
private with sharing class PartnerTieringEvaluator_Test {

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
        Account record = new Account(Name = 'Sample Account', Expansion_Potential__c = value);
        Database.insert(record, AccessLevel.USER_MODE);
        return record;
    }

    @IsTest
    static void bandForAppliesThresholds() {
        Assert.areEqual(PartnerTieringEvaluator.BAND_HIGH, PartnerTieringEvaluator.bandFor(PartnerTieringEvaluator.HIGH_THRESHOLD));
        Assert.areEqual(PartnerTieringEvaluator.BAND_MEDIUM, PartnerTieringEvaluator.bandFor(PartnerTieringEvaluator.MEDIUM_THRESHOLD));
        Assert.areEqual(PartnerTieringEvaluator.BAND_LOW, PartnerTieringEvaluator.bandFor(PartnerTieringEvaluator.MEDIUM_THRESHOLD - 1));
        Assert.areEqual(PartnerTieringEvaluator.BAND_NONE, PartnerTieringEvaluator.bandFor(null));
    }

    @IsTest
    static void bandsForReadsStoredValues() {
        System.runAs(areaUser()) {
            Account high = sampleRecord(PartnerTieringEvaluator.HIGH_THRESHOLD);
            Account low = sampleRecord(PartnerTieringEvaluator.MEDIUM_THRESHOLD - 1);

            Map<Id, String> bands = PartnerTieringEvaluator.bandsFor(new Set<Id>{ high.Id, low.Id });

            Assert.areEqual(2, bands.size());
            Assert.areEqual(PartnerTieringEvaluator.BAND_HIGH, bands.get(high.Id));
            Assert.areEqual(PartnerTieringEvaluator.BAND_LOW, bands.get(low.Id));
            Assert.areEqual(0, PartnerTieringEvaluator.bandsFor(new Set<Id>()).size());
        }
    }

    @IsTest
    static void stampBandsWritesTheBand() {
        System.runAs(areaUser()) {
            Account record = sampleRecord(PartnerTieringEvaluator.HIGH_THRESHOLD);
            Account before = [SELECT Id, Expansion_Potential__c, Account_Planning_Band__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
            Assert.isNull(before.Account_Planning_Band__c);

            PartnerTieringEvaluator.stampBands(new List<Account>{ before });

            Account after = [SELECT Id, Account_Planning_Band__c FROM Account WHERE Id = :record.Id WITH USER_MODE];
            Assert.areEqual(PartnerTieringEvaluator.BAND_HIGH, after.Account_Planning_Band__c);
        }
    }

    @IsTest
    static void bandForRecordReturnsBandOrNull() {
        System.runAs(areaUser()) {
            Account record = sampleRecord(PartnerTieringEvaluator.MEDIUM_THRESHOLD);

            Assert.areEqual(PartnerTieringEvaluator.BAND_MEDIUM, PartnerTieringEvaluator.bandForRecord(record.Id));
            Assert.isNull(PartnerTieringEvaluator.bandForRecord(null));
        }
    }
}
