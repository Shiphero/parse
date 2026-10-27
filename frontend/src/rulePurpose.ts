import type { CheckDefinition, CheckStatus, RuleSpec, RuleTypeDefinition } from './api';
export const rulePurposeLabels = {
  general_guidance: 'General guidance',
  shipment_validation: 'Shipment validation',
  unclassified: 'Needs classification',
} as const;

type VerificationKind = 'automatic' | 'manual' | 'external' | 'unresolved' | 'guidance';
type VerificationSummary = {kind:VerificationKind; label:string; detail:string; unavailable?:boolean};

export function resolveCheckStatus(rule:RuleSpec, checks:CheckDefinition[]|null, types:RuleTypeDefinition[]|null):CheckStatus|undefined {
  if (rule.execution_mode === 'reference_only') return {label:'Automatic verification unavailable',availability:'reference_only'};
  if (rule.standard_check) {
    return checks?.find(check=>check.id===rule.standard_check?.check_id&&check.version===rule.standard_check.version);
  }
  const type=types?.find(type=>type.id===rule.rule_type?.id&&type.version===rule.rule_type.version);
  if (type&&!type.check_ids.length&&['human','external_evidence'].includes(rule.verification)) {
    return {label:type.label,availability:rule.verification==='human'?'manual':'external'};
  }
  if (rule.schema_version==='1.2'&&rule.purpose==='shipment_validation') return {label:'Choose a verification check',availability:'needs_mapping'};
  return {label:'Existing verification',availability:'legacy'};
}

export function verificationSummary(rule: RuleSpec, status?:CheckStatus): VerificationSummary {
  if (rule.execution_mode === 'reference_only') return {kind:'unresolved',label:'Reference requirement',detail:'Can be approved as an instruction; automatic verification is unavailable.',unavailable:true};
  if (rule.purpose === 'general_guidance') return {kind:'guidance',label:'Guidance only',detail:'Reference instructions; no shipment verification.'};
  if (rule.purpose !== 'shipment_validation') return {kind:'unresolved',label:'Not classified',detail:'Choose how this rule will be used before setting verification.'};
  if (status?.availability === 'needs_mapping') return {kind:'unresolved',label:'Not configured',detail:'Choose a verification check.'};
  if (status?.availability === 'not_implemented') return {kind:'automatic',label:'Automatic',detail:'Unavailable — cannot run yet',unavailable:true};
  if (status?.availability === 'implemented') return {kind:'automatic',label:'Automatic',detail:'Checks shipment data.'};
  if (rule.standard_check && !status) {
    const method={data:{kind:'automatic',label:'Automatic'},human:{kind:'manual',label:'Manual'},external_evidence:{kind:'external',label:'External confirmation'},unresolved:{kind:'unresolved',label:'Not configured'}} as const;
    return {...method[rule.verification],detail:'Check availability not loaded',unavailable:true};
  }
  if (rule.verification === 'external_evidence') return {kind:'external',label:'External confirmation',detail:'Requires supporting evidence or confirmation from another party.'};
  if (rule.verification === 'human') return {kind:'manual',label:'Manual',detail:'A person inspects and verifies this requirement.'};
  if (rule.verification === 'data') return {kind:'automatic',label:'Automatic',detail:'Existing check using shipment data.'};
  return {kind:'unresolved',label:'Not configured',detail:'Choose a verification method.'};
}
