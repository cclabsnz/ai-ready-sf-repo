public without sharing class LegacyAccountUtil {
    // without sharing: nightly batch needs cross-owner visibility; see RAID-14
    public static Decimal score(Account a) { return a.Legacy_Score__c; }
}
