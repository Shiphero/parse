import type { RuleSpec } from './api';

export type ConditionField = {
  path: string;
  label: string;
  type: 'number' | 'text';
  unit?: 'in' | 'lb';
  help?: string;
};

// Paths match the normalized scenario data and the evaluator's per-subject context.
const shipmentFields: ConditionField[] = [
  {path:'shipment.customer_po_number',label:'Customer PO number',type:'text'},
  {path:'shipment.department',label:'Department',type:'text'},
  {path:'shipment.destination.country',label:'Destination country',type:'text'},
  {path:'shipment.destination.state',label:'Destination state',type:'text'},
  {path:'shipment.destination.zip',label:'Destination ZIP / postal code',type:'text'},
  {path:'shipment.distribution_center_number',label:'Distribution center number',type:'text'},
  {path:'shipment.mode',label:'Shipping mode',type:'text',help:'Provide shipment.mode in scenario JSON or overrides; the ShipHero import does not populate it.'},
  {path:'shipment.shipping_option',label:'Shipping option',type:'text'},
  {path:'shipment.store_location_number',label:'Store location number',type:'text'},
];

export function conditionFields(subject: RuleSpec['subject']): ConditionField[] {
  const dimensions: ConditionField[] = subject==='carton'||subject==='pallet' ? [
    {path:'height',label:`${subject==='carton'?'Carton':'Pallet'} height`,type:'number',unit:'in'},
    {path:'length',label:`${subject==='carton'?'Carton':'Pallet'} length`,type:'number',unit:'in'},
    {path:'weight',label:`${subject==='carton'?'Carton':'Pallet'} weight`,type:'number',unit:'lb'},
    {path:'width',label:`${subject==='carton'?'Carton':'Pallet'} width`,type:'number',unit:'in'},
  ] : [];
  const itemFields: ConditionField[] = subject==='item' ? [
    {path:'sku',label:'Item SKU',type:'text',help:'Uses the SKU supplied on each item in the scenario.'},
    {path:'quantity',label:'Item quantity',type:'number',help:'Uses the supplied item quantity; case quantities are not converted to eaches.'},
  ] : [];
  return [...dimensions, ...itemFields, ...shipmentFields].sort((a,b)=>a.label.localeCompare(b.label));
}
