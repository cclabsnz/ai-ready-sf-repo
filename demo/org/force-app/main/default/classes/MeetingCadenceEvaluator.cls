/**
 * Bands Contact records by meeting cadence days for meeting cadence.
 *
 * Records at or above HIGH_THRESHOLD are High, at or above MEDIUM_THRESHOLD are Medium, anything
 * lower is Low and a blank value is None. stampBands writes the band to Outreach_Priority__c, and
 * bandForRecord feeds the meetingCadenceBadge component.
 */
public with sharing class MeetingCadenceEvaluator {

    public static final Decimal HIGH_THRESHOLD = 5000;
    public static final Decimal MEDIUM_THRESHOLD = 2500;
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
        List<Contact> rows = [
            SELECT Id, Meeting_Cadence_Days__c
            FROM Contact
            WHERE Id IN :recordIds
            WITH USER_MODE
        ];
        for (Contact row : rows) {
            bands.put(row.Id, bandFor(row.Meeting_Cadence_Days__c));
        }
        return bands;
    }

    /** Writes the band to Outreach_Priority__c on the records whose stored band differs. */
    public static void stampBands(List<Contact> rows) {
        List<Contact> changed = new List<Contact>();
        for (Contact row : rows) {
            String band = bandFor(row.Meeting_Cadence_Days__c);
            if (row.Outreach_Priority__c != band) {
                changed.add(new Contact(Id = row.Id, Outreach_Priority__c = band));
            }
        }
        if (!changed.isEmpty()) {
            Database.update(changed, AccessLevel.USER_MODE);
        }
    }

    /**
     * The band of one record for the meetingCadenceBadge component. Null when the record is not visible.
     * cacheable=true: the client may show a stale band until the record page refreshes.
     */
    @AuraEnabled(cacheable=true)
    public static String bandForRecord(Id recordId) {
        List<Contact> rows = [
            SELECT Id, Meeting_Cadence_Days__c
            FROM Contact
            WHERE Id = :recordId
            WITH USER_MODE
            LIMIT 1
        ];
        return rows.isEmpty() ? null : bandFor(rows[0].Meeting_Cadence_Days__c);
    }
}
