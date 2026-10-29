/**
 * Account summary shown to agents on the Case page (caseAccountSummary LWC).
 * Reads standard Account fields only.
 */
public with sharing class CaseAccountSummaryController {

    @AuraEnabled(cacheable=true)
    public static AccountSummary getSummary(Id caseId) {
        List<Case> rows = [
            SELECT Id, AccountId, Account.Name, Account.Type, Account.Industry,
                   Account.Rating, Account.Phone, Account.Owner.Name
            FROM Case
            WHERE Id = :caseId
            WITH USER_MODE
            LIMIT 1
        ];
        if (rows.isEmpty() || rows[0].AccountId == null) {
            return null;
        }
        Account a = rows[0].Account;
        AccountSummary s = new AccountSummary();
        s.accountId = rows[0].AccountId;
        s.name = a.Name;
        s.type = a.Type;
        s.industry = a.Industry;
        s.rating = a.Rating;
        s.phone = a.Phone;
        s.ownerName = a.Owner?.Name;
        return s;
    }

    public class AccountSummary {
        @AuraEnabled public Id accountId;
        @AuraEnabled public String name;
        @AuraEnabled public String type;
        @AuraEnabled public String industry;
        @AuraEnabled public String rating;
        @AuraEnabled public String phone;
        @AuraEnabled public String ownerName;
    }
}
