import type { RuleSpec } from './api';

export const operationalCategoryLabels: Record<NonNullable<RuleSpec['operational_category']>, string> = {
  warehouse_operations: 'Warehouse operations',
  transportation_scheduling: 'Transportation & scheduling',
  electronic_documents_edi: 'Electronic documents & EDI',
  business_administration: 'Business administration',
  unclassified: 'Needs categorization',
};
export const consumptionPointLabels: Record<NonNullable<RuleSpec['consumption_points']>[number], string> = {
  mobile_picking: 'Mobile picking', mobile_packing: 'Mobile packing',
  label_generation: 'Label generation', label_application: 'Label application',
  pallet_building: 'Pallet building', warehouse_loading: 'Staging & loading',
  transport_planning: 'Transportation planning', pickup_scheduling: 'Pickup scheduling',
  delivery_scheduling: 'Delivery scheduling', document_generation: 'Document generation', document_transmission: 'Document delivery (email / portal)',
  asn_generation: 'ASN generation & validation', edi_transmission: 'EDI transmission',
  supplier_onboarding: 'Supplier onboarding', supplier_management: 'Supplier management',
  product_setup: 'Product setup', order_management: 'Order management',
  billing: 'Billing', compliance_disputes: 'Compliance & disputes',
};
export const consumptionPointOptions = Object.entries(consumptionPointLabels)
  .sort(([, left], [, right]) => left.localeCompare(right));
export const needsClassification = (spec: RuleSpec) => (spec.purpose || 'unclassified') === 'unclassified'
  || (spec.operational_category || 'unclassified') === 'unclassified' || !spec.consumption_points?.length;
