@IsTest
private class CaseAccountSummaryController_Test {

    private static User agent() {
        Profile p = [SELECT Id FROM Profile WHERE Name = 'Standard User' LIMIT 1];
        PermissionSet ps = [SELECT Id FROM PermissionSet WHERE Name = 'Service_Agent' LIMIT 1];
        String unique = String.valueOf(Datetime.now().getTime()) + String.valueOf(Crypto.getRandomInteger()).replace('-', '');
        User u = new User(
            ProfileId = p.Id,
            LastName = 'Summary Agent',
            Alias = 'sumagt',
            Email = 'summary.agent@example.com',
            Username = 'summary.agent.' + unique + '@example.com',
            TimeZoneSidKey = 'Pacific/Auckland',
            LocaleSidKey = 'en_NZ',
            EmailEncodingKey = 'UTF-8',
            LanguageLocaleKey = 'en_US'
        );
        // Setup objects in their own runAs block (avoids MIXED_DML_OPERATION).
        System.runAs(new User(Id = UserInfo.getUserId())) {
            insert u;
            insert new PermissionSetAssignment(AssigneeId = u.Id, PermissionSetId = ps.Id);
        }
        return u;
    }

    @IsTest
    static void summaryReturnsAccountFields() {
        User u = agent();
        Account a = new Account(Name = 'Summary Sample Account', OwnerId = u.Id, Type = 'Customer - Direct',
                                Industry = 'Technology', Rating = 'Hot', Phone = '555-0100');
        insert a;
        Case c = new Case(Subject = 'Summary case', AccountId = a.Id, OwnerId = u.Id, Status = 'Working', Origin = 'Phone');
        insert c;

        CaseAccountSummaryController.AccountSummary s;
        System.runAs(u) {
            s = CaseAccountSummaryController.getSummary(c.Id);
        }

        Assert.isNotNull(s);
        Assert.areEqual(a.Id, s.accountId);
        Assert.areEqual('Summary Sample Account', s.name);
        Assert.areEqual('Customer - Direct', s.type);
        Assert.areEqual('Technology', s.industry);
        Assert.areEqual('Hot', s.rating);
        Assert.areEqual('555-0100', s.phone);
        Assert.areEqual('Summary Agent', s.ownerName);
    }

    @IsTest
    static void caseWithoutAccountReturnsNull() {
        User u = agent();
        Case c = new Case(Subject = 'No account case', OwnerId = u.Id, Status = 'Working', Origin = 'Phone');
        insert c;

        System.runAs(u) {
            Assert.isNull(CaseAccountSummaryController.getSummary(c.Id));
        }
    }

    @IsTest
    static void unknownCaseReturnsNull() {
        Case c = new Case(Subject = 'Deleted case', Status = 'Working', Origin = 'Phone');
        insert c;
        Id goneId = c.Id;
        delete c;

        Assert.isNull(CaseAccountSummaryController.getSummary(goneId));
    }
}
