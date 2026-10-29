/**
 * Round-robin case assignment (placeholder).
 *
 * Today this only re-assigns cases handed back to New during an update, across the active users
 * in the Escalation_Agents queue. Assignment of newly created cases is not built yet.
 *
 * Placeholder limitation: the round-robin position is not stored, so it restarts at the first
 * agent in every transaction. Across many small updates the first agents get more cases.
 */
public with sharing class CaseAssignmentService {

    public static final String STATUS_NEW = 'New';
    public static final String AGENT_QUEUE = 'Escalation_Agents';

    @TestVisible
    private static List<Id> agentPoolOverride;

    public static void assign(List<Case> cases, Map<Id, Case> oldMap) {
        List<Case> toAssign = new List<Case>();
        for (Case c : cases) {
            Case before = oldMap.get(c.Id);
            if (before != null && c.Status == STATUS_NEW && before.Status != STATUS_NEW) {
                toAssign.add(c);
            }
        }
        if (toAssign.isEmpty()) {
            return;
        }
        List<Id> pool = agentPool();
        if (pool.isEmpty()) {
            return;
        }
        Integer next = 0; // restarts each transaction; see class comment
        for (Case c : toAssign) {
            c.OwnerId = pool[Math.mod(next, pool.size())];
            next++;
        }
    }

    /** Active users who are direct members of the agent queue, in a stable order. */
    @TestVisible
    private static List<Id> agentPool() {
        if (agentPoolOverride != null) {
            return agentPoolOverride;
        }
        Set<Id> memberIds = new Set<Id>();
        for (GroupMember gm : [
            SELECT UserOrGroupId
            FROM GroupMember
            WHERE Group.DeveloperName = :AGENT_QUEUE AND Group.Type = 'Queue'
            WITH USER_MODE
        ]) {
            if (gm.UserOrGroupId.getSObjectType() == User.SObjectType) {
                memberIds.add(gm.UserOrGroupId);
            }
        }
        List<Id> pool = new List<Id>();
        if (memberIds.isEmpty()) {
            return pool;
        }
        for (User u : [
            SELECT Id FROM User WHERE Id IN :memberIds AND IsActive = true WITH USER_MODE ORDER BY Id
        ]) {
            pool.add(u.Id);
        }
        return pool;
    }
}
