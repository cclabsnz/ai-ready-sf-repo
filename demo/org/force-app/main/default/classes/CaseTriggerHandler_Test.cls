@IsTest
private with sharing class CaseTriggerHandler_Test {

    private static User agent() {
        Profile p = [SELECT Id FROM Profile WHERE Name = 'Standard User' LIMIT 1];
        String unique = String.valueOf(Datetime.now().getTime()) + String.valueOf(Crypto.getRandomInteger()).replace('-', '');
        User u = new User(
            ProfileId = p.Id,
            LastName = 'Handler Agent',
            Alias = 'hdlagt',
            Email = 'handler.agent@example.com',
            Username = 'handler.agent.' + unique + '@example.com',
            TimeZoneSidKey = 'Pacific/Auckland',
            LocaleSidKey = 'en_NZ',
            EmailEncodingKey = 'UTF-8',
            LanguageLocaleKey = 'en_US'
        );
        PermissionSet ps = [SELECT Id FROM PermissionSet WHERE Name = 'Service_Agent' LIMIT 1];
        // Setup objects in their own runAs block, so the Case inserts that follow do not raise
        // MIXED_DML_OPERATION.
        System.runAs(new User(Id = UserInfo.getUserId())) {
            insert u;
            insert new PermissionSetAssignment(AssigneeId = u.Id, PermissionSetId = ps.Id);
        }
        return u;
    }

    private static List<Case> cases(User owner, Integer n, String status) {
        List<Case> rows = new List<Case>();
        for (Integer i = 0; i < n; i++) {
            rows.add(new Case(Subject = 'Handler case ' + i, OwnerId = owner.Id, Status = status, Origin = 'Phone'));
        }
        insert rows;
        return rows;
    }

    @IsTest
    static void escalationInBulkSetsLevelAndComment() {
        User u = agent();
        List<Case> rows = cases(u, 200, 'Working');
        for (Case c : rows) {
            c.IsEscalated = true;
        }

        Test.startTest();
        System.runAs(u) {
            update rows;
        }
        Test.stopTest();

        Assert.areEqual(200, [SELECT COUNT() FROM Case WHERE Escalation_Level__c = 'Level 1' AND Id IN :rows],
                        'cases with no account escalate to Level 1');
        Assert.areEqual(200, [SELECT COUNT() FROM CaseComment WHERE ParentId IN :rows]);
    }

    @IsTest
    static void caseBackToNewIsAssignedRoundRobin() {
        User u = agent();
        User other = agent();
        List<Case> rows = cases(u, 4, 'Working');
        CaseAssignmentService.agentPoolOverride = new List<Id>{ u.Id, other.Id };
        for (Case c : rows) {
            c.Status = 'New';
        }

        Test.startTest();
        update rows;
        Test.stopTest();

        Map<Id, Integer> perOwner = new Map<Id, Integer>();
        for (Case c : [SELECT OwnerId FROM Case WHERE Id IN :rows]) {
            perOwner.put(c.OwnerId, (perOwner.containsKey(c.OwnerId) ? perOwner.get(c.OwnerId) : 0) + 1);
        }
        Assert.areEqual(2, perOwner.get(u.Id));
        Assert.areEqual(2, perOwner.get(other.Id));
    }

    @IsTest
    static void unchangedCasesAreLeftAlone() {
        User u = agent();
        List<Case> rows = cases(u, 3, 'Working');
        for (Case c : rows) {
            c.Subject = c.Subject + ' (edited)';
        }

        Test.startTest();
        update rows;
        Test.stopTest();

        Assert.areEqual(0, [SELECT COUNT() FROM Case WHERE Id IN :rows AND Escalation_Level__c IN ('Level 1', 'Level 2')]);
        Assert.areEqual(0, [SELECT COUNT() FROM CaseComment WHERE ParentId IN :rows]);
        Assert.areEqual(3, [SELECT COUNT() FROM Case WHERE Id IN :rows AND OwnerId = :u.Id]);
    }

    @IsTest
    static void bypassSkipsAllWork() {
        User u = agent();
        List<Case> rows = cases(u, 2, 'Working');
        CaseTriggerHandler.bypass = true;
        for (Case c : rows) {
            c.IsEscalated = true;
            c.Escalation_Level__c = 'Level 1';
        }

        Test.startTest();
        update rows;
        Test.stopTest();

        Assert.areEqual(0, [SELECT COUNT() FROM CaseComment WHERE ParentId IN :rows]);
    }
}
