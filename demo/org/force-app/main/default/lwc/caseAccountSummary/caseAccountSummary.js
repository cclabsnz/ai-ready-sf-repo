import { LightningElement, api, wire } from 'lwc';
import getSummary from '@salesforce/apex/CaseAccountSummaryController.getSummary';

export default class CaseAccountSummary extends LightningElement {
    @api recordId;

    summary;
    error;

    @wire(getSummary, { caseId: '$recordId' })
    wiredSummary({ data, error }) {
        this.summary = data;
        this.error = error;
    }

    get hasSummary() {
        return !!this.summary;
    }

    get noAccount() {
        return !this.summary && !this.error;
    }
}
