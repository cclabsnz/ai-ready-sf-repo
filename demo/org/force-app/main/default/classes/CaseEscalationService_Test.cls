@IsTest
private class CaseEscalationService_Test {

    private static User agentWith(String permissionSetName) {
        Profile p = [SELECT Id FROM Profile WHERE Name = 'Standard User' LIMIT 1];
        String unique = String.valueOf(Datetime.now().getTime()) + String.valueOf(Crypto.getRandomInteger()).replace('-', '');
        User u = new User(
            ProfileId = p.Id,
            LastName = 'Escalation Agent',
            Alias = 'escagt',
            Email = 'escalation.agent@example.com',
            Username = 'escalation.agent.' + unique + '@example.com',
            TimeZoneSidKey = 'Pacific/Auckland',
            LocaleSidKey = 'en_NZ',
            EmailEncodingKey = 'UTF-8',
            LanguageLocaleKey = 'en_US'
        );
        PermissionSet ps = [SELECT Id FROM PermissionSet WHERE Name = :permissionSetName LIMIT 1];
        // Setup objects (User, PermissionSetAssignment) in their own runAs block, so the
        // Account/Entitlement/Case inserts that follow do not raise MIXED_DML_OPERATION.
        System.runAs(new User(Id = UserInfo.getUserId())) {
            insert u;
            insert new PermissionSetAssignment(AssigneeId = u.Id, PermissionSetId = ps.Id);
        }
        return u;
    }

    private static Case openCase(User owner, String serviceLevel, Decimal slaHours, Integer hoursAgo) {
        Account a = new Account(Name = 'Sample Account ' + serviceLevel, OwnerId = owner.Id, Service_Level__c = serviceLevel);
        insert a;
        Entitlement e = new Entitlement(Name = 'Sample Entitlement', AccountId = a.Id,
                                        StartDate = Date.today().addDays(-30), Premium_SLA_Hours__c = slaHours);
        insert e;
        Case c = new Case(Subject = 'Sample case', AccountId = a.Id, EntitlementId = e.Id,
                          OwnerId = owner.Id, Status = 'Working', Origin = 'Web');
        insert c;
        Test.setCreatedDate(c.Id, Datetime.now().addHours(-hoursAgo));
        return c;
    }

    @IsTest
    static void levelForStandardIsLevel1() {
        Assert.areEqual(CaseEscalationService.LEVEL_1, CaseEscalationService.levelFor('Standard', 4, 100));
        Assert.areEqual(CaseEscalationService.LEVEL_1, CaseEscalationService.levelFor(null, null, 0));
    }

    @IsTest
    static void levelForPremiumDependsOnSla() {
        Assert.areEqual(CaseEscalationService.LEVEL_1, CaseEscalationService.levelFor('Premium', 4, 3.9));
        Assert.areEqual(CaseEscalationService.LEVEL_2, CaseEscalationService.levelFor('Premium', 4, 4));
        Assert.areEqual(CaseEscalationService.LEVEL_1, CaseEscalationService.levelFor('Premium', null, 50),
                        'premium without an SLA stays at Level 1');
    }

    @IsTest
    static void hoursBetweenHandlesNulls() {
        Datetime t = Datetime.newInstanceGmt(2026, 1, 1, 0, 0, 0);
        Decimal six = CaseEscalationService.hoursBetween(t, t.addHours(6));
        Decimal half = CaseEscalationService.hoursBetween(t, t.addMinutes(30));
        Decimal none = CaseEscalationService.hoursBetween(null, t);
        // Compare Decimals numerically; Assert.areEqual(Integer, Decimal) would compare types too.
        Assert.isTrue(six == 6.0, 'expected 6 hours, got ' + six);
        Assert.isTrue(half == 0.5, 'expected 0.5 hours, got ' + half);
        Assert.isTrue(none == 0.0, 'expected 0 hours for a null start, got ' + none);
    }

    @IsTest
    static void premiumCaseOverSlaEscalatesToLevel2() {
        User agent = agentWith('Service_Agent');
        Case c = openCase(agent, 'Premium', 4, 10);

        Test.startTest();
        System.runAs(agent) {
            update new Case(Id = c.Id, IsEscalated = true, Escalation_Reason__c = 'Outage for the whole site');
        }
        Test.stopTest();

        Case after = [SELECT Escalation_Level__c FROM Case WHERE Id = :c.Id];
        Assert.areEqual(CaseEscalationService.LEVEL_2, after.Escalation_Level__c);
        List<CaseComment> comments = [SELECT CommentBody, IsPublished FROM CaseComment WHERE ParentId = :c.Id];
        Assert.areEqual(1, comments.size());
        Assert.isFalse(comments[0].IsPublished);
        Assert.isTrue(comments[0].CommentBody.contains('Outage for the whole site'));
    }

    @IsTest
    static void standardCaseEscalatesToLevel1() {
        User agent = agentWith('Service_Agent');
        Case c = openCase(agent, 'Standard', 4, 10);

        Test.startTest();
        System.runAs(agent) {
            update new Case(Id = c.Id, IsEscalated = true);
        }
        Test.stopTest();

        Assert.areEqual(CaseEscalationService.LEVEL_1,
                        [SELECT Escalation_Level__c FROM Case WHERE Id = :c.Id].Escalation_Level__c);
    }

    @IsTest
    static void premiumCasesFiltersOnServiceLevel() {
        User agent = agentWith('Service_Agent');
        Case premium = openCase(agent, 'Premium', 4, 1);
        Case standard = openCase(agent, 'Standard', 4, 1);

        List<Case> result;
        System.runAs(agent) {
            result = CaseEscalationService.premiumCases(new Set<Id>{ premium.Id, standard.Id });
        }

        Assert.areEqual(1, result.size());
        Assert.areEqual(premium.Id, result[0].Id);
        Assert.areEqual(0, CaseEscalationService.premiumCases(new Set<Id>()).size());
    }

    @IsTest
    static void getEscalationStateReportsSlaBreach() {
        User agent = agentWith('Service_Agent');
        Case c = openCase(agent, 'Premium', 4, 10);

        CaseEscalationService.EscalationState state;
        System.runAs(agent) {
            state = CaseEscalationService.getEscalationState(c.Id);
        }

        Assert.isNotNull(state);
        Assert.isTrue(state.isPremium);
        Assert.areEqual('Premium', state.serviceLevel);
        Assert.isTrue(state.premiumSlaHours == 4.0, 'expected 4 SLA hours, got ' + state.premiumSlaHours);
        Assert.isTrue(state.slaBreached);
        Assert.areEqual(CaseEscalationService.LEVEL_NONE, state.level);
    }
}
