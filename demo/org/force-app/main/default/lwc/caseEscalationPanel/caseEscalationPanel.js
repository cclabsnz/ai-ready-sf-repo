import { LightningElement, api, wire } from 'lwc';
import getEscalationState from '@salesforce/apex/CaseEscalationService.getEscalationState';

export default class CaseEscalationPanel extends LightningElement {
    @api recordId;

    state;
    error;

    @wire(getEscalationState, { caseId: '$recordId' })
    wiredState({ data, error }) {
        this.state = data;
        this.error = error;
    }

    get hasState() {
        return !!this.state;
    }

    get tierLabel() {
        return this.state && this.state.isPremium ? 'Premium customer' : 'Standard customer';
    }

    get levelLabel() {
        return this.state ? this.state.level : '';
    }

    get slaLabel() {
        if (!this.state || this.state.premiumSlaHours == null) {
            return 'No premium SLA';
        }
        return `${this.state.hoursOpen} of ${this.state.premiumSlaHours} SLA hours used`;
    }

    get slaBreached() {
        return !!(this.state && this.state.slaBreached);
    }

    get errorMessage() {
        return this.error && this.error.body ? this.error.body.message : 'Escalation details are unavailable.';
    }
}
