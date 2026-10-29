/**
 * Bands Opportunity records by discount pct for discount guard.
 *
 * Records at or above HIGH_THRESHOLD are High, at or above MEDIUM_THRESHOLD are Medium, anything
 * lower is Low and a blank value is None. stampBands writes the band to Review_Status_Label__c, and
 * bandForRecord feeds the record page.
 */
public with sharing class DiscountGuardService {

    public static final Decimal HIGH_THRESHOLD = 80;
    public static final Decimal MEDIUM_THRESHOLD = 40;
    public static final String BAND_HIGH = 'High';
    public static final String BAND_MEDIUM = 'Medium';
    public static final String BAND_LOW = 'Low';
    public static final String BAND_NONE = 'None';

    /** The band for a value. Pure, so the rule is testable without records. */
    public static String bandFor(Decimal value) {
        if (value == null) {
            return BAND_NONE;
        }
        if (value >= HIGH_THRESHOLD) {
            return BAND_HIGH;
        }
        if (value >= MEDIUM_THRESHOLD) {
            return BAND_MEDIUM;
        }
        return BAND_LOW;
    }

    /** Bands for the given records, read in one query whatever the batch size. */
    public static Map<Id, String> bandsFor(Set<Id> recordIds) {
        Map<Id, String> bands = new Map<Id, String>();
        if (recordIds == null || recordIds.isEmpty()) {
            return bands;
        }
        List<Opportunity> rows = [
            SELECT Id, Discount_Pct__c
            FROM Opportunity
            WHERE Id IN :recordIds
            WITH USER_MODE
        ];
        for (Opportunity row : rows) {
            bands.put(row.Id, bandFor(row.Discount_Pct__c));
        }
        return bands;
    }

    /** Writes the band to Review_Status_Label__c on the records whose stored band differs. */
    public static void stampBands(List<Opportunity> rows) {
        List<Opportunity> changed = new List<Opportunity>();
        for (Opportunity row : rows) {
            String band = bandFor(row.Discount_Pct__c);
            if (row.Review_Status_Label__c != band) {
                changed.add(new Opportunity(Id = row.Id, Review_Status_Label__c = band));
            }
        }
        if (!changed.isEmpty()) {
            Database.update(changed, AccessLevel.USER_MODE);
        }
    }

    /**
     * The band of one record for the record page. Null when the record is not visible.
     * cacheable=true: the client may show a stale band until the record page refreshes.
     */
    @AuraEnabled(cacheable=true)
    public static String bandForRecord(Id recordId) {
        List<Opportunity> rows = [
            SELECT Id, Discount_Pct__c
            FROM Opportunity
            WHERE Id = :recordId
            WITH USER_MODE
            LIMIT 1
        ];
        return rows.isEmpty() ? null : bandFor(rows[0].Discount_Pct__c);
    }
}
