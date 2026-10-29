public with sharing class RiskRatingService {
    public static void recalculate(Set<Id> accountIds) {
        List<Account> accts = [SELECT Id, Risk_Rating__c, Legacy_Score__c FROM Account WHERE Id IN :accountIds WITH USER_MODE];
        for (Account a : accts) {
            a.Risk_Rating__c = a.Legacy_Score__c > 70 ? 'High' : 'Low';
        }
        Database.update(accts, AccessLevel.USER_MODE);
    }
}
