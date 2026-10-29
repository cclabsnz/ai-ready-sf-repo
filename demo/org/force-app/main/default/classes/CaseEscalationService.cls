/**
 * Case escalation rules.
 *
 * The escalation level of a case depends on the customer's contracted service level (Account) and,
 * for premium customers, on how long the case has been open against the premium SLA on its
 * entitlement:
 *   - Standard customers escalate to Level 1.
 *   - Premium customers escalate to Level 1, or straight to Level 2 once the case has been open
 *     for at least the entitlement's premium SLA hours.
 *
 * Called from CaseTriggerHandler (before and after update), EscalationNotifier (invocable, from the
 * Case_Escalate_Premium flow) and the caseEscalationPanel LWC.
 */
public with sharing class CaseEscalationService {

    public static final String LEVEL_NONE = 'Not Escalated';
    public static final String LEVEL_1 = 'Level 1';
    public static final String LEVEL_2 = 'Level 2';
    public static final String PREMIUM = 'Premium';

    private static final Decimal MILLIS_PER_HOUR = 3600000;

    /**
     * Before update: sets the escalation level on cases that have just been escalated.
     * One query per related object, whatever the batch size.
     */
    public static void applyEscalation(List<Case> cases, Map<Id, Case> oldMap) {
        List<Case> newlyEscalated = new List<Case>();
        Set<Id> accountIds = new Set<Id>();
        Set<Id> entitlementIds = new Set<Id>();
        for (Case c : cases) {
            Case before = oldMap.get(c.Id);
            if (c.IsEscalated && before != null && !before.IsEscalated) {
                newlyEscalated.add(c);
                if (c.AccountId != null) {
                    accountIds.add(c.AccountId);
                }
                if (c.EntitlementId != null) {
                    entitlementIds.add(c.EntitlementId);
                }
            }
        }
        if (newlyEscalated.isEmpty()) {
            return;
        }

        Map<Id, Account> accounts = new Map<Id, Account>(
            [SELECT Id, Service_Level__c FROM Account WHERE Id IN :accountIds WITH USER_MODE]
        );
        Map<Id, Entitlement> entitlements = new Map<Id, Entitlement>(
            [SELECT Id, Premium_SLA_Hours__c FROM Entitlement WHERE Id IN :entitlementIds WITH USER_MODE]
        );

        Datetime now = Datetime.now();
        for (Case c : newlyEscalated) {
            Account acct = accounts.get(c.AccountId);
            Entitlement ent = entitlements.get(c.EntitlementId);
            c.Escalation_Level__c = levelFor(
                acct?.Service_Level__c,
                ent?.Premium_SLA_Hours__c,
                hoursBetween(c.CreatedDate, now)
            );
        }
    }

    /**
     * After update: records a private case comment for every case whose escalation level changed,
     * so the reason survives later edits to the case.
     */
    public static void recordEscalationReasons(List<Case> cases, Map<Id, Case> oldMap) {
        List<CaseComment> comments = new List<CaseComment>();
        for (Case c : cases) {
            Case before = oldMap.get(c.Id);
            if (before == null || c.Escalation_Level__c == before.Escalation_Level__c
                    || c.Escalation_Level__c == null || c.Escalation_Level__c == LEVEL_NONE) {
                continue;
            }
            String body = 'Escalated to ' + c.Escalation_Level__c + '.';
            if (String.isNotBlank(c.Escalation_Reason__c)) {
                body += ' Reason: ' + c.Escalation_Reason__c;
            }
            comments.add(new CaseComment(ParentId = c.Id, CommentBody = body.abbreviate(4000), IsPublished = false));
        }
        if (!comments.isEmpty()) {
            Database.insert(comments, AccessLevel.USER_MODE);
        }
    }

    /**
     * The cases among caseIds whose account is on the premium service level.
     * Used by EscalationNotifier, which does not read the account itself.
     */
    public static List<Case> premiumCases(Set<Id> caseIds) {
        if (caseIds == null || caseIds.isEmpty()) {
            return new List<Case>();
        }
        return [
            SELECT Id, CaseNumber, Subject, OwnerId, Escalation_Level__c
            FROM Case
            WHERE Id IN :caseIds AND Account.Service_Level__c = :PREMIUM
            WITH USER_MODE
        ];
    }

    /**
     * Escalation state for the caseEscalationPanel LWC. Null when the case is not visible.
     * cacheable=true: the client caches the result, so hoursOpen and slaBreached can be stale
     * until the record page refreshes (refreshApex or a record change).
     */
    @AuraEnabled(cacheable=true)
    public static EscalationState getEscalationState(Id caseId) {
        List<Case> rows = [
            SELECT Id, IsEscalated, Escalation_Level__c, CreatedDate,
                   Account.Service_Level__c, Entitlement.Premium_SLA_Hours__c
            FROM Case
            WHERE Id = :caseId
            WITH USER_MODE
            LIMIT 1
        ];
        if (rows.isEmpty()) {
            return null;
        }
        Case c = rows[0];
        EscalationState state = new EscalationState();
        state.isEscalated = c.IsEscalated;
        state.level = String.isBlank(c.Escalation_Level__c) ? LEVEL_NONE : c.Escalation_Level__c;
        state.serviceLevel = c.Account?.Service_Level__c;
        state.isPremium = state.serviceLevel == PREMIUM;
        state.premiumSlaHours = c.Entitlement?.Premium_SLA_Hours__c;
        state.hoursOpen = hoursBetween(c.CreatedDate, Datetime.now()).setScale(1);
        state.slaBreached = state.isPremium && state.premiumSlaHours != null
            && state.hoursOpen >= state.premiumSlaHours;
        return state;
    }

    /** The level a case escalates to. Pure, so the rule is testable without records. */
    @TestVisible
    private static String levelFor(String serviceLevel, Decimal premiumSlaHours, Decimal hoursOpen) {
        if (serviceLevel != PREMIUM) {
            return LEVEL_1;
        }
        if (premiumSlaHours != null && hoursOpen != null && hoursOpen >= premiumSlaHours) {
            return LEVEL_2;
        }
        return LEVEL_1;
    }

    @TestVisible
    private static Decimal hoursBetween(Datetime fromTime, Datetime toTime) {
        if (fromTime == null || toTime == null) {
            return 0;
        }
        return Decimal.valueOf(toTime.getTime() - fromTime.getTime()) / MILLIS_PER_HOUR;
    }

    public class EscalationState {
        @AuraEnabled public Boolean isEscalated;
        @AuraEnabled public String level;
        @AuraEnabled public String serviceLevel;
        @AuraEnabled public Boolean isPremium;
        @AuraEnabled public Decimal premiumSlaHours;
        @AuraEnabled public Decimal hoursOpen;
        @AuraEnabled public Boolean slaBreached;
    }
}
