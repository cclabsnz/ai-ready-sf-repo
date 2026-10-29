import { LightningElement, api, wire } from 'lwc';
import getBand from '@salesforce/apex/PricingExceptionService.bandForRecord';

export default class PricingExceptionBadge extends LightningElement {
    @api recordId;

    band;
    error;

    @wire(getBand, { recordId: '$recordId' })
    wiredBand({ data, error }) {
        this.band = data;
        this.error = error;
    }

    get hasBand() {
        return !!this.band;
    }
}
