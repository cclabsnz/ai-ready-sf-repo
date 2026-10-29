import { LightningElement, api, wire } from 'lwc';
import getBand from '@salesforce/apex/ResponseTrackingEvaluator.bandForRecord';

export default class ResponseTrackingCard extends LightningElement {
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
