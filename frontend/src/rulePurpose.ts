import type { CheckStatus } from './api';
export const rulePurposeLabels = {
  general_guidance: 'General guidance',
  shipment_validation: 'Shipment validation',
  unclassified: 'Needs classification',
} as const;

export function shipmentCheckMode(rule: {purpose?: string; verification: string}, status?:CheckStatus) {
  if (rule.purpose === 'general_guidance') return 'Not a shipment check';
  if (rule.purpose !== 'shipment_validation') return 'Needs classification';
  if (status?.availability==='needs_mapping') return 'Needs mapping to a standard verification check';
  if (status&&status.availability!=='legacy') return `${status.label} · ${status.availability.replaceAll('_',' ')}`;
  if (rule.verification === 'unresolved') return 'Shipment check method unresolved';
  return rule.verification === 'data' ? 'Automatic shipment check' : 'Shipment inspection / evidence';
}

export function shipmentCheckLabel(rule: {purpose?: string; verification: string}, status?:CheckStatus) {
  if (rule.purpose === 'general_guidance') return '—';
  if (rule.purpose !== 'shipment_validation') return 'Unclassified';
  if (status?.availability==='needs_mapping') return 'Needs mapping';
  if (status?.availability==='not_implemented') return 'Not available';
  if (rule.verification === 'external_evidence') return 'External';
  if (rule.verification === 'data') return 'Automatic';
  if (rule.verification === 'unresolved') return 'Unresolved';
  return 'Manual';
}
