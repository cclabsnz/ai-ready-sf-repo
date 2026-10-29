// Plain SOQL and DML, matching LegacyCaseMerge, the deliberately aged class it tests.
@IsTest
private with sharing class LegacyCaseMerge_Test {

    @IsTest
    static void normalizeSubjectStripsPrefixes() {
        Assert.areEqual('printer jam', LegacyCaseMerge.normalizeSubject('  RE: Fwd: Printer Jam '));
        Assert.areEqual('', LegacyCaseMerge.normalizeSubject(null));
        Assert.areEqual('', LegacyCaseMerge.normalizeSubject('   '));
    }

    @IsTest
    static void groupBySubjectKeysOnNormalizedSubject() {
        List<Task> tasks = new List<Task>{
            new Task(Subject = 'Call back'),
            new Task(Subject = 'RE: call back'),
            new Task(Subject = 'Send quote'),
            new Task(Subject = '')
        };

        Map<String, List<Task>> groups = LegacyCaseMerge.groupBySubject(tasks);

        Assert.areEqual(2, groups.size());
        Assert.areEqual(2, groups.get('call back').size());
        Assert.areEqual(1, groups.get('send quote').size());
        Assert.areEqual(0, LegacyCaseMerge.groupBySubject(null).size());
    }

    @IsTest
    static void completeDuplicatesKeepsTheFirstTask() {
        Task first = new Task(Subject = 'Chase invoice', Status = 'Not Started');
        Task second = new Task(Subject = 'RE: Chase invoice', Status = 'Not Started');
        Task other = new Task(Subject = 'Book room', Status = 'Not Started');
        insert new List<Task>{ first, second, other };

        List<Task> completed = LegacyCaseMerge.completeDuplicates(new List<Task>{ first, second, other });

        Assert.areEqual(1, completed.size());
        Assert.areEqual(second.Id, completed[0].Id);
        Map<Id, Task> stored = new Map<Id, Task>(
            [SELECT Id, Status FROM Task WHERE Id IN :new Set<Id>{ first.Id, second.Id, other.Id }]);
        Assert.areEqual('Not Started', stored.get(first.Id).Status);
        Assert.areEqual('Completed', stored.get(second.Id).Status);
        Assert.areEqual('Not Started', stored.get(other.Id).Status);
    }
}
