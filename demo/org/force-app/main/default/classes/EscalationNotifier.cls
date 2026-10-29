/**
 * Invocable action used by the Case_Escalate_Premium flow.
 *
 * Creates a follow-up task for the owner of each case that belongs to a premium customer. Whether a
 * customer is premium is decided by CaseEscalationService; this class does not read the account.
 */
public with sharing class EscalationNotifier {

    public static final String TASK_SUBJECT_PREFIX = 'Premium escalation: case ';

    public class Request {
        @InvocableVariable(label='Case Id' required=true)
        public Id caseId;
    }

    public class Result {
        @InvocableVariable(label='Owner notified')
        public Boolean notified;
    }

    @InvocableMethod(label='Notify Premium Escalation'
                     description='Creates a follow-up task for the owner of a premium customer case.'
                     category='Case Escalation')
    public static List<Result> notify(List<Request> requests) {
        Set<Id> caseIds = new Set<Id>();
        for (Request r : requests) {
            if (r != null && r.caseId != null) {
                caseIds.add(r.caseId);
            }
        }

        Set<Id> notifiedCaseIds = new Set<Id>();
        List<Task> followUps = new List<Task>();
        for (Case c : CaseEscalationService.premiumCases(caseIds)) {
            if (c.OwnerId == null || c.OwnerId.getSObjectType() != User.SObjectType) {
                continue; // queue-owned: nobody to notify yet
            }
            followUps.add(new Task(
                OwnerId = c.OwnerId,
                WhatId = c.Id,
                Subject = TASK_SUBJECT_PREFIX + c.CaseNumber,
                Priority = 'High',
                Status = 'Not Started',
                ActivityDate = Date.today()
            ));
            notifiedCaseIds.add(c.Id);
        }
        if (!followUps.isEmpty()) {
            Database.insert(followUps, AccessLevel.USER_MODE);
        }

        List<Result> results = new List<Result>();
        for (Request r : requests) {
            Result res = new Result();
            res.notified = r != null && notifiedCaseIds.contains(r.caseId);
            results.add(res);
        }
        return results;
    }
}
