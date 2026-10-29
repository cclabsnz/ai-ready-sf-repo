@IsTest
private class CaseAssignmentService_Test {

    private static User newUser(String lastName, Boolean active) {
        Profile p = [SELECT Id FROM Profile WHERE Name = 'Standard User' LIMIT 1];
        String unique = String.valueOf(Datetime.now().getTime()) + String.valueOf(Crypto.getRandomInteger()).replace('-', '');
        return new User(
            ProfileId = p.Id,
            LastName = lastName,
            Alias = 'asnagt',
            Email = 'assignment.agent@example.com',
            Username = 'assignment.agent.' + unique + '@example.com',
            TimeZoneSidKey = 'Pacific/Auckland',
            LocaleSidKey = 'en_NZ',
            EmailEncodingKey = 'UTF-8',
            LanguageLocaleKey = 'en_US',
            IsActive = active
        );
    }

    /** Two active agents and one inactive user, all members of the Escalation_Agents queue. */
    private static List<User> queueMembers() {
        User first = newUser('Queue Agent One', true);
        User second = newUser('Queue Agent Two', true);
        User inactive = newUser('Queue Agent Inactive', false);
        List<User> users = new List<User>{ first, second, inactive };
        Group queue = [SELECT Id FROM Group WHERE DeveloperName = :CaseAssignmentService.AGENT_QUEUE AND Type = 'Queue' LIMIT 1];
        PermissionSet ps = [SELECT Id FROM PermissionSet WHERE Name = 'Service_Agent' LIMIT 1];
        // Setup objects (User, PermissionSetAssignment, GroupMember) in their own runAs block, so
        // the Case inserts that follow do not raise MIXED_DML_OPERATION.
        System.runAs(new User(Id = UserInfo.getUserId())) {
            insert users;
            insert new List<PermissionSetAssignment>{
                new PermissionSetAssignment(AssigneeId = first.Id, PermissionSetId = ps.Id),
                new PermissionSetAssignment(AssigneeId = second.Id, PermissionSetId = ps.Id)
            };
            List<GroupMember> members = new List<GroupMember>();
            for (User u : users) {
                members.add(new GroupMember(GroupId = queue.Id, UserOrGroupId = u.Id));
            }
            insert members;
        }
        return users;
    }

    private static List<Case> cases(User owner, Integer n) {
        List<Case> rows = new List<Case>();
        for (Integer i = 0; i < n; i++) {
            rows.add(new Case(Subject = 'Assignment case ' + i, OwnerId = owner.Id, Status = 'Working', Origin = 'Web'));
        }
        insert rows;
        return rows;
    }

    @IsTest
    static void poolComesFromActiveQueueMembers() {
        List<User> users = queueMembers();

        List<Id> pool;
        System.runAs(users[0]) {
            pool = CaseAssignmentService.agentPool();
        }

        Set<Id> poolSet = new Set<Id>(pool);
        Assert.isTrue(poolSet.contains(users[0].Id), 'active member one is in the pool');
        Assert.isTrue(poolSet.contains(users[1].Id), 'active member two is in the pool');
        Assert.isFalse(poolSet.contains(users[2].Id), 'inactive member is left out');
        Assert.areEqual(pool.size(), poolSet.size(), 'no duplicates');
    }

    @IsTest
    static void casesBackToNewAreSpreadAcrossQueuePool() {
        List<User> users = queueMembers();
        List<Case> rows = cases(users[0], 4);
        for (Case c : rows) {
            c.Status = CaseAssignmentService.STATUS_NEW;
        }

        List<Id> pool;
        Test.startTest();
        System.runAs(users[0]) {
            pool = CaseAssignmentService.agentPool();
            update rows;
        }
        Test.stopTest();

        Set<Id> poolSet = new Set<Id>(pool);
        Set<Id> owners = new Set<Id>();
        for (Case c : [SELECT OwnerId FROM Case WHERE Id IN :rows]) {
            Assert.isTrue(poolSet.contains(c.OwnerId), 'every case goes to a pool member');
            owners.add(c.OwnerId);
        }
        Assert.areEqual(Math.min(4, pool.size()), owners.size(), 'round-robin uses as many agents as it can');
        Assert.isFalse(owners.contains(users[2].Id));
    }

    @IsTest
    static void otherStatusChangesKeepOwner() {
        List<User> users = queueMembers();
        List<Case> rows = cases(users[0], 3);
        for (Case c : rows) {
            c.Status = 'Escalated';
        }

        Test.startTest();
        update rows;
        Test.stopTest();

        Assert.areEqual(3, [SELECT COUNT() FROM Case WHERE Id IN :rows AND OwnerId = :users[0].Id]);
    }

    @IsTest
    static void emptyPoolLeavesOwner() {
        User owner = queueMembers()[0];
        List<Case> rows = cases(owner, 2);
        CaseAssignmentService.agentPoolOverride = new List<Id>();
        for (Case c : rows) {
            c.Status = CaseAssignmentService.STATUS_NEW;
        }

        Test.startTest();
        update rows;
        Test.stopTest();

        Assert.areEqual(2, [SELECT COUNT() FROM Case WHERE Id IN :rows AND OwnerId = :owner.Id]);
    }
}
