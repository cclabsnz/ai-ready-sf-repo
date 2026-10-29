/**
 * Dispatcher for CaseTrigger. Holds no business rules; each context delegates to a service.
 */
public with sharing class CaseTriggerHandler {

    @TestVisible
    private static Boolean bypass = false;

    public static void handle(System.TriggerOperation operation, List<Case> newCases, Map<Id, Case> oldMap) {
        if (bypass) {
            return;
        }
        switch on operation {
            when BEFORE_UPDATE {
                CaseEscalationService.applyEscalation(newCases, oldMap);
                CaseAssignmentService.assign(newCases, oldMap);
            }
            when AFTER_UPDATE {
                CaseEscalationService.recordEscalationReasons(newCases, oldMap);
            }
            when else {
                return;
            }
        }
    }
}
