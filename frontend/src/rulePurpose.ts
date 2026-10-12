export const rulePurposeLabels = {
  general_guidance: 'General guidance',
  shipment_validation: 'Shipment validation',
  unclassified: 'Needs classification',
} as const;

export function shipmentCheckMode(rule: {purpose?: string; verification: string}) {
  if (rule.purpose === 'general_guidance') return 'Not a shipment check';
  if (rule.purpose !== 'shipment_validation') return 'Needs classification';
  return rule.verification === 'data' ? 'Automatic shipment check' : 'Shipment inspection / evidence';
}
