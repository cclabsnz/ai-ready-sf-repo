// Deliberate sign of age for the demo inventory: pinned to API 52.0, with no user-mode enforcement.
// Plain SOQL and DML, as code written before user mode existed would be; the rule baseline (WS8)
// records it as debt. Kept as is.
/**
 * Bands Opportunity records by contract term months for contract term.
 *
 * Records at or above HIGH_THRESHOLD are High, at or above MEDIUM_THRESHOLD are Medium, anything
 * lower is Low and a blank value is None. stampBands writes the band to Review_Status_Label__c, and
 * bandForRecord feeds the record page.
 */
public with sharing class ContractTermService {

    public static final Decimal HIGH_THRESHOLD = 100;
    public static final Decimal MEDIUM_THRESHOLD = 50;
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
            SELECT Id, Contract_Term_Months__c
            FROM Opportunity
            WHERE Id IN :recordIds
        ];
        for (Opportunity row : rows) {
            bands.put(row.Id, bandFor(row.Contract_Term_Months__c));
        }
        return bands;
    }

    /** Writes the band to Review_Status_Label__c on the records whose stored band differs. */
    public static void stampBands(List<Opportunity> rows) {
        List<Opportunity> changed = new List<Opportunity>();
        for (Opportunity row : rows) {
            String band = bandFor(row.Contract_Term_Months__c);
            if (row.Review_Status_Label__c != band) {
                changed.add(new Opportunity(Id = row.Id, Review_Status_Label__c = band));
            }
        }
        if (!changed.isEmpty()) {
            update changed;
        }
    }

    /**
     * The band of one record for the record page. Null when the record is not visible.
     * cacheable=true: the client may show a stale band until the record page refreshes.
     */
    @AuraEnabled(cacheable=true)
    public static String bandForRecord(Id recordId) {
        List<Opportunity> rows = [
            SELECT Id, Contract_Term_Months__c
            FROM Opportunity
            WHERE Id = :recordId
            LIMIT 1
        ];
        return rows.isEmpty() ? null : bandFor(rows[0].Contract_Term_Months__c);
    }
}
