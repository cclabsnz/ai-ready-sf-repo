@IsTest
private with sharing class EscalationNotifier_Test {

    private static User agent() {
        Profile p = [SELECT Id FROM Profile WHERE Name = 'Standard User' LIMIT 1];
        PermissionSet ps = [SELECT Id FROM PermissionSet WHERE Name = 'Service_Agent' LIMIT 1];
        String unique = String.valueOf(Datetime.now().getTime()) + String.valueOf(Crypto.getRandomInteger()).replace('-', '');
        User u = new User(
            ProfileId = p.Id,
            LastName = 'Notifier Agent',
            Alias = 'ntfagt',
            Email = 'notifier.agent@example.com',
            Username = 'notifier.agent.' + unique + '@example.com',
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

    private static Case caseFor(User owner, String serviceLevel) {
        Account a = new Account(Name = 'Notifier Account ' + serviceLevel, OwnerId = owner.Id,
                                Service_Level__c = serviceLevel);
        insert a;
        Case c = new Case(Subject = 'Notifier case', AccountId = a.Id, OwnerId = owner.Id,
                          Status = 'Working', Origin = 'Web');
        insert c;
        return [SELECT Id, CaseNumber FROM Case WHERE Id = :c.Id];
    }

    private static EscalationNotifier.Request request(Id caseId) {
        EscalationNotifier.Request r = new EscalationNotifier.Request();
        r.caseId = caseId;
        return r;
    }

    @IsTest
    static void notifiesOwnerOfPremiumCaseOnly() {
        User u = agent();
        Case premium = caseFor(u, 'Premium');
        Case standard = caseFor(u, 'Standard');

        List<EscalationNotifier.Result> results;
        Test.startTest();
        System.runAs(u) {
            results = EscalationNotifier.notify(new List<EscalationNotifier.Request>{
                request(premium.Id), request(standard.Id), request(null)
            });
        }
        Test.stopTest();

        Assert.areEqual(3, results.size(), 'one result per request, in order');
        Assert.isTrue(results[0].notified);
        Assert.isFalse(results[1].notified);
        Assert.isFalse(results[2].notified);

        Set<Id> caseIds = new Set<Id>{ premium.Id, standard.Id };
        List<Task> tasks = [SELECT OwnerId, WhatId, Subject, Priority FROM Task WHERE WhatId IN :caseIds];
        Assert.areEqual(1, tasks.size());
        Assert.areEqual(premium.Id, tasks[0].WhatId);
        Assert.areEqual(u.Id, tasks[0].OwnerId);
        Assert.areEqual(EscalationNotifier.TASK_SUBJECT_PREFIX + premium.CaseNumber, tasks[0].Subject);
        Assert.areEqual('High', tasks[0].Priority);
    }

    @IsTest
    static void emptyRequestCreatesNothing() {
        List<EscalationNotifier.Result> results = EscalationNotifier.notify(new List<EscalationNotifier.Request>());
        Assert.areEqual(0, results.size());
        Assert.areEqual(0, [SELECT COUNT() FROM Task WHERE Subject LIKE 'Premium escalation:%']);
    }
}
