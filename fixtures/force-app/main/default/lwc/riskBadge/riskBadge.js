import { LightningElement, api } from 'lwc';
import recalculate from '@salesforce/apex/RiskRatingService.recalculate';
export default class RiskBadge extends LightningElement { @api recordId; }
