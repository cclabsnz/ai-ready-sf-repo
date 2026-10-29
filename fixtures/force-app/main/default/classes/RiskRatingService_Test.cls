@isTest
private class RiskRatingService_Test {
    @isTest static void highScoreIsHigh() {
        Account a = new Account(Name='T', Legacy_Score__c=90);
        insert a;
        RiskRatingService.recalculate(new Set<Id>{a.Id});
        System.assertEquals('High', [SELECT Risk_Rating__c FROM Account WHERE Id=:a.Id].Risk_Rating__c);
    }
}
