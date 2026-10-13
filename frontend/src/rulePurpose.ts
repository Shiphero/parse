export const rulePurposeLabels = {
  general_guidance: 'General guidance',
  shipment_validation: 'Shipment validation',
  unclassified: 'Needs classification',
} as const;

export function shipmentCheckMode(rule: {purpose?: string; verification: string}) {
  if (rule.purpose === 'general_guidance') return 'Not a shipment check';
  if (rule.purpose !== 'shipment_validation') return 'Needs classification';
  if (rule.verification === 'unresolved') return 'Shipment check method unresolved';
  return rule.verification === 'data' ? 'Automatic shipment check' : 'Shipment inspection / evidence';
}

export function shipmentCheckLabel(rule: {purpose?: string; verification: string}) {
  if (rule.purpose === 'general_guidance') return '—';
  if (rule.purpose !== 'shipment_validation') return 'Unclassified';
  if (rule.verification === 'data') return 'Automatic';
  if (rule.verification === 'unresolved') return 'Unresolved';
  return 'Manual';
}
