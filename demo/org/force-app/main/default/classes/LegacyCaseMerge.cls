// Deliberate sign of age for the demo inventory: pinned to API 45.0, without sharing, and with no
// user-mode enforcement (plain SOQL and DML; the rule baseline in WS8 records it as debt).
// Why without sharing: the original merge job ran as a batch that had to see and complete every
// follow-up task, whoever owned it. Its one DML statement is plain too. Kept as is; nothing in the
// core Case flow calls it.
public without sharing class LegacyCaseMerge {

    /** Lower-cases a subject and strips reply and forward prefixes, so near-duplicates share a key. */
    public static String normalizeSubject(String subject) {
        if (String.isBlank(subject)) {
            return '';
        }
        String key = subject.trim().toLowerCase();
        while (key.startsWith('re:') || key.startsWith('fw:') || key.startsWith('fwd:')) {
            key = key.substring(key.indexOf(':') + 1).trim();
        }
        return key;
    }

    /** Groups tasks by normalized subject. Tasks with a blank subject are left out. */
    public static Map<String, List<Task>> groupBySubject(List<Task> tasks) {
        Map<String, List<Task>> groups = new Map<String, List<Task>>();
        if (tasks == null) {
            return groups;
        }
        for (Task t : tasks) {
            String key = normalizeSubject(t.Subject);
            if (key == '') {
                continue;
            }
            if (!groups.containsKey(key)) {
                groups.put(key, new List<Task>());
            }
            groups.get(key).add(t);
        }
        return groups;
    }

    /**
     * Completes every task that duplicates an earlier one with the same normalized subject and
     * returns them. The first task in each group survives. All updates go in one DML statement.
     */
    public static List<Task> completeDuplicates(List<Task> tasks) {
        List<Task> duplicates = new List<Task>();
        for (List<Task> group : groupBySubject(tasks).values()) {
            for (Integer i = 1; i < group.size(); i++) {
                duplicates.add(new Task(Id = group[i].Id, Status = 'Completed'));
            }
        }
        if (!duplicates.isEmpty()) {
            update duplicates;
        }
        return duplicates;
    }
}
